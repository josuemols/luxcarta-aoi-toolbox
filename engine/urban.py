"""
Tool 5 — city name -> real dense built-up urban polygon.

Sources (all public, keyless):
  1. Nominatim (OSM) search  -> city candidates + official admin boundary polygon
  2. Overpass API            -> landuse=residential/commercial/industrial/retail
                                polygons = the actual built-up footprint
  3. geoBoundaries ADM2      -> admin fallback when OSM has no boundary polygon

Strategy: prefer the built-up footprint (landuse union, morphologically closed
so city blocks fuse into one shape); fall back to the admin boundary when
landuse coverage is thin; last resort a concave hull of whatever urban
polygons exist. The caller shows which method was used and lets the user switch.
"""
import requests
import shapely
from shapely.geometry import shape, Polygon, LineString, Point
from shapely.ops import unary_union, polygonize

from . import geo

USER_AGENT = "LuxCarta-AOI-Toolbox/1.0 (sales tooling; josuemo@gmail.com)"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
PHOTON = "https://photon.komoot.io/api"
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
GEOBOUNDARIES = "https://www.geoboundaries.org/api/current/gbOpen/{iso3}/ADM2/"

# built-up is capped to this half-size box around the city centre so huge
# municipal boundaries (whole provinces) don't blow up the Overpass query
MAX_HALF_DEG = 0.7  # ~75 km
THIN_KM2 = 4.0      # built-up smaller than this = "thin", prefer admin


class UrbanLookupError(Exception):
    """User-facing lookup failure — message is safe to show in the UI."""


# ---------------------------------------------------------------- candidates

def find_candidates(city, country=None, timeout=20):
    """City search -> list of candidate dicts:
    {label, lat, lon, admin_geom (shapely or None), country_code, kind,
     osm_rel_id (when the boundary polygon must be fetched separately)}.
    Nominatim first; Photon + Overpass fallback (Nominatim blocks many
    cloud-host IPs, so the fallback is what usually runs in production)."""
    try:
        return _nominatim_candidates(city, country, timeout)
    except UrbanLookupError as primary_error:
        try:
            return _photon_candidates(city, country, timeout)
        except UrbanLookupError:
            raise primary_error


def _http_detail(e):
    status = getattr(getattr(e, "response", None), "status_code", None)
    return f"HTTP {status}" if status else e.__class__.__name__


def _nominatim_candidates(city, country, timeout):
    q = f"{city}, {country}" if country else city
    try:
        r = requests.get(
            NOMINATIM,
            params={"q": q, "format": "jsonv2", "polygon_geojson": 1,
                    "limit": 6, "addressdetails": 1},
            headers={"User-Agent": USER_AGENT}, timeout=timeout)
        r.raise_for_status()
        rows = r.json()
    except requests.RequestException as e:
        raise UrbanLookupError(f"City search service is unreachable right now ({_http_detail(e)}). Try again in a minute.")
    out = []
    for row in rows:
        cat = row.get("category") or row.get("class")  # jsonv2 says "category"
        if cat not in ("boundary", "place"):
            continue
        gj = row.get("geojson") or {}
        admin = None
        if gj.get("type") in ("Polygon", "MultiPolygon"):
            try:
                admin = shape(gj)
                if not admin.is_valid:
                    admin = admin.buffer(0)
            except Exception:
                admin = None
        out.append({
            "label": row.get("display_name", city),
            "lat": float(row["lat"]), "lon": float(row["lon"]),
            "admin_geom": admin,
            "country_code": (row.get("address") or {}).get("country_code", ""),
            "kind": f'{cat}/{row.get("type")}',
        })
    if not out:
        raise UrbanLookupError(
            f'No city found for "{q}". Check the spelling, or add the country.')
    return out


