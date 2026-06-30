"""
profile_data.py

The automated profiler + self-verification gate -- the centerpiece deliverable.

It does four things:
1. Schema report   : shape, dtypes, columns per table.
2. Null audit      : per-column null %, with attention to join keys.
3. Join validation : measured match rate between two sides of a join.
4. Quality gate    : a per-table/per-join verdict AND a single overall
                     `proceed | proceed_with_warning | stop` verdict that the
                     pipeline checks before running downstream steps.

Verdict thresholds (completeness / match rate):
    USABLE   >= 0.80
    WARNING  0.50 - 0.80
    DROP     < 0.50

The LLM-assisted version of this gate is Checkpoint 3 scope; for Checkpoint 2 the
gate is fully rule-based. The architecture/hook is deliberately in place now.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

USABLE, WARNING, DROP = "usable", "usable_with_warning", "drop"
PROCEED, PROCEED_WARN, STOP = "proceed", "proceed_with_warning", "stop"

USABLE_THRESHOLD = 0.80
DROP_THRESHOLD = 0.50

# Tables whose failure should HALT the pipeline (need side is load-bearing for
# every county). Capacity-side join gaps (FL/CT) only warn -- they auto-drop.
NEED_SIDE_TABLES = {"disadvantaged", "poverty", "nccs"}


def classify(rate: float) -> str:
    if rate >= USABLE_THRESHOLD:
        return USABLE
    if rate >= DROP_THRESHOLD:
        return WARNING
    return DROP


class DataProfiler:
    """Accumulates table/join profiles and renders an overall gate verdict."""

    def __init__(self):
        self.tables: dict[str, dict] = {}
        self.joins: list[dict] = []

    # -- table profiling ---------------------------------------------------
    def profile_table(self, name: str, df: pd.DataFrame,
                      key_cols: list[str] | None = None) -> dict:
        n = len(df)
        null_pct = {
            c: round(float(df[c].isna().mean()), 4) for c in df.columns
        }
        key_cols = [c for c in (key_cols or []) if c in df.columns]
        # Table completeness = mean non-null over its declared key columns
        # (falls back to 1.0 when no keys are declared).
        if key_cols:
            completeness = float(
                sum(1 - null_pct[c] for c in key_cols) / len(key_cols)
            )
        else:
            completeness = 1.0
        report = {
            "rows": int(n),
            "columns": list(df.columns),
            "dtypes": {c: str(t) for c, t in df.dtypes.items()},
            "null_pct": null_pct,
            "key_cols": key_cols,
            "key_completeness": round(completeness, 4),
            "verdict": classify(completeness),
        }
        self.tables[name] = report
        return report

    # -- join validation ---------------------------------------------------
    def record_join(self, name: str, side: str, match_rate: float,
                    matched: int, unmatched: int, detail: dict | None = None):
        """
        side : 'need' or 'capacity'. Determines gate severity:
               need-side DROP -> stop; capacity-side DROP -> warn (auto-drop).
        """
        entry = {
            "name": name,
            "side": side,
            "match_rate": round(float(match_rate), 4),
            "matched": int(matched),
            "unmatched": int(unmatched),
            "verdict": classify(match_rate),
            "detail": detail or {},
        }
        self.joins.append(entry)
        return entry

    # -- overall gate ------------------------------------------------------
    @staticmethod
    def _table_signal(name: str, rep: dict) -> tuple[str, str] | None:
        """Map a table report to (verdict, reason), or None if clean."""
        if rep["verdict"] == DROP and name in NEED_SIDE_TABLES:
            return STOP, (f"need-side table '{name}' key_completeness="
                          f"{rep['key_completeness']} below DROP threshold")
        if rep["verdict"] == WARNING:
            return PROCEED_WARN, f"table '{name}' is {WARNING}"
        return None

    @staticmethod
    def _join_signal(j: dict) -> tuple[str, str] | None:
        """Map a join report to (verdict, reason), or None if clean."""
        if j["verdict"] == DROP and j["side"] == "need":
            return STOP, (f"need-side join '{j['name']}' match_rate="
                          f"{j['match_rate']} below DROP threshold")
        # Capacity side: any auto-dropped rows are surfaced as a warning (even
        # when the overall match rate is 'usable'), because dropping whole
        # states (FL/CT) is noteworthy and must be visible in the verdict.
        if j["side"] == "capacity" and (j["verdict"] in (WARNING, DROP) or j["unmatched"] > 0):
            return PROCEED_WARN, (
                f"capacity-side join '{j['name']}' match_rate={j['match_rate']} "
                f"({j['verdict']}) -> auto-drop unmatched ({j['unmatched']} rows); "
                f"top states: {j['detail'].get('top_unmatched_states', {})}")
        return None

    def gate(self) -> dict:
        """Render the single proceed / proceed_with_warning / stop verdict."""
        rank = {PROCEED: 0, PROCEED_WARN: 1, STOP: 2}
        signals = [self._table_signal(n, r) for n, r in self.tables.items()]
        signals += [self._join_signal(j) for j in self.joins]
        signals = [s for s in signals if s is not None]

        verdict = PROCEED
        reasons = [reason for _, reason in signals]
        for sig_verdict, _ in signals:
            if rank[sig_verdict] > rank[verdict]:
                verdict = sig_verdict

        if not reasons:
            reasons.append("all tables and joins usable")
        return {"verdict": verdict, "reasons": reasons}

    # -- serialization -----------------------------------------------------
    def to_dict(self) -> dict:
        return {"tables": self.tables, "joins": self.joins, "gate": self.gate()}

    def save(self, path: str | Path) -> dict:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_dict()
        path.write_text(json.dumps(payload, indent=2))
        return payload
