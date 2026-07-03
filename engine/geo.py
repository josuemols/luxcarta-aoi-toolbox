"""
Geodesic measurement and metric-accurate geometry operations.

garea_km2() is copied from luxcarta-quote-app engine/overlap.py so the km²
shown here matches the quote tool exactly.
"""
from pyproj import Geod, CRS, Transformer
from shapely.geometry import base as shp_base
from shapely.ops import transform as shp_transform, unary_union

GEOD = Geod(ellps="WGS84")


def garea_km2(g):
    """Geodesic area in km² of a shapely geometry in EPSG:4326 (lon/lat).
    Identical to the quote engine's overlap.garea_km2."""
    if g is None or g.is_empty:
        return 0.0
    return abs(GEOD.geometry_area_perimeter(g)[0]) / 1e6


def utm_crs_for(geom_wgs84):
    """UTM CRS for the geometry's centroid — local metric CRS for buffering."""
    c = geom_wgs84.centroid
    zone = min(60, max(1, int((c.x + 180) // 6) + 1))
    return CRS.from_epsg((32600 if c.y >= 0 else 32700) + zone)


def _to_metric_and_back(geom_wgs84):
    crs = utm_crs_for(geom_wgs84)
    fwd = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
    back = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
    return fwd, back


def buffer_km(geom_wgs84, km):
    """Geodesically honest buffer: project to local UTM, buffer in metres,
    reproject back to WGS84. Valid for AOI-scale geometries."""
    fwd, back = _to_metric_and_back(geom_wgs84)
    buffered = shp_transform(fwd, geom_wgs84).buffer(km * 1000.0)
    return shp_transform(back, buffered)


def corridor_polygon(line_geoms_wgs84, half_width_km):
    """Buffer line(s) by half_width_km each side and dissolve to one polygon."""
    merged = unary_union([g for g in line_geoms_wgs84 if g and not g.is_empty])
    fwd, back = _to_metric_and_back(merged)
    corridor = shp_transform(fwd, merged).buffer(half_width_km * 1000.0)
    corridor = corridor.buffer(0)  # heal any self-touches
    return shp_transform(back, corridor)


def morph_close_km(geom_wgs84, km):
    """Morphological closing (dilate then erode by km) in a metric CRS —
    fuses nearby urban patches into a coherent footprint."""
    fwd, back = _to_metric_and_back(geom_wgs84)
    m = shp_transform(fwd, geom_wgs84)
    closed = m.buffer(km * 1000.0).buffer(-km * 1000.0)
    return shp_transform(back, closed)


def simplify_m(geom_wgs84, tolerance_m):
    """Topology-preserving simplify with a tolerance given in metres."""
    if not tolerance_m:
        return geom_wgs84
    fwd, back = _to_metric_and_back(geom_wgs84)
    simplified = shp_transform(fwd, geom_wgs84).simplify(tolerance_m, preserve_topology=True)
    return shp_transform(back, simplified)


def n_vertices(geom):
    """Total vertex count of any shapely geometry."""
    if geom is None or geom.is_empty:
        return 0
    if geom.geom_type == "Point":
        return 1
    if geom.geom_type in ("LineString", "LinearRing"):
        return len(geom.coords)
    if geom.geom_type == "Polygon":
        return len(geom.exterior.coords) + sum(len(r.coords) for r in geom.interiors)
    if hasattr(geom, "geoms"):
        return sum(n_vertices(g) for g in geom.geoms)
    return 0


def largest_parts(geom, keep_ratio=0.05):
    """Drop slivers: keep polygon parts whose area is at least keep_ratio of
    the largest part. Returns a (Multi)Polygon."""
    if geom.geom_type != "MultiPolygon":
        return geom
    parts = sorted(geom.geoms, key=lambda p: p.area, reverse=True)
    if not parts:
        return geom
    biggest = parts[0].area
    kept = [p for p in parts if p.area >= keep_ratio * biggest]
    return unary_union(kept)
