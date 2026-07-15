"""Offline cache replay: fresh caches replay, stale caches are rejected."""

import json

import pytest

from correlation_agent import (
    PROMPT_VERSION, canonical_hash, check_cache_integrity, get_proposal,
    _integrity_metadata,
)

SCHEMA = {"need_vars": {"poverty_rate": {"mean": 1.0}}, "n_counties": 3}
GATE = {"verdict": "proceed", "reasons": ["all tables and joins usable"]}


def _artifact(schema=SCHEMA, gate=GATE):
    return {
        "metadata": {"mode": "cached", "source": "offline_development_session",
                     **_integrity_metadata(schema, gate)},
        "schema_context": schema,
        "proposal": {"candidates": [], "gate_review": {"verdict": "proceed"},
                     "narrative_notes": ""},
    }


def _write(tmp_path, artifact):
    path = tmp_path / "llm_candidates.json"
    path.write_text(json.dumps(artifact))
    return path


def test_canonical_hash_is_order_insensitive():
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})


def test_fresh_cache_replays(tmp_path):
    path = _write(tmp_path, _artifact())
    artifact = get_proposal(SCHEMA, GATE, path, live=False)
    assert artifact["proposal"]["candidates"] == []
    assert artifact["metadata"]["prompt_version"] == PROMPT_VERSION


def test_stale_schema_rejected(tmp_path):
    path = _write(tmp_path, _artifact())
    changed = {"need_vars": {"poverty_rate": {"mean": 99.0}}, "n_counties": 4}
    with pytest.raises(RuntimeError, match="STALE"):
        get_proposal(changed, GATE, path, live=False)


def test_stale_gate_rejected(tmp_path):
    path = _write(tmp_path, _artifact())
    changed_gate = {"verdict": "stop", "reasons": ["boom"]}
    with pytest.raises(RuntimeError, match="STALE"):
        get_proposal(SCHEMA, changed_gate, path, live=False)


def test_allow_stale_bypass(tmp_path):
    path = _write(tmp_path, _artifact())
    changed = {"need_vars": {}, "n_counties": 0}
    artifact = get_proposal(changed, GATE, path, live=False, allow_stale=True)
    assert artifact["proposal"] is not None


def test_check_cache_integrity_reports_specific_keys():
    art = _artifact()
    problems = check_cache_integrity(art, {"other": 1}, GATE)
    assert any("schema_context_sha256" in p for p in problems)
    assert not any("gate_sha256" in p for p in problems)


def test_missing_cache_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        get_proposal(SCHEMA, GATE, tmp_path / "nope.json", live=False)
