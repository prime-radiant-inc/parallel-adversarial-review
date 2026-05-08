---
name: multi-model-adversarial-review
description: Use for high-stakes review where you want multiple model providers reviewing the same artifact and critiquing each other. Shells out to installed coding-agent CLIs (claude, codex, gemini, opencode, amp, aider, cursor-agent) to run parallel reviews, then runs a cross-critique grid where each reviewer evaluates the others' findings to catch hallucinations and severity inflation, then synthesizes a final deduplicated report. Triggers on "MMAR review", "multi-model review", "cross-model adversarial", "review with all the models", or when single-model PAR feels insufficient.
---

# Multi-Model Adversarial Review (MMAR)

A three-stage review pipeline that uses multiple installed coding-agent CLIs as independent reviewers, then has them critique each other's findings, then synthesizes a final report. Catches model-specific blind spots and hallucinations that single-model PAR cannot.

## When To Use This vs. Plain PAR

| Situation | Use |
|---|---|
| Routine review, normal stakes | `parallel-adversarial-review` (faster, cheaper) |
| Pre-merge review on hot path code | MMAR |
| Security review | MMAR |
| Production incident postmortem code change | MMAR |
| You suspect a model has a blind spot for this kind of code | MMAR |
| Compliance / audit artifact | MMAR |

MMAR costs more (N+1 model invocations + cross-critique). Don't reach for it on every commit.

## Pipeline

```
                Stage 1: Parallel Reviews
                ┌──────────────┬──────────────┬──────────────┐
   diff ──────► │   claude     │    codex     │    gemini    │ ───► findings_<model>.md
                └──────┬───────┴──────┬───────┴──────┬───────┘
                       │              │              │
                Stage 2: Cross-Critique (NxN-1 grid)
                ┌──────────────┬──────────────┬──────────────┐
                │ codex critiq │ gemini critiq│ codex critiq │
                │ of claude    │ of claude    │ of gemini    │ ───► critique_<a>_of_<b>.md
                │ ...                                        │
                └──────┬───────┴──────┬───────┴──────┬───────┘
                       │              │              │
                Stage 3: Synthesis
                ┌──────────────────────────────────────────────┐
                │  synthesizer (Claude as subagent or CLI)     │
                │  - dedupe across reviewers                   │
                │  - drop hallucinations flagged by critics    │
                │  - apply severity-disagreement rule          │
                │  - produce final findings report             │
                └──────────────────────────────────────────────┘
```

## How To Run It

You do not call CLIs by hand. Run the driver:

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/mmar.py review <diff_path_or_- > [options]
```

Options:
- `--reviewers claude,codex,gemini` — which CLIs to use (default: auto-detect)
- `--workdir <dir>` — repo to run reviewers in (default: cwd)
- `--out <dir>` — where to write per-stage artifacts (default: `./.mmar/<timestamp>/`)
- `--mock-dir <dir>` — read pre-recorded responses from `<dir>/<stage>/<reviewer>.txt` instead of calling CLIs (for evals and CI)
- `--skip-critique` — stage 1 + stage 3 only, no cross-critique (degrades to multi-model PAR)
- `--domain-prompt <file>` — path to a file with the domain-specific reviewer instructions (e.g. "review for security bugs"); defaults to a generic code-quality prompt

The driver writes per-stage artifacts and a final `findings.md` in the output directory. Read it. Pass it to the implementer or whoever owns the next stage.

## Adapter Configuration

CLI invocations are defined in `scripts/adapters.toml`. Each entry maps a CLI name to a command template. To add a new CLI or fix an invocation that broke (CLIs change their flags), edit that file. The driver reads it on every run.

If a CLI is not installed, it is silently skipped. The driver requires at least 2 reviewers to proceed; with 1 it errors and tells you to install another or use plain PAR.

## Wrapper Prompts

Stage 1 reviewers get the prompt in `reviewer-wrapper.md`. Stage 2 critics get the prompt in `critic-wrapper.md`. Stage 3 synthesis uses `synthesizer-prompt.md`. The driver assembles these from the diff and findings; you do not invoke them directly.

## Aggregation Rules

The synthesizer applies:

1. **Dedupe**: findings within ±3 lines on the same file with overlapping description keywords collapse to one.
2. **Hallucination filter**: if a critic explicitly flags a finding as "fabricated" or "the cited code does not exist / does not say what reviewer claims", drop it from the final report. (Critics are instructed to verify file:line and quoted code.)
3. **Severity escalation**: on disagreement, take the worst severity. Same rule as plain PAR.
4. **Confidence labeling**: a finding gets `[high]` if found by ≥2 reviewers and not flagged by any critic; `[medium]` if found by 1 reviewer and not flagged; `[low]` if found by 1 and partially flagged.

These rules are enforced by `synthesizer-prompt.md`. Do not negotiate with them.

## Failure Modes And What To Do

| Failure | Response |
|---|---|
| A reviewer CLI hangs | Driver has a per-CLI timeout (default 5 min). Kill that adapter; continue with the rest. |
| A reviewer returns empty/unparseable output | Treated as "no findings"; do not retry — that biases the result. |
| Cross-critique pairs balloon (6 reviewers → 30 critiques) | Driver caps critiques per reviewer at 3 random others. Configurable. |
| Cost concerns | Use `--reviewers` to pick fewer, or use plain PAR. |
| Network down | Run with `--mock-dir` over a recorded fixture, or use plain PAR with the local Claude session. |

## Eval Suite

The eval suite in `evals/` measures recall and precision against fixtures with planted defects. Run:

```bash
${CLAUDE_PLUGIN_ROOT}/evals/runner.py --mode mock      # cheap, deterministic, CI-safe
${CLAUDE_PLUGIN_ROOT}/evals/runner.py --mode live      # actually invokes CLIs (costs $$)
```

If you change the wrappers or synthesizer, re-run evals before merging. A regression on recall or precision is a blocker.

## See Also

- `reviewer-wrapper.md`, `critic-wrapper.md`, `synthesizer-prompt.md` — the prompts the driver uses.
- `parallel-adversarial-review` skill — single-model PAR for routine reviews.
- `scripts/adapters.toml` — how to add or fix a CLI invocation.
