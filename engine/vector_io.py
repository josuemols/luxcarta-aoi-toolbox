"""
Read messy real-world vector uploads (zipped shapefiles, MapInfo TAB/MIF,
nested-folder KMZ, GeoJSON) into WGS84 GeoDataFrames, and write clean
KML/KMZ that the quote tool and Google Earth both read.

The quote engine (make_aoi.measure_kmz) extracts the AOI name with a regex on
the <name> element inside each <Placemark> — so every writer here always sets
the placemark-level <name>, plus an ExtendedData 'city'/'name' field as backup.
"""
import io
import os
import re
import zipfile
import tempfile
import xml.etree.ElementTree as ET

import geopandas as gpd
import simplekml
from shapely.geometry import shape, Point, LineString, Polygon, MultiPolygon
from shapely.ops import unary_union

VECTOR_EXTS = {".shp", ".tab", ".mif", ".kml", ".kmz", ".geojson", ".json", ".gpkg"}
SIDECAR_EXTS = {".dbf", ".shx", ".prj", ".cpg", ".dat", ".map", ".id", ".ind", ".mid", ".qix", ".sbn", ".sbx"}
NAME_FIELD_HINTS = ("name", "city", "nom", "ville", "label", "title", "nombre", "ciudad", "aoi", "id")


class VectorReadError(Exception):
    """User-facing read failure — message is safe to show in the UI."""


# ---------------------------------------------------------------- reading

def read_uploads(uploaded):
    """uploaded: list of (filename, bytes). Returns (GeoDataFrame, warnings).

    Reads EVERY dataset in the upload — a .zip with five shapefiles yields the
    features of all five, each row tagged with its source file in 'src_file'
    (often the only reliable site name in multi-file bundles).

    The gdf is in EPSG:4326 unless no CRS was defined (gdf.crs is None then —
    caller must ask the user and call assume_crs())."""
    warnings = []
    with tempfile.TemporaryDirectory() as tmp:
        mains = _stage_files(uploaded, tmp, warnings)
        if not mains:
            raise VectorReadError(
                "No readable vector file found. Upload a .zip shapefile, "
                ".shp with its .dbf/.shx/.prj, a MapInfo .tab/.mif, a .kml/.kmz or GeoJSON.")
        frames, crsless = [], []
        for main in mains:
            ext = os.path.splitext(main)[1].lower()
            stem = re.sub(r"__\d+$", "", os.path.splitext(os.path.basename(main))[0])
            if ext in (".kml", ".kmz"):
                feats = parse_kml_features(open(main, "rb").read(), is_kmz=(ext == ".kmz"))
                if not feats:
                    continue
                g = gpd.GeoDataFrame(
                    {"name": [f["name"] for f in feats]},
                    geometry=[f["geom"] for f in feats], crs="EPSG:4326")
            else:
                try:
                    g = gpd.read_file(main)
                except Exception as e:
                    raise VectorReadError(f"Could not read {os.path.basename(main)}: {e}")
                if g.empty:
                    continue
                if g.crs is None:
                    crsless.append(os.path.basename(main))
                else:
                    g = g.to_crs("EPSG:4326")
            g["src_file"] = stem
            frames.append(g)
        if not frames:
            raise VectorReadError("The file(s) contain no features.")
        if crsless and len(crsless) < len(frames):
            raise VectorReadError(
                "Some of the files don't say which coordinate system they use ("
                + ", ".join(crsless[:5]) +
                ") while others do — upload those separately so the right one can be chosen.")
        if len(frames) == 1:
            gdf = frames[0]
        else:
            import pandas as pd
            gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=frames[0].crs)
        if crsless:
            warnings.append("no_crs")
        return gdf, warnings


def assume_crs(gdf, epsg):
    """Assign a user-chosen CRS to a CRS-less gdf, then convert to WGS84."""
    gdf = gdf.set_crs(epsg=int(epsg), allow_override=True)
    return gdf.to_crs("EPSG:4326")


def _fix_zip_name(zi):
    """Zip members without the UTF-8 flag are decoded as cp437 by Python —
    repair accented names (Alençon) when they were really UTF-8."""
    if zi.flag_bits & 0x800:
        return zi.filename
    try:
        return zi.filename.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return zi.filename


