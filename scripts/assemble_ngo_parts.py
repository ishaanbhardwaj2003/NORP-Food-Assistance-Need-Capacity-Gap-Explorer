"""
assemble_ngo_parts.py

Turn the full NGOs_with_categories export into committed, loadable evidence.

GitHub rejects files over 100 MB and the full export is ~162 MB gzipped, so
the canonical committed form is data/raw/ngos_full/ with N gzipped CSV parts
(each carrying the header, each well under the cap). DataLoader reads the
parts in filename order; this script creates and/or validates them.

Modes:
    --source <csv[.gz]>   validate the single-file export, then split it into
                          --parts gzipped parts under --out
    --validate-only       validate an existing --out directory of parts
                          (row totals, EIN uniqueness, schema, food count)

Validation is anchored to two externally verified numbers: the Checkpoint 1
Metabase row count (3,420,024) and its food-category count (~40,080; the
delivered export measures 40,086, within tolerance).

Usage:
    python scripts/assemble_ngo_parts.py --source data/raw/NGOs_with_categories.csv.gz
    python scripts/assemble_ngo_parts.py --validate-only
"""

from __future__ import annotations

import argparse
import gzip
import math
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from load_data import NGOS_FULL_DIR, to_snake_case  # noqa: E402

DEFAULT_OUT = PROJECT_ROOT / "data" / "raw" / NGOS_FULL_DIR
EXPECTED_ROWS = 3_420_024
FOOD_LABEL = "Food, Agriculture and Nutrition"
FOOD_ANCHOR = 40_080          # Checkpoint 1 Metabase verification
FOOD_TOLERANCE = 0.01         # +-1%
# The extract's post-snake_case schema is the contract every part must match.
EXPECTED_SCHEMA = ["ein", "name", "fulladdr", "city", "state", "zip", "county",
                   "ntee_code", "category", "is_category_llm_generated"]
GITHUB_SOFT_CAP_MB = 95


def _snake_columns(path: Path) -> list[str]:
    return [to_snake_case(c) for c in pd.read_csv(path, nrows=0).columns]


def validate_frame(df: pd.DataFrame, label: str, expected_rows: int) -> bool:
    """Run the delivery checks on a fully loaded (snake_cased) NGO table."""
    ok = True

    def check(name: str, passed: bool, detail: str) -> None:
        nonlocal ok
        ok &= passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}: {detail}")

    check("schema", list(df.columns) == EXPECTED_SCHEMA,
          f"{list(df.columns)}")
    check("row_count", len(df) == expected_rows,
          f"{len(df):,} (expected {expected_rows:,})")
    eins = df["ein"].astype("string")
    check("ein_nonnull", int(eins.isna().sum()) == 0,
          f"{int(eins.isna().sum())} null EINs")
    check("ein_unique", eins.is_unique, f"{eins.nunique():,} unique of {len(df):,}")
    food = int((df["category"] == FOOD_LABEL).sum())
    rel = abs(food - FOOD_ANCHOR) / FOOD_ANCHOR
    check("food_count", rel <= FOOD_TOLERANCE,
          f"{food:,} vs CP1 anchor {FOOD_ANCHOR:,} (rel diff {rel:.3%})")
    top = df["state"].astype("string").value_counts().head(5).to_dict()
    print(f"  [info] top states: {top}")
    print(f"  [info] llm-generated flag non-null: "
          f"{int(df['is_category_llm_generated'].notna().sum()):,}")
    return ok


def load_snake(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype="string", low_memory=False)
    df.columns = [to_snake_case(c) for c in df.columns]
    return df


def split_source(source: Path, out_dir: Path, n_parts: int) -> list[Path]:
    """Split the validated single-file export into n gzipped parts, each with
    the original header, preserving row order (the export is EIN-sorted)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.csv.gz"):
        old.unlink()

    total = sum(1 for _ in gzip.open(source, "rt", encoding="utf-8")) - 1
    rows_per_part = math.ceil(total / n_parts)
    print(f"  splitting {total:,} rows into {n_parts} parts "
          f"of <= {rows_per_part:,} rows")

    paths = []
    with pd.read_csv(source, dtype="string", low_memory=False,
                     chunksize=250_000) as reader:
        part_idx, part_rows, handle = 0, 0, None
        for chunk in reader:
            start = 0
            while start < len(chunk):
                if handle is None:
                    path = out_dir / f"NGOs_with_categories.part{part_idx + 1}.csv.gz"
                    handle = gzip.open(path, "wt", encoding="utf-8",
                                       compresslevel=6)
                    chunk.head(0).to_csv(handle, index=False)
                    paths.append(path)
                take = min(len(chunk) - start, rows_per_part - part_rows)
                chunk.iloc[start:start + take].to_csv(handle, index=False,
                                                      header=False)
                part_rows += take
                start += take
                if part_rows >= rows_per_part:
                    handle.close()
                    handle, part_rows, part_idx = None, 0, part_idx + 1
        if handle is not None:
            handle.close()

    for p in paths:
        mb = p.stat().st_size / 1e6
        flag = "" if mb < GITHUB_SOFT_CAP_MB else "  ** exceeds GitHub-safe size **"
        print(f"  wrote {p.name}: {mb:.1f} MB{flag}")
    return paths


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Split/validate the full NGO export")
    ap.add_argument("--source", default=None,
                    help="single-file full export to validate and split")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help=f"parts directory (default {DEFAULT_OUT})")
    ap.add_argument("--parts", type=int, default=4)
    ap.add_argument("--expected-rows", type=int, default=EXPECTED_ROWS)
    ap.add_argument("--validate-only", action="store_true",
                    help="validate the existing parts directory and exit")
    args = ap.parse_args(argv)
    out_dir = Path(args.out)

    if args.validate_only:
        parts = sorted(out_dir.glob("*.csv*"))
        if not parts:
            print(f"no parts found in {out_dir}")
            return 1
        print(f"Validating {len(parts)} committed parts in {out_dir} ...")
        df = pd.concat([load_snake(p) for p in parts], ignore_index=True)
        return 0 if validate_frame(df, "parts", args.expected_rows) else 1

    if not args.source:
        print("--source is required unless --validate-only")
        return 2
    source = Path(args.source)
    print(f"Validating single-file export {source} ...")
    df = load_snake(source)
    if not validate_frame(df, "source", args.expected_rows):
        print("source failed validation; not splitting")
        return 1
    del df

    print(f"Splitting into {args.parts} parts under {out_dir} ...")
    split_source(source, out_dir, args.parts)

    print("Re-validating the parts round-trip ...")
    parts = sorted(out_dir.glob("*.csv.gz"))
    df = pd.concat([load_snake(p) for p in parts], ignore_index=True)
    ok = validate_frame(df, "parts", args.expected_rows)
    print("done." if ok else "PARTS FAILED VALIDATION")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
