"""
run_cp4.py

Checkpoint 4 orchestration: turns the three stated final-report deliverables
into committed artifacts, all offline and deterministic (no API key, Python is
the source of truth for every statistic).

  1. State fixed-effects estimate of the wealth-capacity relationship
     -> data/output/fixed_effects_results.json
  2. County/state gap choropleth (general + food-specific gaps)
     -> data/output/figures/gap_choropleth.png
  3. Automated exact-first crosswalk for Virginia's independent cities,
     audited against the real county_fips_lookup + NGO county names
     -> data/output/va_crosswalk_report.json

Mirrors scripts/run_analysis.py: same PROJECT_ROOT / src path setup, same
committed-panel + county-lookup load, same output directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from load_data import DataLoader                      # noqa: E402
from fixed_effects import run_all as run_fixed_effects  # noqa: E402
from make_maps import choropleth_cartogram            # noqa: E402
from va_crosswalk import resolve_with_va_cities, resolution_report  # noqa: E402

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "output"
DEFAULT_PANEL = DEFAULT_OUTPUT_DIR / "joined_county_panel.csv"


def load_panel(panel_csv: Path) -> pd.DataFrame:
    """Committed county panel, county_fips kept as zero-padded string."""
    if not panel_csv.exists():
        raise FileNotFoundError(
            f"{panel_csv} not found -- run `python scripts/run_pipeline.py` first."
        )
    return pd.read_csv(panel_csv, dtype={"county_fips": "string"})


def _write_json(obj: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str))
    return path


def step_fixed_effects(panel: pd.DataFrame, output_dir: Path) -> dict:
    report = run_fixed_effects(panel)
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(report, output_dir / "fixed_effects_results.json")
    head = report["estimates"][0]
    print(f"  [FE] {report['headline_pair']}: FE slope "
          f"{head.get('fe_slope')} (std {head.get('fe_slope_standardized')}), "
          f"cluster-p {head.get('fe_p_value')}, "
          f"survives_state_fe={report['headline_survives_state_fe']}")
    return report


def step_choropleth(panel: pd.DataFrame, output_dir: Path) -> Path:
    path = choropleth_cartogram(panel, output_dir / "figures")
    print(f"  [MAP] wrote {path.relative_to(PROJECT_ROOT)}")
    return path


def step_va_crosswalk(output_dir: Path, sample: int | None) -> dict:
    loader = DataLoader()
    lookup = loader.load_county_lookup()
    ngos = loader.load_ngos()[["state", "county"]]
    if sample:
        ngos = ngos.head(sample)
    resolved = resolve_with_va_cities(ngos, lookup)
    report = resolution_report(resolved, lookup)
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(report, output_dir / "va_crosswalk_report.json")
    print(f"  [VA] exact={report['by_stage']['exact']} "
          f"normalized={report['by_stage']['normalized']} "
          f"unmatched={report['by_stage']['unmatched']}; "
          f"{len(report['collision_pairs_disambiguated'])} VA city/county "
          f"pairs disambiguated; "
          f"{report['va_rows_resolved_to_independent_city']} rows -> "
          f"independent cities")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Checkpoint 4 benchmark orchestration")
    ap.add_argument("--panel", default=str(DEFAULT_PANEL))
    ap.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    ap.add_argument("--skip-plots", action="store_true")
    ap.add_argument("--skip-va", action="store_true",
                    help="skip the VA crosswalk step (avoids loading the NGO file)")
    ap.add_argument("--va-sample", type=int, default=None,
                    help="cap NGO rows for a fast VA crosswalk smoke test")
    args = ap.parse_args(argv)

    output_dir = Path(args.output_dir)
    panel = load_panel(Path(args.panel))
    print(f"[run_cp4] panel: {len(panel):,} counties")

    step_fixed_effects(panel, output_dir)
    if not args.skip_plots:
        step_choropleth(panel, output_dir)
    if not args.skip_va:
        step_va_crosswalk(output_dir, args.va_sample)

    print("[run_cp4] done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