def _stage_files(uploaded, tmp, warnings):
    """Write uploads to disk, expanding zips (nested folders ok).
    Returns the sorted list of ALL main vector files found — a zip holding
    five shapefiles yields five entries, not just the first."""
    staged = []

    def _put(name, data):
        base = os.path.basename(name)
        if not base or base.startswith(("._", "~")):
            return
        if os.path.splitext(base)[1].lower() not in VECTOR_EXTS | SIDECAR_EXTS:
            return
        path = os.path.join(tmp, base)
        n = 1
        while os.path.exists(path):  # same basename arriving from different folders
            stem, e = os.path.splitext(base)
            n += 1
            path = os.path.join(tmp, f"{stem}__{n}{e}")
        open(path, "wb").write(data)
        staged.append(path)

    for fname, data in uploaded:
        if os.path.splitext(fname)[1].lower() == ".zip":
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    for zi in z.infolist():
                        if not zi.is_dir():
                            _put(_fix_zip_name(zi), z.read(zi))
            except zipfile.BadZipFile:
                raise VectorReadError(f"{os.path.basename(fname)} is not a valid .zip archive.")
        else:
            _put(fname, data)

    mains = [p for p in staged if os.path.splitext(p)[1].lower() in
             (".shp", ".tab", ".mif", ".kmz", ".kml", ".geojson", ".json", ".gpkg")]
    for p in mains:
        if p.lower().endswith(".shp"):
            stem = os.path.splitext(p)[0]
            missing = [e for e in (".dbf", ".shx") if not os.path.exists(stem + e)]
            if missing:
                raise VectorReadError(
                    f"Shapefile “{os.path.basename(p)}” is incomplete — also upload its "
                    + " and ".join(missing) + " sidecar file(s) (or a single .zip).")
            if not os.path.exists(stem + ".prj"):
                warnings.append("no_prj")
    return sorted(mains)


# ---------------------------------------------------------------- KML parse

