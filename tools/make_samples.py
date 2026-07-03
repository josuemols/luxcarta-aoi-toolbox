"""
Generate the sample test files in samples/ :
  - nice_utm32n.zip   projected (EPSG:32632) shapefile of a Nice-area polygon
  - bad_name.kmz      a KMZ whose polygon is named "Polygon 1" (Tool 2 input)
  - railway_line.kml  a coastal railway-like line near Nice (Tool 4 input)

Run:  python tools/make_samples.py
"""
import os
import sys
import zipfile

import geopandas as gpd
from shapely.geometry import Polygon, LineString

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import vector_io  # noqa: E402

SAMPLES = os.path.join(ROOT, "samples")
os.makedirs(SAMPLES, exist_ok=True)

# Nice, France — rough city-centre rectangle in WGS84
nice_wgs = Polygon([(7.20, 43.66), (7.30, 43.66), (7.30, 43.73), (7.20, 43.73)])

# 1 — projected shapefile (UTM 32N), zipped
gdf = gpd.GeoDataFrame({"CITY_NAME": ["Nice"]}, geometry=[nice_wgs], crs="EPSG:4326").to_crs(32632)
shp_dir = os.path.join(SAMPLES, "_shp_tmp")
os.makedirs(shp_dir, exist_ok=True)
gdf.to_file(os.path.join(shp_dir, "nice_utm32n.shp"))
with zipfile.ZipFile(os.path.join(SAMPLES, "nice_utm32n.zip"), "w", zipfile.ZIP_DEFLATED) as z:
    for f in os.listdir(shp_dir):
        z.write(os.path.join(shp_dir, f), f)
for f in os.listdir(shp_dir):
    os.remove(os.path.join(shp_dir, f))
os.rmdir(shp_dir)

# 2 — KMZ with a useless generic name
kml = vector_io.write_kml_bytes([{"name": "Polygon 1", "geom": nice_wgs, "attrs": {}}],
                                doc_name="export")
open(os.path.join(SAMPLES, "bad_name.kmz"), "wb").write(vector_io.kml_to_kmz_bytes(kml))

# 3 — railway-like line along the coast Nice -> Antibes -> Cannes
rail = LineString([(7.262, 43.705), (7.212, 43.688), (7.155, 43.660),
                   (7.125, 43.615), (7.075, 43.580), (7.017, 43.552)])
kml = vector_io.write_kml_bytes([{"name": "Nice–Cannes railway", "geom": rail, "attrs": {}}],
                                doc_name="Nice–Cannes railway")
open(os.path.join(SAMPLES, "railway_line.kml"), "wb").write(kml)

print("samples written to", SAMPLES)
