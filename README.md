# parallel-adversarial-review

Two skills for adversarial code review, plus an eval suite.

## What's in here

### `skills/parallel-adversarial-review/`

The original PAR pattern, ported from `iterative-development`. Two same-model reviewer subagents run in parallel under a competitive scoring frame; their findings are aggregated, with the worst severity winning on disagreement.

Use this for routine review.

### `skills/multi-model-adversarial-review/` (MMAR)

A three-stage pipeline that uses multiple installed coding-agent CLIs as independent reviewers, then runs a cross-critique grid where each reviewer evaluates the others' findings (catching hallucinations and severity inflation), then synthesizes a final deduplicated report.

```
Stage 1: parallel reviews   (each CLI reviews independently)
Stage 2: cross-critique     (each CLI verifies other CLIs' findings)
Stage 3: synthesis          (one model merges everything, applies rules)
```

Use this for high-stakes review (security, pre-merge on hot-path code, audits). Costs more.

The driver is `scripts/mmar.py`. CLI invocations are configured in `scripts/adapters.toml` so flags can be fixed when CLIs change without touching code.

```
$ python3 scripts/mmar.py list
amp       DISABLED  installed   amp
claude    ENABLED   installed   claude
codex     ENABLED   installed   codex
droid     DISABLED  installed   droid
gemini    ENABLED   installed   gemini
opencode  ENABLED   installed   opencode
pi        ENABLED   installed   pi

$ python3 scripts/mmar.py review path/to/diff_or_file_or_dir \
    --reviewers claude,codex,gemini \
    --out ./.mmar/run-1
```

**Default-on tier:** `claude`, `codex`, `gemini`, `pi`, `opencode` — enabled if installed.

**Opt-in tier (enabled=false by default):** `amp` and `droid` (Factory). Flip to `enabled=true` in `adapters.toml` after configuring credentials (`amp login` / Factory account).

For evals/CI, replace live CLI invocations with pre-recorded responses:

```
$ python3 scripts/mmar.py review evals/fixtures/001-sql-injection/input \
    --reviewers claude,codex,gemini \
    --mock-dir evals/fixtures/001-sql-injection/mocks \
    --out /tmp/mmar-run
```

## Eval suite

Fixture-based eval that scores recall and precision against planted defects.

```
$ python3 evals/runner.py --mode mock        # cheap, deterministic, CI-safe
$ python3 evals/runner.py --mode live        # real CLIs, costs $$
```

Current fixtures:

- `001-sql-injection` — classic f-string SQLi, with a parameter-bound query nearby that one reviewer hallucinates as also injectable (cross-critique drops it)
- `002-off-by-one` — windowed_sum loop overruns by one; mocks include a critic-driven severity downgrade
- `003-clean` — negative case, no defects; tests false-positive rate (one reviewer hallucinates a generic "could be passed a large string" worry, critics drop it)
- `004-resource-leak` — file handle leaked on exception path; gemini's mock misses it as a serious issue, aggregation still surfaces it

Pass thresholds: recall ≥ 0.8, precision ≥ 0.7. Negative-case fixtures pass iff zero false positives.

```
$ python3 evals/runner.py --mode mock
fixture                       truth  found   tp   fp   fn   prec    rec     F1  result
-----------------------------------------------------------------------------------------------
001-sql-injection                 1      1    1    0    0   1.00   1.00   1.00  PASS
002-off-by-one                    1      1    1    0    0   1.00   1.00   1.00  PASS
003-clean                         0      0    0    0    0   1.00   1.00   1.00  PASS
004-resource-leak                 1      1    1    0    0   1.00   1.00   1.00  PASS

aggregate (positive cases): precision=1.00  recall=1.00  f1=1.00
passed: 4/4
```

## Tests

```
$ python3 -m unittest discover -s tests
```

15 unit tests covering finding parsing, truth matching, and adapter loading/mock invocation.

## Adding a CLI

Edit `scripts/adapters.toml`:

```toml
[my-new-cli]
enabled = true
binary = "my-new-cli"
argv = ["--print"]
prompt_via = "argv"      # or "stdin", or "argv-after-flag"
prompt_flag = "--prompt" # only with argv-after-flag
timeout_sec = 300
notes = "..."
```

The driver picks it up on the next run.

## Adding a fixture

```
evals/fixtures/<id>/
  input/<files>            # code under review
  truth.json               # planted defects (see evals/README.md schema)
  mocks/
    stage1/<reviewer>.txt
    stage2/<critic>__on__<reviewed>.txt
    stage3/synthesizer.txt
```

For `--mode mock` you only really need a realistic `stage3/synthesizer.txt` for scoring; stage1/stage2 just need to exist so the driver runs through.

## Layout

```
.claude-plugin/plugin.json
skills/
  parallel-adversarial-review/SKILL.md, reviewer-wrapper.md
  multi-model-adversarial-review/SKILL.md, reviewer-wrapper.md, critic-wrapper.md, synthesizer-prompt.md
scripts/
  mmar.py            # driver
  adapters.py        # CLI invocation
  adapters.toml      # CLI config
  findings.py        # parsing + scoring
evals/
  runner.py
  fixtures/<id>/...
tests/
  test_findings.py
  test_adapters.py
```
