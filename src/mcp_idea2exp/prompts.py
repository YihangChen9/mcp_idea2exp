"""Prompt builders — the distilled AutoResearch Stage-4/5 contract.

Every rule here was paid for by a real pipeline failure:
- Stage-5-authoritative parameters (run be7144a49333)
- pin verification with ls-remote/ls-tree evidence (run 083041abd013:
  Stage 5 copied a runbook example's nonexistent commit + file verbatim)
- truncation-confound control + equal budgets (GSM8K campaign)
- n_seeds >= 3 for stochastic decoding, single-run only for greedy with
  justification
- smoke contract: same code path, same schema, <=5 min
- environment-first: deps verified/built BEFORE any experiment run
- parallelism-first: batch the full (item x condition x seed) grid;
  per-example generate() loops are forbidden (3,957 generations ran in
  80s once batched)
"""
from __future__ import annotations

METHODOLOGY_SYSTEM = """You are a CCF-A-grade research methodology designer.
You turn a selected research hypothesis into a rigorous, pre-registered
methodology. You design; you do not implement. British English. No
marketing adjectives (novel, significant, robust...). Output ONLY the
markdown document requested — no preamble, no commentary."""

METHODOLOGY_SECTIONS = [
    "## 1. Problem",
    "## 2. Variables",
    "## 3. Hypotheses",
    "## 4. Pre-registered statistical tests",
    "## 5. Evaluation metrics",
    "## 6. Threats to validity",
]

EXPERIMENT_SECTIONS = [
    "## 1. Experiment Overview",
    "## 2. Design matrix",
    "## 3. Randomisation and seeds",
    "## 4. Power / sample size",
    "## 5. Locked statistical analysis",
    "## 6. Smoke contract",
    "## 7. Execution environment",
    "## 8. Assignments",
    "## 9. Codebase pin",
]


def build_methodology_prompt(stage3_output: str, topic: str = "", constraints: str = "") -> str:
    extra = f"\nAdditional topic context: {topic}\n" if topic else ""
    cons = f"\nHard constraints from the caller (budget/hardware/data): {constraints}\n" if constraints else ""
    return f"""Turn the following Stage-3 output (selected research hypotheses /
idea) into a Stage-4 methodology document.
{extra}{cons}
--- STAGE 3 OUTPUT (the idea — treat its hypothesis as the contract) ---
{stage3_output}
--- END STAGE 3 OUTPUT ---

Write `stage4_methodology.md` with EXACTLY these sections:

## 1. Problem
One paragraph: what is being tested and why it is decidable by an experiment.

## 2. Variables
A table of independent variables (IVs), dependent variables (DVs), and
controlled variables, each with its allowed values/levels. Every IV/DV
must be measurable by code.

## 3. Hypotheses
H1..Hn stated as falsifiable, directional claims with explicit
effect-size thresholds (e.g. "H1: accuracy_B - accuracy_A >= 0.10").
Include at least one falsification check (a result pattern that would
INVALIDATE the headline claim, e.g. a truncation or extraction confound).

## 4. Pre-registered statistical tests
For each hypothesis: the exact test (paired where the design is paired),
the effect-size measure with CI method, alpha, and the
multiple-comparison correction. These are LOCKED — downstream stages may
not substitute tests.

## 5. Evaluation metrics
Exact metric definitions including the answer-extraction / scoring rule
(state the extraction pattern precisely — extraction yield must itself
be reported as a diagnostic).

## 6. Threats to validity
Honest list, each with its mitigation or an explicit acceptance. Always
consider: truncation/budget confounds between conditions (give both
conditions EQUAL budgets and add a diagnostic arm when generation
length differs by design), extraction-rule bias, single-model
generalisation, seed/variance coverage."""


def build_experiment_prompt(stage4_methodology: str, stage3_output: str = "",
                            constraints: str = "") -> str:
    cons = f"\nHard constraints from the caller (budget/hardware/data): {constraints}\n" if constraints else ""
    s3 = f"\n--- STAGE 3 (original idea, for reference) ---\n{stage3_output}\n--- END ---\n" if stage3_output else ""
    return f"""Turn this Stage-4 methodology into a Stage-5 experiment plan that an
autonomous code-writer and experiment-runner can execute without asking
questions. The Stage-5 document SUPERSEDES everything upstream — every
parameter it locks is final.
{cons}{s3}
--- STAGE 4 METHODOLOGY (the contract) ---
{stage4_methodology}
--- END STAGE 4 ---

Write `stage5_experiment_design.md` with EXACTLY these sections:

## 1. Experiment Overview
Restate the hypotheses verbatim and the decision rule for each.

## 2. Design matrix
Every (condition x benchmark/dataset x model) cell with exact
parameters: model path/name, decoding (temperature, max_tokens per
condition — EQUAL budgets unless a diagnostic arm says otherwise),
prompts per condition (verbatim system/user templates), dataset name +
split + exact n. Real datasets only — no synthetic stand-ins unless the
idea is about synthetic data.

## 3. Randomisation and seeds
Stochastic decoding => >= 3 seeds (list them) and report median + IQR.
Greedy/deterministic => single run is acceptable ONLY with a one-line
justification stating determinism.

## 4. Power / sample size
MDE at the pre-registered effect threshold, the n that achieves it, and
what is sacrificed if the budget caps n.

## 5. Locked statistical analysis
The exact tests from Stage 4 §4 mapped onto the design cells, with the
CI method named. No new tests may be added downstream (no HARKing).

## 6. Smoke contract
A `--smoke` mode: same code path, same output schema, first K items
(state K), wall-clock <= 5 min. State the exact smoke command and the
expected RESULT_JSON keys (the driver must print one final
`=== RESULT_JSON: {{...}} ===` line; include extraction-yield and
truncation-rate keys per condition).

## 7. Execution environment
State required packages (pinned), whether GPU is required, and the
environment-first rule: the environment must be VERIFIED (probe every
top-level import) or BUILT (fresh venv from pinned requirements) BEFORE
any experiment run. Batch-first: the full (item x condition x seed)
grid is submitted as batched inference / vectorised execution — a
per-item model-call loop is forbidden.

## 8. Assignments
A table: | # | Task | Skill (code_implementer / experiment_runner /
result_analyst / paper_writer) | Acceptance criterion |. Acceptance
criteria must be mechanically checkable (file exists, run_id terminal,
n complete, yield >= threshold).

## 9. Codebase pin
EITHER pin a real public upstream:
- Repository: <github url>
- Commit: MUST be copied from real `git ls-remote` output — NEVER from
  memory and NEVER from an example
- Verification: state that the consumer MUST run
  `git ls-remote <url> HEAD` and `git ls-tree -r --name-only <sha>`
  and paste both outputs here before implementation starts; every
  adaptation-surface file must appear in the ls-tree output
- Adaptation surface: file-by-file table with LOC estimates
OR write exactly `NO USABLE UPSTREAM FOUND.` with one sentence why,
which routes the implementer to the from-scratch path (single driver +
pinned requirements.txt).

Never invent repository names, file paths, or commit SHAs."""
