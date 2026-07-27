"""
Tests for DataLoader's final-checkpoint upgrades: header-casing robustness
(the full export ships EIN / NTEE_code / is_category_LLM_generated) and the
three-way NGO source selection (committed full parts > local single full
export > truncated extract).
"""

import gzip

import pandas as pd
import pytest

from load_data import DataLoader, to_snake_case

EXTRACT_NAME = "NGOs_with_categories_1MILLION_rows.csv.gz"
FULL_SINGLE_NAME = "NGOs_with_categories.csv.gz"

EXTRACT_HEADER = "Ein,Name,Fulladdr,City,State,Zip,County,Ntee Code,Category,Is Category Llm Generated"
FULL_HEADER = "EIN,NAME,FULLADDR,CITY,STATE,ZIP,COUNTY,NTEE_code,CATEGORY,is_category_LLM_generated"


def _row(ein, county="Autauga County", state="AL"):
    return f'{ein},Org {ein},"X,{state}",Town,{state},99999,{county},A01,Unknown,'


def _write_gz(path, header, eins):
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(header + "\n")
        for e in eins:
            fh.write(_row(e) + "\n")


@pytest.fixture
def raw_dir(tmp_path):
    _write_gz(tmp_path / EXTRACT_NAME, EXTRACT_HEADER, ["001", "002"])
    return tmp_path


def test_snake_case_maps_both_header_variants_identically():
    assert [to_snake_case(c) for c in EXTRACT_HEADER.split(",")] == \
           [to_snake_case(c) for c in FULL_HEADER.split(",")]
    assert to_snake_case("is_category_LLM_generated") == "is_category_llm_generated"
    assert to_snake_case("NTEE_code") == "ntee_code"


def test_extract_mode_without_full_data(raw_dir):
    loader = DataLoader(raw_dir=raw_dir)
    df = loader.load_ngos()
    assert loader.ngo_source == {"mode": "extract", "files": 1, "rows": 2}
    # String dtype preserved even for numeric-looking EINs (leading zeros kept).
    assert list(df["ein"]) == ["001", "002"]


def test_full_single_preferred_over_extract(raw_dir):
    _write_gz(raw_dir / FULL_SINGLE_NAME, FULL_HEADER, ["1", "2", "3"])
    loader = DataLoader(raw_dir=raw_dir)
    df = loader.load_ngos()
    assert loader.ngo_source["mode"] == "full_single"
    assert len(df) == 3
    assert list(df.columns)[:3] == ["ein", "name", "fulladdr"]
    assert df["ein"].dtype == "string"          # dtype matched despite EIN casing


def test_full_parts_preferred_and_ordered(raw_dir):
    parts = raw_dir / "ngos_full"
    parts.mkdir()
    _write_gz(parts / "NGOs_with_categories.part1.csv.gz", FULL_HEADER, ["1", "2"])
    _write_gz(parts / "NGOs_with_categories.part2.csv.gz", FULL_HEADER, ["3"])
    _write_gz(raw_dir / FULL_SINGLE_NAME, FULL_HEADER, ["9"])  # must be ignored
    loader = DataLoader(raw_dir=raw_dir)
    df = loader.load_ngos()
    assert loader.ngo_source == {"mode": "full_parts", "files": 2, "rows": 3}
    assert list(df["ein"]) == ["1", "2", "3"]   # filename order preserved


def test_extract_override_ignores_full_data(raw_dir):
    parts = raw_dir / "ngos_full"
    parts.mkdir()
    _write_gz(parts / "NGOs_with_categories.part1.csv.gz", FULL_HEADER, ["1"])
    loader = DataLoader(raw_dir=raw_dir, ngo_source="extract")
    df = loader.load_ngos()
    assert loader.ngo_source["mode"] == "extract"
    assert list(df["ein"]) == ["001", "002"]


def test_sample_mode_caps_across_parts(raw_dir):
    parts = raw_dir / "ngos_full"
    parts.mkdir()
    _write_gz(parts / "NGOs_with_categories.part1.csv.gz", FULL_HEADER, ["1", "2"])
    _write_gz(parts / "NGOs_with_categories.part2.csv.gz", FULL_HEADER, ["3", "4"])
    loader = DataLoader(raw_dir=raw_dir, sample_mode=True, sample_rows=3)
    df = loader.load_ngos()
    assert len(df) == 3
    assert list(df["ein"]) == ["1", "2", "3"]


def test_invalid_ngo_source_rejected(raw_dir):
    with pytest.raises(ValueError, match="ngo_source"):
        DataLoader(raw_dir=raw_dir, ngo_source="bogus")