def _photon_candidates(city, country, timeout):
    """Photon geocoder (keyless, no IP policy). Returns candidates whose
    boundary polygon is fetched later from Overpass via osm_rel_id."""
    q = f"{city}, {country}" if country else city
    try:
        r = requests.get(PHOTON, params={"q": q, "limit": 6},
                         headers={"User-Agent": USER_AGENT}, timeout=timeout)
        r.raise_for_status()
        features = r.json().get("features", [])
    except requests.RequestException as e:
        raise UrbanLookupError(f"City search fallback also unreachable ({_http_detail(e)}).")
    out = []
    for f in features:
        p = f.get("properties", {})
        if p.get("osm_key") not in ("place", "boundary"):
            continue
        try:
            lon, lat = f["geometry"]["coordinates"][:2]
        except (KeyError, TypeError, ValueError):
            continue
        label = ", ".join(x for x in (p.get("name"), p.get("state"), p.get("country")) if x)
        out.append({
            "label": label or city,
            "lat": float(lat), "lon": float(lon),
            "admin_geom": None,
            "osm_rel_id": p.get("osm_id") if p.get("osm_type") == "R" else None,
            "country_code": (p.get("countrycode") or "").lower(),
            "kind": f'{p.get("osm_key")}/{p.get("osm_value")}',
        })
    if not out:
        raise UrbanLookupError(
            f'No city found for "{q}". Check the spelling, or add the country.')
    return out


def relation_polygon(rel_id, timeout=120):
    """Fetch an OSM admin-boundary relation from Overpass and assemble its
    outer ways into a (Multi)Polygon. Returns None if it can't be built."""
    data = _overpass(f"[out:json][timeout:90];relation({rel_id});out geom;", timeout)
    lines = []
    for el in data.get("elements", []):
        if el.get("type") != "relation":
            continue
        for m in el.get("members", []):
            if m.get("type") == "way" and m.get("role") in ("outer", "") and "geometry" in m:
                pts = [(p["lon"], p["lat"]) for p in m["geometry"]]
                if len(pts) >= 2:
                    lines.append(LineString(pts))
    if not lines:
        return None
    polys = list(polygonize(unary_union(lines)))
    if not polys:
        return None
    geom = unary_union(polys)
    return geom.buffer(0) if not geom.is_valid else geom


# ---------------------------------------------------------------- built-up

def _overpass(query, timeout=120):
    last = None
    for url in OVERPASS_ENDPOINTS:
        try:
            r = requests.post(url, data={"data": query},
                              headers={"User-Agent": USER_AGENT}, timeout=timeout)
            if r.status_code == 429:
                last = UrbanLookupError("The map data service is rate-limiting us — wait a minute and retry.")
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last = UrbanLookupError(f"Map data service unreachable ({e.__class__.__name__}).")
    raise last or UrbanLookupError("Map data service unreachable.")


def builtup_polygons(lat, lon, admin_geom=None):
    """Fetch landuse polygons around the city centre. Returns list of shapely
    polygons (possibly empty)."""
    if admin_geom is not None:
        minx, miny, maxx, maxy = admin_geom.bounds
        minx, maxx = max(minx, lon - MAX_HALF_DEG), min(maxx, lon + MAX_HALF_DEG)
        miny, maxy = max(miny, lat - MAX_HALF_DEG), min(maxy, lat + MAX_HALF_DEG)
    else:
        d = 0.25  # ~25 km box when we only have a point
        minx, miny, maxx, maxy = lon - d, lat - d, lon + d, lat + d
    bbox = f"{miny},{minx},{maxy},{maxx}"
    q = f"""[out:json][timeout:90];
(
  way["landuse"~"^(residential|commercial|industrial|retail)$"]({bbox});
  relation["landuse"~"^(residential|commercial|industrial|retail)$"]({bbox});
);
out geom;"""
    data = _overpass(q)
    polys = []
    for el in data.get("elements", []):
        if el["type"] == "way" and "geometry" in el:
            pts = [(p["lon"], p["lat"]) for p in el["geometry"]]
            if len(pts) >= 4:
                polys.append(Polygon(pts))
        elif el["type"] == "relation":
            for m in el.get("members", []):
                if m.get("role") == "outer" and "geometry" in m:
                    pts = [(p["lon"], p["lat"]) for p in m["geometry"]]
                    if len(pts) >= 4 and pts[0] == pts[-1]:
                        polys.append(Polygon(pts))
    return [p.buffer(0) if not p.is_valid else p for p in polys if not p.is_empty]


