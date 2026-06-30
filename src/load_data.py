"""
load_data.py

DataLoader for the six raw inputs of the Need-Capacity Gap Explorer.

Responsibilities
----------------
* Read each raw file (transparently decompressing the .gz NGO file).
* Standardize every column name to snake_case on load -- this normalization is
  the single source of truth for the rest of the pipeline.
* Preserve identifier columns (EIN, FIPS, GEOID) as zero-padded *strings* so we
  never lose leading zeros (e.g. FIPS "01001", which pandas would otherwise read
  as the integer 1001).
* Support a fast `sample_mode` (nrows per file) for development iterations.

All downstream modules reference the snake_cased names produced here, e.g.
`f9 01 rev tot cy` -> `f9_01_rev_tot_cy`, `Dac Status` -> `dac_status`,
`County Fips` -> `county_fips`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

# Project root = two levels up from this file (src/ -> repo root).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"

# Raw filenames (kept in one place so a rename only touches here).
FILES = {
    "ngos": "NGOs_with_categories_1MILLION_rows.csv.gz",
    "f9": "F9_P01_T00_SUMMARY_2022.csv",
    "disadvantaged": "disadvantaged_communities.csv",
    "county_lookup": "county_fips_lookup.csv",
    "poverty": "Poverty_Rates_2023.csv",
    "nccs": "nccs_crosswalk_economic.csv",
}

# Columns that must stay string identifiers (mapped by their ORIGINAL header,
# since dtype is applied before we rename to snake_case).
_STR_COLS = {
    "ngos": ["Ein"],
    "f9": ["Org Ein"],
    "disadvantaged": ["County Fips", "State Fips", "Geoid"],
    "county_lookup": ["County Fips"],
    "poverty": ["Fips Code"],
    "nccs": ["Geoid 2010"],
}


def to_snake_case(name: str) -> str:
    """'F9 01 Rev Tot Cy' -> 'f9_01_rev_tot_cy'."""
    name = name.strip().lower()
    name = re.sub(r"[^0-9a-z]+", "_", name)  # non-alnum runs -> single underscore
    return name.strip("_")


class DataLoader:
    """Loads the six raw tables with consistent typing and naming."""

    def __init__(self, raw_dir: str | Path = DEFAULT_RAW_DIR,
                 sample_mode: bool = False, sample_rows: int = 10_000):
        self.raw_dir = Path(raw_dir)
        self.sample_mode = sample_mode
        self.sample_rows = sample_rows

    # -- internals ---------------------------------------------------------
    def _read(self, key: str, **kwargs) -> pd.DataFrame:
        path = self.raw_dir / FILES[key]
        if not path.exists():
            raise FileNotFoundError(f"Missing raw file for '{key}': {path}")
        dtype = dict.fromkeys(_STR_COLS.get(key, []), "string")
        nrows = self.sample_rows if self.sample_mode else None
        df = pd.read_csv(path, dtype=dtype, nrows=nrows, low_memory=False, **kwargs)
        df.columns = [to_snake_case(c) for c in df.columns]
        return df

    # -- per-file loaders --------------------------------------------------
    def load_ngos(self) -> pd.DataFrame:
        """Nonprofit capacity base table (ein, state, county, category)."""
        return self._read("ngos")

    def load_f9(self) -> pd.DataFrame:
        """IRS Form 990 financial summary (org_ein, revenue, net assets)."""
        return self._read("f9")

    def load_disadvantaged(self) -> pd.DataFrame:
        """Census-tract need indicators with clean county_fips."""
        return self._read("disadvantaged")

    def load_county_lookup(self) -> pd.DataFrame:
        """County-name -> FIPS crosswalk (bare names, no suffix)."""
        return self._read("county_lookup")

    def load_poverty(self) -> pd.DataFrame:
        """County-level poverty percentage."""
        return self._read("poverty")

    def load_nccs(self) -> pd.DataFrame:
        """County-level economic indicators (income, poverty, unemployment)."""
        return self._read("nccs")

    def load_all(self) -> dict[str, pd.DataFrame]:
        """Return every table keyed by short name."""
        return {
            "ngos": self.load_ngos(),
            "f9": self.load_f9(),
            "disadvantaged": self.load_disadvantaged(),
            "county_lookup": self.load_county_lookup(),
            "poverty": self.load_poverty(),
            "nccs": self.load_nccs(),
        }


if __name__ == "__main__":
    loader = DataLoader(sample_mode=True)
    for name, df in loader.load_all().items():
        print(f"{name:14s} shape={df.shape}  cols={list(df.columns)[:6]}...")
