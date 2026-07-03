"""
Headless verification of every tool's engine logic (the brief's checklist).
Run:  python tools/verify.py            (offline checks)
      python tools/verify.py --network  (adds Tool 5 real-city checks)

If the luxcarta-quote-app repo is present next to this repo, Tool 2's output
is ALSO parsed with the real quote engine (make_aoi.measure_kmz) — the
authoritative "the name lands in the quote table" check.
"""
import io
import math
import os
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from shapely.geometry import Point, LineString, Polygon
from pyproj import Geod

from engine import geo, vector_io

GEOD = Geod(ellps="WGS84")
FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}  {detail}")
    if not ok:
        FAILURES.append(label)


print("== Tool 1: projected shapefile lands in the right place ==")
sample = os.path.join(ROOT, "samples", "nice_utm32n.zip")
gdf, warnings = vector_io.read_uploads([("nice_utm32n.zip", open(sample, "rb").read())])
check("no warnings", not warnings, warnings)
c = gdf.geometry.iloc[0].centroid
check("centroid ~ Nice (7.25E, 43.70N)", abs(c.x - 7.25) < 0.05 and abs(c.y - 43.695) < 0.05,
      f"got ({c.x:.4f}, {c.y:.4f})")
check("name column guessed", vector_io.guess_name_field(gdf) == "CITY_NAME")
kml = vector_io.write_kml_bytes([{"name": "Nice", "geom": gdf.geometry.iloc[0], "attrs": {}}])
ET.fromstring(kml)  # well-formed or raises
feats = vector_io.parse_kml_features(kml)
check("KML round-trips", len(feats) == 1 and feats[0]["geom"].is_valid
      and abs(geo.garea_km2(feats[0]["geom"]) - geo.garea_km2(gdf.geometry.iloc[0])) < 0.5)

print("== Tool 3: buffer km² vs independent formula ==")
pt = Point(7.25, 43.70)
buf = geo.buffer_km(pt, 5.0)
got, expect = geo.garea_km2(buf), math.pi * 25.0
check("5 km buffer of a point ≈ π·r²", abs(got - expect) / expect < 0.03,
      f"{got:.2f} vs {expect:.2f} km²")
sq = Polygon([(7.2, 43.66), (7.3, 43.66), (7.3, 43.73), (7.2, 43.73)])
grown = geo.buffer_km(sq, 2.0)
per = abs(GEOD.geometry_area_perimeter(sq)[1]) / 1000.0
expect = geo.garea_km2(sq) + per * 2.0 + math.pi * 4.0
got = geo.garea_km2(grown)
check("2 km buffer of a square ≈ A + P·d + π·d²", abs(got - expect) / expect < 0.03,
      f"{got:.2f} vs {expect:.2f} km²")

print("== Tool 4: corridor km² vs independent formula ==")
rail = LineString([(7.262, 43.705), (7.212, 43.688), (7.155, 43.660),
                   (7.125, 43.615), (7.075, 43.580), (7.017, 43.552)])
corridor = geo.corridor_polygon([rail], 2.0)
check("corridor is one closed polygon", corridor.geom_type == "Polygon" and corridor.is_valid)
length_km = GEOD.geometry_length(rail) / 1000.0
expect = length_km * 4.0 + math.pi * 4.0   # 2 km each side + round caps
got = geo.garea_km2(corridor)
check("corridor area ≈ L·2w + π·w²", abs(got - expect) / expect < 0.05,
      f"{got:.2f} vs {expect:.2f} km² (line {length_km:.1f} km)")

print("== Tool 2: renamed KMZ read by the QUOTE ENGINE itself ==")
bad = os.path.join(ROOT, "samples", "bad_name.kmz")
feats = vector_io.parse_kml_features(open(bad, "rb").read(), is_kmz=True)
check("sample has the bad generic name", feats[0]["name"] == "Polygon 1")
fixed_kml = vector_io.write_kml_bytes(
    [{"name": "Nice", "geom": feats[0]["geom"], "attrs": feats[0]["attrs"]}], doc_name="Nice")
fixed_kmz = vector_io.kml_to_kmz_bytes(fixed_kml)
check("our regex check sees the city", vector_io.quote_tool_name_check(fixed_kmz) == ["Nice"])
quote_engine = os.path.join(os.path.dirname(ROOT), "luxcarta-quote-app", "engine")
if os.path.isdir(quote_engine):
    sys.path.insert(0, quote_engine)
    import make_aoi
    with tempfile.NamedTemporaryFile(suffix=".kmz", delete=False) as tf:
        tf.write(fixed_kmz)
    sites = make_aoi.measure_kmz(tf.name)
    os.unlink(tf.name)
    check("REAL quote engine reads the city name", [s["name"] for s in sites] == ["Nice"],
          str(sites))
    ours = geo.garea_km2(feats[0]["geom"])
    check("REAL quote engine area matches ours", abs(sites[0]["area_km2"] - ours) / ours < 0.02,
          f'{sites[0]["area_km2"]} vs {ours:.2f} km²')
else:
    print("  SKIP  luxcarta-quote-app repo not found next to this repo")

print("== Output KML/KMZ well-formedness ==")
for name in ("bad_name.kmz", "railway_line.kml"):
    p = os.path.join(ROOT, "samples", name)
    data = open(p, "rb").read()
    kml = vector_io.kml_bytes_from_kmz(data) if name.endswith(".kmz") else data
    ET.fromstring(kml)
    check(f"{name} well-formed", True)

if "--network" in sys.argv:
    print("== Tool 5: real cities (network) ==")
    from engine import urban
    for city, country in (("Toulouse", "France"), ("Douala", "Cameroon")):
        try:
            cands = urban.find_candidates(city, country)
            res = urban.build_urban_area(cands[0])
            m = res["default"]
            g = res["methods"][m]
            km2 = geo.garea_km2(g)
            nv = geo.n_vertices(g)
            plausible = 20 < km2 < 2500 and nv > 30
            check(f"{city}: plausible urban polygon", plausible,
                  f"{km2:.0f} km², {nv} pts, method: {m}; notes: {res['notes']}")
        except Exception as e:
            check(f"{city}: lookup", False, repr(e))

print()
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
print("ALL CHECKS PASSED")
