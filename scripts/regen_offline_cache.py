"""
regen_offline_cache.py

Rebuild the committed offline LLM artifact (data/output/llm_candidates.json)
against the CURRENT panel schema and gate.

The artifact is hash-bound: correlation_agent records SHA-256 hashes of the
schema context and gate it was generated against, and run_analysis (offline
mode) refuses a stale replay. Any change to the panel (new counties, the full
NGO table) therefore requires regenerating the artifact. Two supported paths:

  * `python scripts/run_analysis.py --live`  -- Anthropic API (needs a key);
  * this script -- the no-key path used since Checkpoint 3: a development-
    session Claude authors the candidate payload (pairs, hypotheses, expected
    signs, gate review, narrative notes) as a JSON file, and THIS script
    derives the schema context and gate from the committed outputs, validates
    the payload with the same validate_proposal guardrails as a live call,
    stamps the integrity hashes, and writes the artifact. The metadata note
    discloses the authorship honestly, exactly as the CP3 artifact did.

The script computes every hash itself, so the artifact can never silently
mismatch the outputs it sits next to.

Usage:
    python scripts/regen_offline_cache.py --candidates <payload.json> \
        [--model claude-fable-5] [--output-dir data/output]
    python scripts/regen_offline_cache.py --print-context   # inspect only
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

from load_data import DataLoader  # noqa: E402
from correlation_agent import (  # noqa: E402
    PROMPT_VERSION, _integrity_metadata, add_derived_columns,
    build_schema_context, validate_proposal,
)

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "output"

NOTE = ("Authored by Claude from the panel schema during development (no API "
        "key in the environment); regenerate live with `python "
        "scripts/run_analysis.py --live`. LLM proposals are advisory; Python "
        "computes all statistics. Hashes bind this artifact to the exact "
        "panel schema context and gate it was written against; a mismatched "
        "replay is rejected as stale.")


def load_context(output_dir: Path) -> tuple[dict, dict]:
    panel = pd.read_csv(output_dir / "joined_county_panel.csv",
                        dtype={"county_fips": "string"})
    lookup = DataLoader().load_county_lookup()
    panel = panel.merge(lookup, on="county_fips", how="left", validate="1:1")
    panel = add_derived_columns(panel)
    schema_ctx = build_schema_context(panel)
    gate = json.loads((output_dir / "profiler_log.json").read_text())["gate"]
    return schema_ctx, gate


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Regenerate the offline LLM artifact")
    ap.add_argument("--candidates", default=None,
                    help="JSON payload: {candidates, gate_review, narrative_notes}")
    ap.add_argument("--model", default="claude-fable-5",
                    help="model name recorded in the artifact metadata")
    ap.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    ap.add_argument("--print-context", action="store_true",
                    help="print the current schema context + gate and exit")
    args = ap.parse_args(argv)
    output_dir = Path(args.output_dir)

    schema_ctx, gate = load_context(output_dir)
    if args.print_context:
        print(json.dumps({"schema_context": schema_ctx, "gate": gate}, indent=2))
        return 0
    if not args.candidates:
        print("--candidates is required (or use --print-context)")
        return 2

    payload = json.loads(Path(args.candidates).read_text())
    artifact = {
        "metadata": {
            "mode": "cached",
            "source": "offline_development_session",
            "model": args.model,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            **_integrity_metadata(schema_ctx, gate),
            "note": NOTE,
        },
        "schema_context": schema_ctx,
        "proposal": validate_proposal(payload),
    }
    out = output_dir / "llm_candidates.json"
    out.write_text(json.dumps(artifact, indent=2))
    val = artifact["proposal"]["validation"]
    print(f"wrote {out}")
    print(f"  candidates: {val['n_valid']} valid of {val['n_raw']} "
          f"(count_in_range={val['count_in_range']})")
    print(f"  schema hash: {artifact['metadata']['schema_context_sha256'][:16]}...")
    print(f"  gate hash:   {artifact['metadata']['gate_sha256'][:16]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