def build_urban_area(candidate):
    """Compute every available method for one candidate.
    Returns {"methods": {name: geom}, "default": name, "notes": [str]}."""
    lat, lon = candidate["lat"], candidate["lon"]
    admin = candidate.get("admin_geom")
    notes, methods = [], {}

    if admin is None and candidate.get("osm_rel_id"):
        try:
            admin = relation_polygon(candidate["osm_rel_id"])
        except UrbanLookupError as e:
            admin = None
            notes.append(f"Official boundary couldn't be fetched: {e}")
        if admin is not None and admin.is_empty:
            admin = None

    try:
        raw = builtup_polygons(lat, lon, admin)
    except UrbanLookupError as e:
        raw = []
        notes.append(f"Built-up lookup failed: {e}")

    if raw:
        union = unary_union(raw)
        if admin is not None:
            union = union.intersection(geo.buffer_km(admin, 1.0))
        if not union.is_empty:
            closed = geo.morph_close_km(union, 0.6)
            closed = geo.largest_parts(closed, keep_ratio=0.08)
            centre = Point(lon, lat)
            if closed.geom_type == "MultiPolygon":
                keep = [g for g in closed.geoms
                        if g.distance(centre) < 0.05 or
                        geo.garea_km2(g) > 0.25 * geo.garea_km2(closed)]
                if keep:
                    closed = unary_union(keep)
            closed = geo.simplify_m(closed.buffer(0), 40)
            if geo.garea_km2(closed) >= THIN_KM2:
                methods["Built-up footprint (OSM landuse)"] = closed
            else:
                notes.append("OSM landuse coverage is thin here — built-up footprint unreliable.")
            try:
                hull = shapely.concave_hull(union, ratio=0.35)
            except Exception:
                hull = union.convex_hull
            if hull.geom_type in ("Polygon", "MultiPolygon") and not hull.is_empty:
                methods["Urban hull (outline around urban blocks)"] = geo.simplify_m(hull.buffer(0), 40)

    if admin is not None:
        methods["Administrative boundary (official limits)"] = admin
    elif not raw:
        gb = _geoboundaries_fallback(candidate)
        if gb is not None:
            methods["Administrative boundary (geoBoundaries ADM2)"] = gb
            notes.append("Boundary from geoBoundaries (OSM had none).")

    if not methods:
        raise UrbanLookupError(
            "Couldn't build a polygon for this city from any source. "
            "Try adding the country, or use Tool 3 (buffer) around a point KML instead.")

    for name in ("Built-up footprint (OSM landuse)",
                 "Administrative boundary (official limits)",
                 "Administrative boundary (geoBoundaries ADM2)",
                 "Urban hull (outline around urban blocks)"):
        if name in methods:
            return {"methods": methods, "default": name, "notes": notes}
    return {"methods": methods, "default": next(iter(methods)), "notes": notes}


# ---------------------------------------------------------------- fallback

def _geoboundaries_fallback(candidate, timeout=60):
    """Find the ADM2 polygon containing the city point via geoBoundaries."""
    iso2 = (candidate.get("country_code") or "").upper()
    if not iso2:
        return None
    try:
        import pycountry
        iso3 = pycountry.countries.get(alpha_2=iso2).alpha_3
    except Exception:
        return None
    try:
        r = requests.get(GEOBOUNDARIES.format(iso3=iso3),
                         headers={"User-Agent": USER_AGENT}, timeout=timeout)
        r.raise_for_status()
        meta = r.json()
        gj_url = meta.get("simplifiedGeometryGeoJSON") or meta.get("gjDownloadURL")
        if not gj_url:
            return None
        gj = requests.get(gj_url, headers={"User-Agent": USER_AGENT}, timeout=timeout).json()
        pt = Point(candidate["lon"], candidate["lat"])
        for feat in gj.get("features", []):
            g = shape(feat["geometry"])
            if g.contains(pt):
                return g.buffer(0) if not g.is_valid else g
    except Exception:
        return None
    return None
