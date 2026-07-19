"""
LuxCarta AOI Toolbox — Streamlit app for the sales team.

Five utilities that prepare Area-of-Interest KML/KMZ files for the quote tool:
  1. Convert Shapefile / MapInfo -> KML/KMZ
  2. Fix the city name inside a KMZ (so it shows in the quote table)
  3. Buffer an AOI by X km
  4. Corridor around a line (railway etc.) -> closed polygon
  5. City name -> real urban-area KMZ

Companion app to luxcarta-quote-app — same branding, same gate() pattern.
"""
import os
import sys

import streamlit as st
import folium
from streamlit_folium import st_folium
from shapely.geometry import mapping
from shapely.ops import unary_union

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

from engine import geo, vector_io, urban, cloud, branding
from engine.vector_io import VectorReadError
from engine.urban import UrbanLookupError

st.set_page_config(page_title="LuxCarta AOI Toolbox", page_icon=branding.page_icon(),
                   layout="wide")
branding.brand_header()

if not branding.gate():
    st.stop()

# ---------------------------------------------------------------- shared UI

COMMON_CRS = {
    "WGS84 — plain latitude/longitude (most common)": 4326,
    "Web Mercator (web maps)": 3857,
    "UTM zone 31N (France W, Spain E)": 32631,
    "UTM zone 32N (France E, Germany, Italy N)": 32632,
    "Lambert 93 (France official)": 2154,
    "British National Grid": 27700,
}


def preview_map(geoms, names=None, color="#FF8300"):
    """Folium preview of WGS84 geometries, zoomed to fit."""
    geoms = [g for g in geoms if g is not None and not g.is_empty]
    if not geoms:
        st.info("Nothing to show yet.")
        return
    union = unary_union(geoms)
    minx, miny, maxx, maxy = union.bounds
    m = folium.Map(tiles="OpenStreetMap")
    for i, g in enumerate(geoms):
        label = (names[i] if names and i < len(names) else None) or f"AOI {i + 1}"
        folium.GeoJson(
            mapping(g), tooltip=label,
            style_function=lambda _f, c=color: {
                "color": c, "weight": 2, "fillColor": c, "fillOpacity": 0.25},
        ).add_to(m)
    m.fit_bounds([[miny, minx], [maxy, maxx]], padding=(20, 20))
    st_folium(m, height=420, use_container_width=True, returned_objects=[])


def area_readout(geoms, label="Total area"):
    km2 = sum(geo.garea_km2(g) for g in geoms if g is not None)
    st.metric(label, f"{km2:,.1f} km²")
    return km2


def offer_downloads(kml_bytes, base_name, key):
    """Local KML + KMZ download buttons, plus optional cloud share link."""
    kmz = vector_io.kml_to_kmz_bytes(kml_bytes)
    c1, c2, c3 = st.columns([1, 1, 2])
    c1.download_button("Download KMZ", kmz, vector_io.safe_filename(base_name, ".kmz"),
                       "application/vnd.google-earth.kmz", key=f"{key}_kmz", type="primary")
    c2.download_button("Download KML", kml_bytes, vector_io.safe_filename(base_name, ".kml"),
                       "application/vnd.google-earth.kml+xml", key=f"{key}_kml")
    if cloud.config():
        if c3.button("Save to cloud & get link", key=f"{key}_cloud"):
            try:
                url = cloud.upload(kmz, vector_io.safe_filename(base_name, ".kmz"))
                st.success("Saved — anyone with this link can download the KMZ:")
                st.code(url)
            except RuntimeError as e:
                st.error(str(e))
    return kmz


def crs_picker(warnings, key):
    """When the upload has no CRS, ask the user; returns EPSG or None (=ready)."""
    if "no_crs" not in warnings and "no_prj" not in warnings:
        return None
    st.warning("This file doesn't say which coordinate system it uses. "
               "Pick the one it was made in (when unsure, keep WGS84).")
    label = st.selectbox("Coordinate system of the uploaded file",
                         list(COMMON_CRS.keys()), key=f"{key}_crs")
    epsg = COMMON_CRS[label]
    custom = st.text_input("…or type an EPSG code (e.g. 32633)", key=f"{key}_epsg")
    if custom.strip().isdigit():
        epsg = int(custom.strip())
    return epsg


@st.cache_data(show_spinner=False, ttl=3600)
def _cached_candidates(city, country):
    return urban.find_candidates(city, country)


@st.cache_data(show_spinner=False, ttl=3600)
def _cached_urban(city, country, idx):
    cands = urban.find_candidates(city, country)
    return urban.build_urban_area(cands[idx])


