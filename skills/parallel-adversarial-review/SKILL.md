---
name: parallel-adversarial-review
description: Use when reviewing a diff, commit, branch, or implementation against a spec — dispatches two same-model reviewer subagents in parallel under a competitive scoring frame, then aggregates findings. Triggers on "review this", "PAR review", "adversarial review", or any evaluative gate (scope review, spec compliance, code quality, audit).
---

# Parallel Adversarial Review (PAR)

Two reviewers, same model, identical inputs, run in parallel. They never see each other. A competitive scoring frame in the prompt pressures thoroughness. After both return, aggregate findings and take the worst severity on disagreement. No thresholds. No negotiation.

## When To Use

Any evaluative gate. If you are about to "review" or "audit" something, use PAR. Do not roll your own review.

| Gate | Reviewer role |
|---|---|
| Pre-iteration scope review | Scope reviewer |
| Per-task spec compliance | Spec-compliance reviewer |
| Per-task code quality | Code-quality reviewer |
| Per-sprint audit | Auditor |
| PR / branch review | Code reviewer |

PAR is always-on. There is no opt-out. If you find yourself wanting to skip the second reviewer "to save time", you are wrong.

## The Pattern

1. **Dispatch TWO reviewer subagents simultaneously** with identical inputs. Use your platform's parallel dispatch (the `Agent` tool, or equivalent). Neither reviewer sees the other's work.

2. **Wrap each reviewer's prompt** with the competitive framing in `reviewer-wrapper.md`. The wrapper adds the scoring incentive on top of your domain-specific reviewer instructions.

3. **Wait for both reviewers to return.** Do not start aggregating until you have both reports.

4. **Aggregate findings:**
   - Same issue found by both reviewers → one finding, high confidence.
   - Issue found by only one reviewer → separate finding, lower confidence but still actionable. Do not drop it.
   - Severity disagreement (A says "critical", B says "minor") → always take the more severe assessment, always fix it. No threshold, no escalation, no negotiation.

5. **Pass aggregated findings to the next stage** (the implementer, the roadmap author for scope reviews, the backlog for audits).

6. **On re-review after fixes:** dispatch a fresh parallel adversarial pair. No state carries between review iterations.

## Key Rules

- **PAR is always-on.** Every evaluative gate uses paired reviewers.
- **The scoring is psychological.** The "5 points" framing is a prompt-level trick to pressure thoroughness. There is no actual point tracking, no scoreboard, no persistent state. Do not build scoring infrastructure.
- **Single model.** Both reviewers use the same model. For multi-model review, use the `multi-model-adversarial-review` skill instead.
- **Severity disagreement → take the worst, fix it.** No thresholds.
- **False positives are worse than misses for scoring purposes** — but that's the wrapper's job to communicate to the reviewer. You, the dispatcher, just aggregate everything they report.

## Single-Agent Fallback

If subagent dispatch is unavailable (session policy, runtime limits, or tool restrictions):

1. Perform the first review pass yourself, using the same domain-specific prompt.
2. Save the findings, then perform a second pass with the explicit instruction: "Find issues the first review missed. Score 5 points for each new finding."
3. Aggregate both passes as if they were parallel reviewers.
4. When reviewing code, use `git diff HEAD` AND `git ls-files --others --exclude-standard` to cover both tracked changes and new untracked files — `git diff` alone misses new files.

This fallback is weaker than true PAR (same model, sequential, no sampling variance) but maintains the adversarial structure. Use it only when parallel dispatch is genuinely impossible.

## Where PAR Does NOT Apply

- Implementer subagents (doers, not evaluators)
- Implementer self-review (internal discipline)
- Extraction subagents (reading spec, not reviewing)
- Aggregation (mechanical merge, not evaluative)

## Dispatch Recipe

```
Inputs you have:
  - DOMAIN_PROMPT: the domain-specific reviewer instructions (e.g., the
    spec-compliance reviewer prompt, or "review this PR for security bugs")
  - REVIEW_TARGET: the diff, file list, branch name, or other artifact to review

Steps:
  1. Read reviewer-wrapper.md (sibling file in this skill).
  2. Build prompt A: substitute [A] and DOMAIN_PROMPT into the wrapper.
  3. Build prompt B: substitute [B] and DOMAIN_PROMPT into the wrapper.
  4. Dispatch both subagents in a single tool-call batch (parallel).
     Descriptions: "PAR Review A: <short>", "PAR Review B: <short>".
  5. Collect both reports.
  6. Aggregate: dedupe identical findings, keep singletons, on severity
     disagreement take the worst.
  7. Output: a single combined findings report with severity buckets.
```

## See Also

- `reviewer-wrapper.md` — the competitive-framing wrapper to apply to every reviewer prompt.
- `multi-model-adversarial-review` skill — the fancier multi-CLI version with cross-critique.
