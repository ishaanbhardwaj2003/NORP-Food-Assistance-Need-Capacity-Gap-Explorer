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
* NGO source selection (final checkpoint): the full 3,420,024-row
  NGOs_with_categories table arrived split-committable; the loader reads, in
  order of preference, (1) the committed multi-part directory
  data/raw/ngos_full/ (GitHub's 100 MB cap forces the split), (2) a local
  single-file full export NGOs_with_categories.csv.gz, (3) the original 1M-row
  truncated extract. `ngo_source="extract"|"full"|"auto"` overrides, and
  `self.ngo_source` records what was actually read so the profiler log carries
  the provenance. The full export's headers differ in casing (EIN, NTEE_code,
  is_category_LLM_generated), so identifier dtypes are matched by snake_case
  identity rather than by exact original header.

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
    "ngos": "NGOs_with_categories_1MILLION_rows.csv.gz",   # truncated extract
    "ngos_full_single": "NGOs_with_categories.csv.gz",     # local full export
    "f9": "F9_P01_T00_SUMMARY_2022.csv",
    "disadvantaged": "disadvantaged_communities.csv",
    "county_lookup": "county_fips_lookup.csv",
    "poverty": "Poverty_Rates_2023.csv",
    "nccs": "nccs_crosswalk_economic.csv",
}
# Committed multi-part directory for the full NGO table (each part < 100 MB).
NGOS_FULL_DIR = "ngos_full"

# Columns that must stay string identifiers, keyed by table then by the
# column's SNAKE_CASE name (matched case-insensitively against any header
# variant the source ships).
_STR_COLS = {
    "ngos": ["ein"],
    "f9": ["org_ein"],
    "disadvantaged": ["county_fips", "state_fips", "geoid"],
    "county_lookup": ["county_fips"],
    "poverty": ["fips_code"],
    "nccs": ["geoid_2010"],
}


def to_snake_case(name: str) -> str:
    """'F9 01 Rev Tot Cy' -> 'f9_01_rev_tot_cy'."""
    name = name.strip().lower()
    name = re.sub(r"[^0-9a-z]+", "_", name)  # non-alnum runs -> single underscore
    return name.strip("_")


class DataLoader:
    """Loads the six raw tables with consistent typing and naming."""

    def __init__(self, raw_dir: str | Path = DEFAULT_RAW_DIR,
                 sample_mode: bool = False, sample_rows: int = 10_000,
                 ngo_source: str = "auto"):
        if ngo_source not in ("auto", "full", "extract"):
            raise ValueError(f"ngo_source must be auto|full|extract, got {ngo_source!r}")
        self.raw_dir = Path(raw_dir)
        self.sample_mode = sample_mode
        self.sample_rows = sample_rows
        self.requested_ngo_source = ngo_source
        self.ngo_source: dict | None = None  # provenance of the last load_ngos

    # -- internals ---------------------------------------------------------
    def _read_csv(self, path: Path, str_cols: list[str],
                  nrows: int | None) -> pd.DataFrame:
        """Read one CSV with identifier columns forced to string dtype,
        matching them by snake_case identity so header-casing variants
        ('Ein' vs 'EIN', 'Ntee Code' vs 'NTEE_code') behave identically."""
        header = pd.read_csv(path, nrows=0)
        wanted = set(str_cols)
        dtype = {orig: "string" for orig in header.columns
                 if to_snake_case(orig) in wanted}
        df = pd.read_csv(path, dtype=dtype, nrows=nrows, low_memory=False)
        df.columns = [to_snake_case(c) for c in df.columns]
        return df

    def _read(self, key: str) -> pd.DataFrame:
        path = self.raw_dir / FILES[key]
        if not path.exists():
            raise FileNotFoundError(f"Missing raw file for '{key}': {path}")
        nrows = self.sample_rows if self.sample_mode else None
        return self._read_csv(path, _STR_COLS.get(key, []), nrows)

    def _ngo_full_parts(self) -> list[Path]:
        parts_dir = self.raw_dir / NGOS_FULL_DIR
        if not parts_dir.is_dir():
            return []
        return sorted(p for p in parts_dir.iterdir()
                      if p.name.endswith((".csv", ".csv.gz")))

    # -- per-file loaders --------------------------------------------------
    def load_ngos(self) -> pd.DataFrame:
        """Nonprofit capacity base table (ein, state, county, category).

        Source preference under 'auto': committed full parts, then a local
        single-file full export, then the truncated 1M-row extract.
        `self.ngo_source` records the choice for the profiler log.
        """
        nrows = self.sample_rows if self.sample_mode else None
        parts = self._ngo_full_parts()
        single_full = self.raw_dir / FILES["ngos_full_single"]
        use_full = (self.requested_ngo_source == "full"
                    or (self.requested_ngo_source == "auto"
                        and (parts or single_full.exists())))

        if use_full and parts:
            df = self._concat_parts(parts, nrows)
            self.ngo_source = {"mode": "full_parts", "files": len(parts),
                               "rows": int(len(df))}
            return df
        if use_full:
            if not single_full.exists():
                raise FileNotFoundError(
                    f"ngo_source='full' but neither {self.raw_dir / NGOS_FULL_DIR}/ "
                    f"parts nor {single_full} exist")
            df = self._read_csv(single_full, _STR_COLS["ngos"], nrows)
            self.ngo_source = {"mode": "full_single", "files": 1,
                               "rows": int(len(df))}
            return df

        df = self._read("ngos")
        self.ngo_source = {"mode": "extract", "files": 1, "rows": int(len(df))}
        return df

    def _concat_parts(self, parts: list[Path], nrows: int | None) -> pd.DataFrame:
        """Concatenate ordered NGO part files, honoring a sample-row cap."""
        frames = []
        remaining = nrows
        for p in parts:
            frames.append(self._read_csv(p, _STR_COLS["ngos"], remaining))
            if remaining is not None:
                remaining -= len(frames[-1])
                if remaining <= 0:
                    break
        return pd.concat(frames, ignore_index=True)

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
