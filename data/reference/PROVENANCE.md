# data/reference provenance

## us_counties_geo.json

- Source: https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json
- Retrieved: 2026-07-26
- Content: 3,221 US county features keyed by 5-digit FIPS (`feature.id`),
  Polygon/MultiPolygon in plain lon/lat. Derived from US Census Bureau
  cartographic boundary files (public domain); redistributed via the plotly
  datasets repository (MIT-licensed repackaging).
- Vintage note: the county set is 2010-era. Two panel counties received new
  FIPS codes after 2010 and therefore have no matching geometry here:
  02158 (Kusilvak Census Area, AK; formerly 02270 Wade Hampton) and
  46102 (Oglala Lakota County, SD; formerly 46113 Shannon). Per the project's
  no-manual-patching rule they are NOT re-aliased; the choropleth draws them
  as missing and `figures/choropleth_meta.json` enumerates them.
- Used by: `src/make_maps.py` (county choropleths). The state cartogram needs
  no geometry.
