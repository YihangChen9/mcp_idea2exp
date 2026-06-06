"""Unit tests — zero network. The LLM is injected as a stub ``complete``."""
from __future__ import annotations

import pytest

from mcp_idea2exp import pipeline
from mcp_idea2exp.prompts import EXPERIMENT_SECTIONS, METHODOLOGY_SECTIONS

GOOD_METHODOLOGY = "\n\n".join(f"{h}\ncontent" for h in METHODOLOGY_SECTIONS)
GOOD_PLAN = "\n\n".join(f"{h}\ncontent" for h in EXPERIMENT_SECTIONS) + "\nNO USABLE UPSTREAM FOUND."


def test_section_gate_passes_complete_doc():
    assert pipeline.missing_sections(GOOD_METHODOLOGY, METHODOLOGY_SECTIONS) == []


def test_section_gate_names_missing():
    doc = GOOD_METHODOLOGY.replace("## 4. Pre-registered statistical tests", "## blah")
    missing = pipeline.missing_sections(doc, METHODOLOGY_SECTIONS)
    assert missing == ["## 4. Pre-registered statistical tests"]


def test_generation_retries_once_with_missing_named_then_succeeds():
    calls = []

    def complete(system, user):
        calls.append(user)
        if len(calls) == 1:
            return "## 1. Problem\nonly one section"
        return GOOD_METHODOLOGY

    doc = pipeline.idea_to_methodology(complete, "H1: X beats Y")
    assert doc == GOOD_METHODOLOGY
    assert len(calls) == 2
    assert "missing these required sections" in calls[1]
    assert "## 2. Variables" in calls[1]


def test_generation_fails_loudly_after_retry():
    def complete(system, user):
        return "## 1. Problem\nstill incomplete"

    with pytest.raises(pipeline.GenerationError):
        pipeline.idea_to_methodology(complete, "H1: X beats Y")


def test_empty_stage3_rejected():
    with pytest.raises(ValueError):
        pipeline.idea_to_methodology(lambda s, u: GOOD_METHODOLOGY, "   ")


def test_full_chain_returns_both_docs_and_skips_pin_when_from_scratch():
    def complete(system, user):
        return GOOD_PLAN if "stage5_experiment_design" in user else GOOD_METHODOLOGY

    out = pipeline.idea_to_experiment(complete, "H1: X beats Y")
    assert out["stage4_methodology_md"] == GOOD_METHODOLOGY
    assert out["stage5_experiment_design_md"] == GOOD_PLAN
    assert out["pin_verification"] == ""  # NO USABLE UPSTREAM FOUND → no git calls


def test_extract_pin_parses_repo_and_files():
    plan = (
        "## 9. Codebase pin\n"
        "- Repository: https://github.com/pypa/sampleproject\n"
        "- Commit: <from ls-remote>\n"
        "| File | Change | Reason | LOC |\n"
        "|---|---|---|---|\n"
        "| `src/sample/benchmark.py` | add driver | exp | 140 |\n"
        "| `pyproject.toml` | script entry | cli | 1 |\n"
    )
    pin = pipeline.extract_pin(plan)
    assert pin["repository"] == "https://github.com/pypa/sampleproject"
    assert "src/sample/benchmark.py" in pin["files"]


def test_extract_pin_none_for_from_scratch():
    assert pipeline.extract_pin("blah\nNO USABLE UPSTREAM FOUND.\nblah") is None


def test_verify_pin_fails_unreachable_repo():
    out = pipeline.verify_pin("https://github.com/this-org-does-not-exist-xx/nope", [])
    assert "FAILED" in out
