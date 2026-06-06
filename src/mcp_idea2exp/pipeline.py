"""idea2exp pipeline: Stage-3 idea -> Stage-4 methodology -> Stage-5 plan.

Pure orchestration. The LLM call is injected as ``complete(system, user)
-> str`` so unit tests run with zero network and the server wires the real
gateway client.

Deterministic quality gates mirror the AutoResearch engine's hard gates:
a generated document missing required sections gets ONE bounded retry
with the missing sections named, then fails loudly. (LLM critics drift;
section checks don't.)
"""
from __future__ import annotations

import re
import subprocess
from typing import Callable

from .prompts import (
    EXPERIMENT_SECTIONS,
    METHODOLOGY_SECTIONS,
    METHODOLOGY_SYSTEM,
    build_experiment_prompt,
    build_methodology_prompt,
)

Complete = Callable[[str, str], str]


class GenerationError(RuntimeError):
    """Raised when a document still fails its section gate after the retry."""


def missing_sections(doc: str, required: list[str]) -> list[str]:
    """Deterministic gate: every required ``## N. Title`` heading must be
    present (numbering exact; title matching is case-insensitive prefix so
    minor rewording doesn't false-positive)."""
    out = []
    for heading in required:
        num = heading.split(".")[0]  # '## 1'
        pattern = re.compile(rf"^{re.escape(num)}\.", re.MULTILINE)
        if not pattern.search(doc or ""):
            out.append(heading)
    return out


def _generate_with_gate(complete: Complete, system: str, user: str,
                        required: list[str], doc_name: str) -> str:
    doc = complete(system, user)
    missing = missing_sections(doc, required)
    if not missing:
        return doc
    retry_user = (
        user
        + "\n\nYour previous attempt was REJECTED by a deterministic section "
        f"gate. It was missing these required sections: {', '.join(missing)}. "
        "Regenerate the COMPLETE document with every required section present."
    )
    doc = complete(system, retry_user)
    missing = missing_sections(doc, required)
    if missing:
        raise GenerationError(
            f"{doc_name} still missing required sections after retry: {missing}"
        )
    return doc


def idea_to_methodology(complete: Complete, stage3_output: str,
                        topic: str = "", constraints: str = "") -> str:
    if not (stage3_output or "").strip():
        raise ValueError("stage3_output is empty — nothing to design from")
    return _generate_with_gate(
        complete, METHODOLOGY_SYSTEM,
        build_methodology_prompt(stage3_output, topic, constraints),
        METHODOLOGY_SECTIONS, "stage4_methodology.md",
    )


def methodology_to_experiment(complete: Complete, stage4_methodology: str,
                              stage3_output: str = "", constraints: str = "") -> str:
    if not (stage4_methodology or "").strip():
        raise ValueError("stage4_methodology is empty")
    return _generate_with_gate(
        complete, METHODOLOGY_SYSTEM,
        build_experiment_prompt(stage4_methodology, stage3_output, constraints),
        EXPERIMENT_SECTIONS, "stage5_experiment_design.md",
    )


def idea_to_experiment(complete: Complete, stage3_output: str,
                       topic: str = "", constraints: str = "") -> dict:
    """Full chain. Returns both artifacts plus the pin-verification report
    (when the plan pins a repo, we verify it for real — run 083041abd013
    burned a full stage on a hallucinated pin)."""
    methodology = idea_to_methodology(complete, stage3_output, topic, constraints)
    plan = methodology_to_experiment(complete, methodology, stage3_output, constraints)
    pin = extract_pin(plan)
    pin_report = ""
    if pin and pin.get("repository"):
        pin_report = verify_pin(pin["repository"], pin.get("files") or [])
    return {
        "stage4_methodology_md": methodology,
        "stage5_experiment_design_md": plan,
        "pin_verification": pin_report,
    }


# ---------------------------------------------------------------------------
# Codebase-pin verification (real git, no LLM)
# ---------------------------------------------------------------------------

_REPO_RE = re.compile(r"Repository:\s*\**\s*<?(https://github\.com/[\w.\-]+/[\w.\-]+)>?", re.IGNORECASE)
_FILE_CELL_RE = re.compile(r"^\|\s*`([^`|]+\.[a-z]{1,5})`\s*\|", re.MULTILINE)


def extract_pin(plan_md: str) -> dict | None:
    """Pull the pinned repo URL + adaptation-surface file paths out of §9."""
    if "NO USABLE UPSTREAM FOUND" in (plan_md or ""):
        return None
    m = _REPO_RE.search(plan_md or "")
    if not m:
        return None
    files = _FILE_CELL_RE.findall(plan_md)
    return {"repository": m.group(1).rstrip("/").removesuffix(".git"), "files": files}


def verify_pin(repo_url: str, files: list[str], timeout: int = 60) -> str:
    """Real verification: ls-remote for the live HEAD sha; shallow clone +
    ls-tree to check every adaptation-surface file exists. Returns an
    evidence block to paste under the plan's §9 Verification."""
    lines: list[str] = [f"## Pin verification — {repo_url}"]
    try:
        ls = subprocess.run(
            ["git", "ls-remote", repo_url, "HEAD"],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return f"PIN VERIFICATION FAILED: git ls-remote errored: {exc}"
    if ls.returncode != 0 or not ls.stdout.strip():
        return (f"PIN VERIFICATION FAILED: repository unreachable "
                f"({(ls.stderr or 'no output').strip()[:200]}) — do NOT implement against this pin")
    head_sha = ls.stdout.split()[0]
    lines.append(f"git ls-remote HEAD: {head_sha}")

    if files:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            try:
                cl = subprocess.run(
                    ["git", "clone", "--depth", "1", "--no-checkout", repo_url, td],
                    capture_output=True, text=True, timeout=timeout * 3,
                )
                tree = subprocess.run(
                    ["git", "-C", td, "ls-tree", "-r", "--name-only", "HEAD"],
                    capture_output=True, text=True, timeout=timeout,
                ) if cl.returncode == 0 else None
            except (subprocess.SubprocessError, OSError) as exc:
                return f"PIN VERIFICATION FAILED: clone/ls-tree errored: {exc}"
        if tree is None or tree.returncode != 0:
            return "PIN VERIFICATION FAILED: could not list the repository tree"
        present = set(tree.stdout.split())
        missing = [f for f in files if f not in present]
        for f in files:
            lines.append(f"file {'OK     ' if f in present else 'MISSING'} {f}")
        if missing:
            lines.append(
                "VERDICT: FAIL — adaptation-surface file(s) not in the tree; "
                "the pin is hallucinated. Fix the plan before implementation."
            )
            return "\n".join(lines)
    lines.append("VERDICT: PASS")
    return "\n".join(lines)