@st.cache_data(show_spinner=False, ttl=3600)
def _reverse_city(lat, lon):
    import requests
    try:
        r = requests.get("https://nominatim.openstreetmap.org/reverse",
                         params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 10},
                         headers={"User-Agent": urban.USER_AGENT}, timeout=15)
        r.raise_for_status()
        a = r.json().get("address", {})
        name = a.get("city") or a.get("town") or a.get("village") or a.get("municipality")
        if name:
            return name
    except Exception:
        pass
    try:  # Photon fallback — Nominatim blocks many cloud-host IPs
        r = requests.get("https://photon.komoot.io/reverse",
                         params={"lat": lat, "lon": lon},
                         headers={"User-Agent": urban.USER_AGENT}, timeout=15)
        r.raise_for_status()
        feats = r.json().get("features", [])
        p = feats[0]["properties"] if feats else {}
        return p.get("city") or p.get("name")
    except Exception:
        return None


def read_uploaded(files):
    """st.file_uploader result -> (gdf, warnings) via engine.vector_io."""
    return vector_io.read_uploads([(f.name, f.getvalue()) for f in files])


# ---------------------------------------------------------------- sidebar

TOOLS = {
    "Convert to KML/KMZ": "Turn a Shapefile or MapInfo file into a KML/KMZ.",
    "Fix city name in KMZ": "Make sure the real city name shows up in the quote table.",
    "Buffer an AOI": "Grow an AOI outward by X km.",
    "Corridor around a line": "Railway or road line -> closed corridor polygon.",
    "City name → urban area": "Type a city, get its real built-up area as KMZ.",
}
st.sidebar.markdown("### Tools")
tool = st.sidebar.radio("Pick a tool", list(TOOLS.keys()),
                        captions=list(TOOLS.values()), label_visibility="collapsed")
st.sidebar.markdown(
    '<div style="color:#72808A;font-size:.8rem;margin-top:24px;">'
    'Outputs feed the <b>LuxCarta Quote Generator</b> — areas (km²) match it exactly.</div>',
    unsafe_allow_html=True)


# ================================================================ Tool 1

def tool_convert():
    st.subheader("Convert to KML/KMZ")
    st.caption("Drop a Shapefile (.zip, or .shp + .dbf/.shx/.prj) or a MapInfo file "
               "(.tab with .dat/.map/.id, or .mif/.mid). You get a KML/KMZ in the right place on Earth.")
    files = st.file_uploader(
        "Files to convert",
        type=["zip", "shp", "dbf", "shx", "prj", "cpg", "tab", "dat", "map", "id", "ind", "mif", "mid", "geojson", "json", "gpkg"],
        accept_multiple_files=True, key="t1_files")
    if not files:
        return
    try:
        gdf, warnings = read_uploaded(files)
    except VectorReadError as e:
        st.error(str(e))
        return
    epsg = crs_picker(warnings, "t1")
    if gdf.crs is None:
        if not epsg:
            return
        try:
            gdf = vector_io.assume_crs(gdf, epsg)
        except Exception:
            st.error(f"EPSG:{epsg} is not a valid coordinate system code.")
            return
    st.success(f"Read {len(gdf)} feature(s).")

    name_col = vector_io.guess_name_field(gdf)
    cols = [c for c in gdf.columns if c != gdf.geometry.name]
    if cols:
        name_col = st.selectbox("Which column holds the AOI / city name?", cols,
                                index=cols.index(name_col) if name_col in cols else 0, key="t1_name")
        names = [str(v) if str(v).strip() not in ("", "None", "nan") else f"AOI {i + 1}"
                 for i, v in enumerate(gdf[name_col])]
    else:
        names = [f"AOI {i + 1}" for i in range(len(gdf))]

    geoms = list(gdf.geometry)
    preview_map(geoms, names)
    area_readout(geoms)
    feats = []
    for i, row in enumerate(gdf.itertuples(index=False)):
        attrs = {c: getattr(row, c, "") for c in cols}
        feats.append({"name": names[i], "geom": geoms[i], "attrs": attrs})
    base = os.path.splitext(files[0].name)[0]
    offer_downloads(vector_io.write_kml_bytes(feats, doc_name=base), base, "t1")


# ================================================================ Tool 2

