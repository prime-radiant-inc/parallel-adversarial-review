# MMAR Eval Suite

Measures recall and precision of the multi-model adversarial review pipeline against fixtures with planted defects.

## Run

```bash
# Cheap, deterministic, CI-safe — uses pre-recorded mock responses
./runner.py --mode mock

# Real — actually invokes installed CLIs, costs $$
./runner.py --mode live
```

## Fixture Layout

```
fixtures/
  <fixture-id>/
    input/                # the code under review
      <files...>
    truth.json            # ground-truth planted defects
    mocks/                # pre-recorded responses for --mode mock
      stage1/
        claude.txt
        codex.txt
        gemini.txt
      stage2/
        <critic>__on__<reviewed>.txt
      stage3/
        synthesizer.txt
```

## truth.json schema

```json
{
  "description": "human-readable summary of the fixture",
  "defects": [
    {
      "file": "path/relative/to/input/source.py",
      "line": 42,
      "severity": "critical",
      "category": "sql-injection",
      "keywords": ["sql", "injection", "f-string", "execute"],
      "description": "user input concatenated into SQL via f-string"
    }
  ]
}
```

`category` and `description` are documentation; `file`, `line`, and `keywords` are what the matcher uses.

## Score interpretation

- **recall** = (planted defects found in final report) / (total planted defects). Higher is better.
- **precision** = (final report findings that match a planted defect) / (total final report findings). Higher is better.
- **F1** = harmonic mean.
- **negative-case fixtures** (zero planted defects) score precision = 1.0 if report is empty, 0.0 otherwise. Recall is N/A.

A fixture passes if: `recall >= recall_threshold` and `precision >= precision_threshold` (defaults 0.8 and 0.7). The runner prints per-fixture and aggregate results.

## Adding A Fixture

1. Create `fixtures/<id>/input/` with the code.
2. Write `fixtures/<id>/truth.json` with the planted defects.
3. Generate or hand-write `mocks/` for `--mode mock`. Synthesis output is what's scored; stage1/stage2 just need to exist.
4. Run `./runner.py --mode mock --only <id>` to verify.

## Regression discipline

If you change the wrappers, the synthesizer prompt, or the scoring logic, re-run the full eval suite. A drop in aggregate F1 is a blocker for merge.
