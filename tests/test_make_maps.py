"""
Tests for the map layer (offline, deterministic): GeoJSON parsing, county
accounting metadata, the state-mean aggregation, and the tile grid adapted
from the TA benchmark branch.
"""

import json

import pandas as pd
import pytest

from make_maps import (
    _tile_grid,
    choropleth_metadata,
    load_county_geometries,
    make_gap_maps,
    state_gap_means,
)

TINY_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "id": "01001",
         "geometry": {"type": "Polygon",
                      "coordinates": [[[-86.9, 32.6], [-86.4, 32.6],
                                       [-86.4, 32.9], [-86.9, 32.6]]]}},
        {"type": "Feature", "id": "02016",   # multipolygon incl. a +lon ring
         "geometry": {"type": "MultiPolygon",
                      "coordinates": [
                          [[[-166.0, 53.9], [-165.6, 53.9], [-165.8, 54.2],
                            [-166.0, 53.9]]],
                          [[[172.0, 52.9], [172.4, 52.9], [172.2, 53.1],
                            [172.0, 52.9]]]]}},
        {"type": "Feature", "id": "12086",   # geometry with no panel row
         "geometry": {"type": "Polygon",
                      "coordinates": [[[-80.9, 25.5], [-80.2, 25.5],
                                       [-80.2, 25.9], [-80.9, 25.5]]]}},
    ],
}


@pytest.fixture
def geo_path(tmp_path):
    p = tmp_path / "geo.json"
    p.write_text(json.dumps(TINY_GEOJSON))
    return p


def _panel():
    return pd.DataFrame({
        "county_fips": pd.array(["01001", "02016", "46102"], dtype="string"),
        "gap_score": [1.2, -0.4, 3.0],
        "food_gap_score": [0.6, -0.2, 2.5],
    })


def test_load_county_geometries_polygon_and_multipolygon(geo_path):
    geoms = load_county_geometries(geo_path)
    assert set(geoms) == {"01001", "02016", "12086"}
    assert len(geoms["01001"]) == 1
    assert len(geoms["02016"]) == 2          # both multipolygon parts kept
    assert geoms["01001"][0].shape[1] == 2


def test_choropleth_metadata_accounts_for_every_county(geo_path):
    meta = choropleth_metadata(_panel(), load_county_geometries(geo_path))
    assert meta["panel_counties"] == 3
    assert meta["counties_drawn"] == 2
    assert meta["missing_geometry_fips"] == ["46102"]  # post-2010 FIPS rename
    assert meta["no_data_counties"] == 1               # FL county, greyed


def test_make_gap_maps_renders_and_writes_meta(tmp_path, geo_path):
    paths = make_gap_maps(_panel(), tmp_path, geometry_path=geo_path)
    names = {p.name for p in paths}
    assert names == {"gap_cartogram_states.png",
                     "gap_score_choropleth_county.png",
                     "food_gap_score_choropleth_county.png",
                     "choropleth_meta.json"}
    meta = json.loads((tmp_path / "choropleth_meta.json").read_text())
    assert meta["counties_drawn"] + len(meta["missing_geometry_fips"]) == \
           meta["panel_counties"]


def test_make_gap_maps_skips_choropleth_without_geometry(tmp_path):
    paths = make_gap_maps(_panel(), tmp_path,
                          geometry_path=tmp_path / "nope.json")
    assert [p.name for p in paths] == ["gap_cartogram_states.png"]


def test_state_gap_means():
    panel = pd.DataFrame({
        "county_fips": ["01001", "01003", "06001"],
        "gap_score": [1.0, 3.0, -1.0],
        "food_gap_score": [0.5, 1.5, -0.5],
    })
    means = state_gap_means(panel)
    assert means.loc["AL", "gap_score"] == pytest.approx(2.0)
    assert means.loc["CA", "gap_score"] == pytest.approx(-1.0)
    assert means.loc["AL", "n_counties"] == 2


def test_tile_grid_unique_and_complete():
    grid = _tile_grid()
    assert len(set(grid.values())) == len(grid)   # every tile unique
    assert "AK" in grid and "HI" in grid
    assert len(grid) == 51                        # 50 states + DC
