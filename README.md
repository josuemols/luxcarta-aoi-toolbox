# LuxCarta AOI Toolbox

Companion Streamlit app to **luxcarta-quote-app**: five utilities the sales
team uses to prepare Area-of-Interest KML/KMZ files that feed the quote tool.
Same branding, same password `gate()` pattern, same repo conventions.

## The five tools

| Tool | What it does |
|---|---|
| **Convert to KML/KMZ** | Shapefile (.zip or .shp+sidecars) / MapInfo TAB/MIF/GeoJSON → KML/KMZ, reprojected to WGS84 |
| **Fix city name in KMZ** | Renames placemarks so the real city name shows in the quote table (with reverse-geocode suggestions) |
| **Buffer an AOI** | Grows any KML/KMZ outward by X real kilometres |
| **Corridor around a line** | Railway/road line → one closed corridor polygon, X km each side |
| **City name → urban area** | Type a city name → KMZ of the actual dense built-up footprint |

Every tool shows a map preview and a **geodesic km² readout that matches the
quote engine exactly**, offers KML + KMZ download, and (when Supabase is
configured) a "Save to cloud & get link" button.

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run streamlit_app.py
```

## Deploy (Streamlit Community Cloud)

1. New app → this repo → `streamlit_app.py`.
2. In the app's **Secrets** panel paste the entries you want from
   [.streamlit/secrets.toml.example](.streamlit/secrets.toml.example)
   (`app_password`, optional `supabase_url`/`supabase_key`/`supabase_bucket`).
   All secrets are optional — with none, the app runs open with local
   downloads only.
3. No `packages.txt` is needed: geopandas/pyogrio wheels bundle GDAL
   (including the MapInfo driver).

For cloud share links: create a **public** bucket named `aoi-toolbox` in
Supabase Storage and use a key with storage write access. AOI files are not
proprietary, so a public bucket is acceptable.

## What was reused from luxcarta-quote-app

- `engine/geo.garea_km2()` — copied verbatim from the quote app's
  `overlap.py` (`pyproj.Geod(ellps="WGS84").geometry_area_perimeter`), so km²
  here equals km² in the quote table.
- `engine/branding.py` — the `_brand()` header CSS (logo, Jost font, palette)
  and the `gate()` password pattern, copied from `streamlit_app.py`.
- `assets/brand/` logos and `.streamlit/config.toml` theme — copied as-is.
- `vector_io.quote_tool_name_check()` mirrors the exact regexes of the quote
  engine's `make_aoi.measure_kmz()`.

**Important compatibility detail:** the quote engine matches a *bare*
`<Polygon>` tag. simplekml normally writes `<Polygon id="…">`, which the quote
tool skips — falling back to the generic name "AOI". That is very likely why
KMZs showed generic names in the quote table. This app strips geometry `id`
attributes from every KML it writes, and every export sets the placemark
`<name>` (the field the quote engine reads) **and** an `ExtendedData`
`city`/`name` pair as backup.

## CRS / reprojection approach

- Inputs are read with GeoPandas; the source CRS comes from `.prj`/metadata
  and everything is reprojected to **WGS84 (EPSG:4326)** before writing KML.
  If the file declares no CRS, the app warns and asks the user (default WGS84).
- Buffers and corridors are computed in the **UTM zone of the geometry's
  centroid** (metres), then reprojected back — a degree buffer would be wrong
  away from the equator. Verified within 3% of the analytic formulas
  (see `tools/verify.py`).
- Areas are always **geodesic** (`pyproj.Geod`), never planar.

## Tool 5 data sources

1. **Nominatim** (OSM, keyless) — city-name candidates + official admin
   boundary polygon, with a picker when names collide.
2. **Overpass API** (two mirrored endpoints) — `landuse=residential/
   commercial/industrial/retail` polygons = the built-up footprint. The union
   is morphologically closed (0.6 km) so city blocks fuse into one shape,
   slivers are dropped, and the result is clipped to the admin boundary +1 km.
   The query bbox is capped to ~75 km around the centre so huge municipal
   boundaries don't blow up the request.
3. **geoBoundaries ADM2** — admin fallback when OSM has no boundary polygon.

The method used (built-up / admin boundary / urban hull) is always shown and
switchable, with a vertex-count readout and a simplify slider before export.

## Sample files & verification

`tools/make_samples.py` generates `samples/`:
- `nice_utm32n.zip` — **projected** (EPSG:32632) shapefile → Tool 1 must land
  it on Nice, not shift it by hundreds of km.
- `bad_name.kmz` — polygon named "Polygon 1" → Tool 2 input.
- `railway_line.kml` — 27 km coastal line → Tool 4 input.

`tools/verify.py` runs the release checklist headlessly:
- Tool 1: projected shapefile centroid lands at Nice; KML round-trips.
- Tool 3: 5 km point buffer within 3% of π·r²; square buffer within 3% of
  A + P·d + π·d².
- Tool 4: corridor area within 5% of L·2w + π·w².
- Tool 2: the corrected KMZ is parsed with the **real quote engine**
  (`make_aoi.measure_kmz`, when the quote-app repo sits next to this one) —
  name reads back correctly and its area matches ours.
- `--network` adds Tool 5 smoke tests (Toulouse 158 km², Douala 91 km² —
  plausible built-up polygons, not circles or provinces).

## Known limitations

- Tool 5 depends on free public APIs (Nominatim/Overpass) that rate-limit;
  the app retries a mirror and shows plain-language errors, but heavy use may
  need a minute's pause. Results are cached for an hour.
- Built-up quality follows OSM landuse coverage — thin in some regions; the
  app says so and falls back to the admin boundary.
- Buffers/corridors use one UTM zone (centroid) — fine for AOI scale, not for
  continent-length lines (>~500 km) crossing several zones.
- KML `<ExtendedData>` attributes survive conversion; other styling from
  input files is replaced by LuxCarta styling.