def tool_fixname():
    st.subheader("Fix city name in KMZ")
    st.caption("When a KMZ shows up as “aoi” or “Polygon 1” in the quote table, fix it here: "
               "type the real city name and download the corrected KMZ.")
    up = st.file_uploader("KMZ or KML file", type=["kmz", "kml"], key="t2_file")
    if not up:
        return
    try:
        feats = vector_io.parse_kml_features(
            up.getvalue(), is_kmz=up.name.lower().endswith(".kmz"))
    except VectorReadError as e:
        st.error(str(e))
        return
    if not feats:
        st.error("No shapes found in this file.")
        return
    st.success(f"Found {len(feats)} shape(s).")

    new_names = []
    if len(feats) > 1:
        same = st.checkbox("Use one name for all shapes", key="t2_same")
        if same:
            one = st.text_input("City name", value=feats[0]["name"], key="t2_all")
            new_names = [one] * len(feats)
    if not new_names:
        # widget-state writes must happen in on_click callbacks (before the
        # script body runs) — writing after the widget exists raises
        def _apply_suggestion(state_key, lat, lon):
            suggestion = _reverse_city(lat, lon)
            if suggestion:
                st.session_state[state_key] = suggestion
            else:
                st.session_state["t2_nosuggest"] = True

        for i, f in enumerate(feats):
            c1, c2 = st.columns([3, 1])
            val = c1.text_input(f"Name for shape {i + 1} (currently “{f['name']}”)",
                                value=f["name"], key=f"t2_n{i}")
            cen = f["geom"].centroid
            c2.button("Suggest", key=f"t2_s{i}", help="Look up the city at this location",
                      on_click=_apply_suggestion,
                      args=(f"t2_n{i}", round(cen.y, 5), round(cen.x, 5)))
            new_names.append(val)
        if st.session_state.pop("t2_nosuggest", False):
            st.toast("No suggestion found for this location.")

    geoms = [f["geom"] for f in feats]
    preview_map(geoms, new_names)
    area_readout(geoms)

    out_feats = [{"name": n or f["name"], "geom": f["geom"], "attrs": f["attrs"]}
                 for n, f in zip(new_names, feats)]
    base = (new_names[0] or "AOI") if new_names else "AOI"
    kml = vector_io.write_kml_bytes(out_feats, doc_name=base)
    kmz = offer_downloads(kml, f"{base}_AOI", "t2")
    seen = vector_io.quote_tool_name_check(kmz)
    if seen and all(s and s.lower() not in ("aoi", "polygon", "untitled") for s in seen):
        st.caption("✅ Checked: the quote tool will read " + ", ".join(f"“{s}”" for s in seen))
    else:
        st.warning("The quote tool may still show a generic name — set a name above.")


# ================================================================ Tool 3

def tool_buffer():
    st.subheader("Buffer an AOI")
    st.caption("Grow an AOI outward by a distance in km — works on areas, lines and points. "
               "The distance is measured in real kilometres on the ground.")
    up = st.file_uploader("KMZ or KML file", type=["kmz", "kml"], key="t3_file")
    km = st.number_input("Distance in km", min_value=0.1, max_value=500.0, value=5.0,
                         step=0.5, key="t3_km")
    if not up:
        return
    try:
        feats = vector_io.parse_kml_features(
            up.getvalue(), is_kmz=up.name.lower().endswith(".kmz"))
    except VectorReadError as e:
        st.error(str(e))
        return
    if not feats:
        st.error("No shapes found in this file.")
        return
    merge = len(feats) > 1 and st.checkbox(
        "Merge everything into one shape first", value=True, key="t3_merge")
    if merge:
        feats = [{"name": feats[0]["name"], "attrs": feats[0]["attrs"],
                  "geom": unary_union([f["geom"] for f in feats])}]
    out = [{"name": f["name"], "attrs": f["attrs"],
            "geom": geo.buffer_km(f["geom"], km)} for f in feats]
    geoms = [f["geom"] for f in out]
    names = [f["name"] for f in out]
    preview_map(geoms, names)
    area_readout(geoms, "Area after buffer")
    base = f"{names[0]}_buffer_{km:g}km"
    offer_downloads(vector_io.write_kml_bytes(out, doc_name=base), base, "t3")


# ================================================================ Tool 4