_KML_NS = "{http://www.opengis.net/kml/2.2}"


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def kml_bytes_from_kmz(data):
    """Extract the KML from a KMZ, tolerating nested folders. doc.kml first."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        kmls = [n for n in z.namelist() if n.lower().endswith(".kml")]
        if not kmls:
            raise VectorReadError("The KMZ contains no .kml file.")
        kmls.sort(key=lambda n: (os.path.basename(n).lower() != "doc.kml", n.count("/")))
        return z.read(kmls[0])


def parse_kml_features(data, is_kmz=False):
    """Parse KML/KMZ bytes -> [{name, geom, attrs}] walking nested Folders.
    Geometries are merged per-placemark (MultiGeometry -> union)."""
    kml = kml_bytes_from_kmz(data) if is_kmz else data
    try:
        root = ET.fromstring(kml)
    except ET.ParseError as e:
        raise VectorReadError(f"The KML is not well-formed XML: {e}")
    feats = []
    for pm in root.iter():
        if _local(pm.tag) != "Placemark":
            continue
        name = None
        for child in pm:
            if _local(child.tag) == "name":
                name = (child.text or "").strip()
                break
        attrs = _extended_data(pm)
        geoms = _geoms_in(pm)
        if not geoms:
            continue
        geom = unary_union(geoms) if len(geoms) > 1 else geoms[0]
        feats.append({"name": name or "AOI", "geom": geom, "attrs": attrs})
    return feats


def _extended_data(pm):
    attrs = {}
    for el in pm.iter():
        tag = _local(el.tag)
        if tag == "Data":
            key = el.get("name")
            val = next((c.text for c in el if _local(c.tag) == "value"), None)
            if key:
                attrs[key] = (val or "").strip()
        elif tag == "SimpleData":
            key = el.get("name")
            if key:
                attrs[key] = (el.text or "").strip()
    return attrs


def _coords(text):
    pts = []
    for token in (text or "").split():
        parts = token.split(",")
        if len(parts) >= 2:
            pts.append((float(parts[0]), float(parts[1])))
    return pts


def _geoms_in(pm):
    geoms = []
    for el in pm.iter():
        tag = _local(el.tag)
        try:
            if tag == "Point":
                pts = _coords(_first_coords_text(el))
                if pts:
                    geoms.append(Point(pts[0]))
            elif tag == "LineString":
                pts = _coords(_first_coords_text(el))
                if len(pts) >= 2:
                    geoms.append(LineString(pts))
            elif tag == "Polygon":
                shell, holes = None, []
                for b in el.iter():
                    btag = _local(b.tag)
                    if btag in ("outerBoundaryIs", "innerBoundaryIs"):
                        pts = _coords(_first_coords_text(b))
                        if len(pts) >= 3:
                            if btag == "outerBoundaryIs":
                                shell = pts
                            else:
                                holes.append(pts)
                if shell:
                    poly = Polygon(shell, holes)
                    if not poly.is_valid:
                        poly = poly.buffer(0)
                    geoms.append(poly)
        except (ValueError, IndexError):
            continue  # skip malformed geometry, keep the rest
    return [g for g in geoms if g and not g.is_empty]


def _first_coords_text(el):
    for c in el.iter():
        if _local(c.tag) == "coordinates":
            return c.text
    return ""


# ---------------------------------------------------------------- KML write

def guess_name_field(gdf):
    """Best attribute column to use as the placemark name.

    Multi-file bundles (several shapefiles in one zip) often carry junk name
    attributes ("Untitled Polygon", empty) while the FILENAMES are the real
    city names — so 'src_file' wins unless an attribute column is complete
    and distinct."""
    cols = [c for c in gdf.columns if c not in (gdf.geometry.name, "src_file")]

    def _clean(c):
        v = gdf[c].astype(str).str.strip()
        return v.mask(v.str.lower().isin(("", "none", "nan")), "")

    hint_col = None
    for hint in NAME_FIELD_HINTS:
        for c in cols:
            if hint in c.lower() and _clean(c).any():
                hint_col = c
                break
        if hint_col:
            break

    multi = "src_file" in gdf.columns and gdf["src_file"].nunique() > 1
    if hint_col is not None:
        v = _clean(hint_col)
        complete_and_distinct = (v != "").all() and (len(gdf) == 1 or v.nunique() == len(gdf))
        if not multi or complete_and_distinct:
            return hint_col
    if multi:
        return "src_file"
    if hint_col is not None:
        return hint_col
    if cols:
        return cols[0]
    return "src_file" if "src_file" in gdf.columns else None


def write_kml_bytes(features, doc_name="AOI"):
    """features: [{name, geom, attrs}] in WGS84 -> KML bytes.
    Writes placemark <name> (the field the quote engine reads) + ExtendedData."""
    kml = simplekml.Kml(name=doc_name)
    line_style = simplekml.Color.red
    for f in features:
        name = (f.get("name") or "AOI").strip() or "AOI"
        attrs = dict(f.get("attrs") or {})
        attrs.setdefault("name", name)
        attrs.setdefault("city", name)
        for geom in _explode(f["geom"]):
            if geom.geom_type == "Polygon":
                pm = kml.newpolygon(name=name)
                pm.outerboundaryis = list(geom.exterior.coords)
                pm.innerboundaryis = [list(r.coords) for r in geom.interiors]
                pm.tessellate = 1
                pm.style.linestyle.color = line_style
                pm.style.linestyle.width = 2
                pm.style.polystyle.color = simplekml.Color.changealphaint(60, simplekml.Color.orange)
            elif geom.geom_type == "LineString":
                pm = kml.newlinestring(name=name, coords=list(geom.coords))
                pm.style.linestyle.color = line_style
                pm.style.linestyle.width = 3
            elif geom.geom_type == "Point":
                pm = kml.newpoint(name=name, coords=[(geom.x, geom.y)])
            else:
                continue
            for k, v in attrs.items():
                if v not in (None, ""):
                    pm.extendeddata.newdata(name=str(k), value=str(v))
    out = kml.kml()
    # The quote engine's parser (make_aoi.measure_kmz) matches a bare
    # <Polygon> tag; simplekml's id attributes would make it skip the feature
    # and fall back to the generic "AOI" name — strip them.
    out = re.sub(r'<(Polygon|LineString|Point|MultiGeometry|LinearRing)\s+id="[^"]*">', r"<\1>", out)
    return out.encode("utf-8")


def _explode(geom):
    if geom.geom_type.startswith("Multi") or geom.geom_type == "GeometryCollection":
        out = []
        for g in geom.geoms:
            out.extend(_explode(g))
        return out
    return [geom]


def kml_to_kmz_bytes(kml_bytes):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml_bytes)
    return buf.getvalue()


def quote_tool_name_check(kmz_bytes):
    """Round-trip check with the SAME regexes the quote engine uses
    (make_aoi.measure_kmz): returns the polygon names the quote table would
    show for this KMZ. Placemarks whose <Polygon> the engine can't match are
    excluded — exactly like the real parser."""
    kml = kml_bytes_from_kmz(kmz_bytes).decode("utf-8", "ignore")
    names = []
    for pm in re.findall(r"<Placemark[^>]*>([\s\S]*?)</Placemark>", kml):
        nm = re.search(r"<name>([^<]*)</name>", pm)
        poly = re.search(r"<Polygon>[\s\S]*?<coordinates>([\s\S]*?)</coordinates>", pm)
        if not poly:
            continue
        names.append(nm.group(1).strip() if nm else "AOI")
    return names


def safe_filename(name, suffix):
    stem = re.sub(r"[^A-Za-z0-9_\-]+", "_", (name or "AOI").strip()).strip("_") or "AOI"
    return f"{stem}{suffix}"
