# parallel-adversarial-review

> Two skills for adversarial code review (single-model PAR and multi-model MMAR with cross-critique to catch hallucinations) plus a fixture-based eval suite.

**Family:** superpowers · **Type:** tool · **Lifecycle:** experimental · **Owner:** unknown (anonymous commits by Jesse Vincent; no GitHub login on contributors API)

## What it does
parallel-adversarial-review dispatches two same-model reviewer subagents in parallel under a competitive scoring frame, aggregating findings and taking the worst severity on disagreement (ported from iterative-development). multi-model-adversarial-review (MMAR) extends this to N installed coding-agent CLIs with a three-stage pipeline: parallel reviews, a cross-critique grid where each reviewer verifies the others' findings, then synthesis into a deduplicated report. The driver is scripts/mmar.py with CLI invocations configured in adapters.toml. A fixture-based eval suite scores precision and recall against planted defects.

## How it fits
- Depends on: —
- Used by: —
- External: Coding-agent CLIs as reviewers: claude, codex, gemini, opencode, pi (default-on), amp, droid/Factory (opt-in). Distributed via a Claude Code marketplace.

## Runtime & data
- Runs: Installed as a Claude Code plugin/skills; mmar.py runs CLIs locally; eval runner supports mock mode for CI.
- Data in: Code diffs/files/dirs to review; fixtures.
- Data out: Deduplicated review findings; eval precision/recall scores.

<!-- Maintained by the maintaining-project-map skill. Do not hand-edit; regenerated. -->