def tool_corridor():
    st.subheader("Corridor around a line")
    st.caption("Drop a line (railway, road, pipeline…) and get a closed corridor polygon "
               "X km each side — the km² shown is what the quote will be based on.")
    files = st.file_uploader(
        "Line file (KMZ/KML/GeoJSON, or a line Shapefile as .zip)",
        type=["kmz", "kml", "geojson", "json", "zip", "shp", "dbf", "shx", "prj"],
        accept_multiple_files=True, key="t4_files")
    km = st.number_input("Width each side, in km", min_value=0.1, max_value=100.0,
                         value=2.0, step=0.5, key="t4_km")
    if not files:
        return
    line_name = None
    try:
        first = files[0].name.lower()
        if first.endswith((".kmz", ".kml")) and len(files) == 1:
            feats = vector_io.parse_kml_features(
                files[0].getvalue(), is_kmz=first.endswith(".kmz"))
            lines = [f["geom"] for f in feats
                     if "Line" in f["geom"].geom_type or "Collection" in f["geom"].geom_type]
            named = [f["name"] for f in feats if "Line" in f["geom"].geom_type]
            line_name = named[0] if named else (feats[0]["name"] if feats else None)
        else:
            gdf, warnings = read_uploaded(files)
            epsg = crs_picker(warnings, "t4")
            if gdf.crs is None:
                if not epsg:
                    return
                gdf = vector_io.assume_crs(gdf, epsg)
            lines = [g for g in gdf.geometry if g and "Line" in g.geom_type]
            col = vector_io.guess_name_field(gdf)
            if col is not None and len(gdf):
                line_name = str(gdf[col].iloc[0])
    except VectorReadError as e:
        st.error(str(e))
        return
    if not lines:
        st.error("No line found in this file — this tool needs a line, not an area or a point. "
                 "For areas use “Buffer an AOI”.")
        return
    line_name = line_name if line_name and line_name.strip() else os.path.splitext(files[0].name)[0]
    corridor = geo.corridor_polygon(lines, km)
    name = f"Railway corridor — {line_name}" if "rail" in line_name.lower() else f"Corridor — {line_name}"
    preview_map([unary_union(lines), corridor], [line_name, name])
    area_readout([corridor], "Corridor area")
    st.caption(f"One closed polygon, {km:g} km each side of the line ({2 * km:g} km total width).")
    feats = [{"name": name, "geom": corridor, "attrs": {"source_line": line_name}}]
    offer_downloads(vector_io.write_kml_bytes(feats, doc_name=name), name, "t4")


# ================================================================ Tool 5

def tool_city():
    st.subheader("City name → urban area")
    st.caption("Type a city and get a KMZ of its real dense built-up area — "
               "not a circle, not the whole province.")
    c1, c2 = st.columns([2, 1])
    city = c1.text_input("City name", placeholder="e.g. Douala", key="t5_city")
    country = c2.text_input("Country (optional)", placeholder="e.g. Cameroon", key="t5_country")
    if not city.strip():
        return
    try:
        with st.spinner("Looking up the city…"):
            cands = _cached_candidates(city.strip(), country.strip() or None)
    except UrbanLookupError as e:
        st.error(str(e))
        if st.button("Retry", key="t5_retry1"):
            _cached_candidates.clear()
            st.rerun()
        return
    idx = 0
    if len(cands) > 1:
        idx = st.radio("Which one did you mean?", range(len(cands)),
                       format_func=lambda i: cands[i]["label"], key="t5_cand")
    try:
        with st.spinner("Building the urban area (can take ~30 s the first time)…"):
            result = _cached_urban(city.strip(), country.strip() or None, idx)
    except UrbanLookupError as e:
        st.error(str(e))
        if st.button("Retry", key="t5_retry2"):
            _cached_urban.clear()
            st.rerun()
        return
    for note in result["notes"]:
        st.info(note)
    methods = result["methods"]
    keys = list(methods.keys())
    chosen = st.radio("Method (you can switch)", keys,
                      index=keys.index(result["default"]), key="t5_method")
    geom = methods[chosen]

    simp = st.slider("Simplify the shape (higher = fewer points, lighter file)",
                     0, 500, 0, 25, format="%d m", key="t5_simp")
    if simp:
        geom = geo.simplify_m(geom, simp)
    geom = geom.buffer(0)

    city_name = city.strip().title()
    preview_map([geom], [city_name])
    a, b = st.columns(2)
    with a:
        area_readout([geom], "Urban area")
    b.metric("Shape points", f"{geo.n_vertices(geom):,}")
    if geo.n_vertices(geom) > 5000:
        st.warning("Heavy shape — consider raising the simplify slider so the quote tool stays fast.")

    dissolved = unary_union([geom])
    feats = [{"name": city_name, "geom": dissolved,
              "attrs": {"method": chosen, "source": "OSM / geoBoundaries"}}]
    offer_downloads(vector_io.write_kml_bytes(feats, doc_name=city_name),
                    f"{city_name}_urban_AOI", "t5")


# ---------------------------------------------------------------- dispatch

try:
    {"Convert to KML/KMZ": tool_convert,
     "Fix city name in KMZ": tool_fixname,
     "Buffer an AOI": tool_buffer,
     "Corridor around a line": tool_corridor,
     "City name → urban area": tool_city}[tool]()
except (VectorReadError, UrbanLookupError) as e:
    st.error(str(e))
except Exception:
    st.error("Something went wrong with this file or request. "
             "Try again, or send the file to Josué so the tool can be fixed.")
    import traceback
    with st.expander("Technical details (for support)"):
        st.code(traceback.format_exc())
