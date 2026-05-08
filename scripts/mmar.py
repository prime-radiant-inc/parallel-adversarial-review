#!/usr/bin/env python3
"""MMAR driver: orchestrates multi-model adversarial review.

Stages:
  1. Parallel reviews — each enabled+installed CLI reviews the diff.
  2. Cross-critique  — each reviewer critiques each other reviewer's findings
     (capped at --max-critiques per reviewer).
  3. Synthesis       — one final pass merges everything into findings.md.

Output structure:
  <out>/
    stage1/<reviewer>.md
    stage2/<critic>__on__<reviewed>.md
    stage3/synthesis.md
    findings.md           # final report (== stage3/synthesis.md)
    run.json              # metadata: reviewers used, durations, errors

For evals/CI, pass --mock-dir <dir>. The driver reads stage1 outputs from
<dir>/stage1/<reviewer>.txt etc instead of running CLIs.
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import os
import random
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from adapters import Adapter, available, invoke, load_adapters  # noqa: E402

SKILL_DIR = PLUGIN_ROOT / "skills" / "multi-model-adversarial-review"


def read_template(name: str) -> str:
    return (SKILL_DIR / name).read_text()


def build_reviewer_prompt(
    reviewer_name: str,
    n_reviewers: int,
    domain_prompt: str,
    review_target: str,
) -> str:
    tpl = read_template("reviewer-wrapper.md")
    body = _extract_code_block(tpl)
    return (
        body.replace("{REVIEWER_NAME}", reviewer_name)
        .replace("{N_REVIEWERS}", str(n_reviewers))
        .replace("{DOMAIN_PROMPT}", domain_prompt)
        .replace("{REVIEW_TARGET}", review_target)
    )


def build_critic_prompt(
    critic_name: str,
    reviewed_name: str,
    review_target: str,
    reviewed_findings: str,
) -> str:
    tpl = read_template("critic-wrapper.md")
    body = _extract_code_block(tpl)
    return (
        body.replace("{CRITIC_NAME}", critic_name)
        .replace("{REVIEWED_NAME}", reviewed_name)
        .replace("{REVIEW_TARGET}", review_target)
        .replace("{REVIEWED_FINDINGS}", reviewed_findings)
    )


def build_synth_prompt(
    n_reviewers: int,
    review_target: str,
    all_reviews: str,
    all_critiques: str,
) -> str:
    tpl = read_template("synthesizer-prompt.md")
    body = _extract_code_block(tpl)
    return (
        body.replace("{N_REVIEWERS}", str(n_reviewers))
        .replace("{REVIEW_TARGET}", review_target)
        .replace("{ALL_REVIEWS}", all_reviews)
        .replace("{ALL_CRITIQUES}", all_critiques)
    )


def _extract_code_block(markdown: str) -> str:
    """Pull the first fenced ``` block from the wrapper file."""
    lines = markdown.splitlines()
    in_block = False
    out: list[str] = []
    for ln in lines:
        if ln.strip().startswith("```"):
            if in_block:
                return "\n".join(out)
            in_block = True
            continue
        if in_block:
            out.append(ln)
    return markdown  # fallback if no block found


DEFAULT_DOMAIN_PROMPT = """\
Review the code for real defects: incorrect behavior, security holes,
data loss, race conditions, resource leaks, missing error handling at
trust boundaries, and spec violations. Do not flag style or naming.
Cite file:line and quote ≤5 lines for each finding."""


def stage1_parallel_reviews(
    adapters_to_use: dict[str, Adapter],
    review_target: str,
    domain_prompt: str,
    workdir: Path,
    out_dir: Path,
    mock_dir: Path | None,
) -> dict[str, dict]:
    """Run all reviewers in parallel. Returns {name: {ok, stdout, ...}}."""
    stage_out = out_dir / "stage1"
    stage_out.mkdir(parents=True, exist_ok=True)
    n = len(adapters_to_use)
    mock_stage = (mock_dir / "stage1") if mock_dir else None

    def run_one(name: str, a: Adapter) -> tuple[str, dict]:
        prompt = build_reviewer_prompt(name, n, domain_prompt, review_target)
        result = invoke(a, prompt, workdir, mock_stage)
        (stage_out / f"{name}.md").write_text(result.stdout)
        if result.stderr:
            (stage_out / f"{name}.stderr.log").write_text(result.stderr)
        return name, {
            "ok": result.ok,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_sec": result.duration_sec,
            "error": result.error,
        }

    results: dict[str, dict] = {}
    with futures.ThreadPoolExecutor(max_workers=max(1, n)) as ex:
        future_map = {
            ex.submit(run_one, name, a): name for name, a in adapters_to_use.items()
        }
        for fut in futures.as_completed(future_map):
            name, payload = fut.result()
            results[name] = payload
    return results


def stage2_cross_critique(
    adapters_to_use: dict[str, Adapter],
    stage1_results: dict[str, dict],
    review_target: str,
    workdir: Path,
    out_dir: Path,
    mock_dir: Path | None,
    max_critiques_per_reviewer: int,
) -> dict[str, dict]:
    """For each (critic, reviewed) pair, have critic verify reviewed's findings.

    Caps at max_critiques_per_reviewer per critic to keep cost bounded.
    """
    stage_out = out_dir / "stage2"
    stage_out.mkdir(parents=True, exist_ok=True)
    mock_stage = (mock_dir / "stage2") if mock_dir else None

    pairs: list[tuple[str, str]] = []
    names = list(adapters_to_use.keys())
    rng = random.Random(0xC0FFEE)
    for critic in names:
        others = [n for n in names if n != critic]
        rng.shuffle(others)
        for reviewed in others[:max_critiques_per_reviewer]:
            pairs.append((critic, reviewed))

    def run_one(critic: str, reviewed: str) -> tuple[str, dict]:
        reviewed_findings = stage1_results.get(reviewed, {}).get("stdout", "")
        if not reviewed_findings.strip():
            payload = {
                "ok": True,
                "stdout": (
                    f"# Critique — {critic} on {reviewed}\n"
                    "(no findings to critique)\n"
                ),
                "stderr": "",
                "duration_sec": 0.0,
                "error": None,
            }
            (stage_out / f"{critic}__on__{reviewed}.md").write_text(payload["stdout"])
            return f"{critic}__on__{reviewed}", payload

        prompt = build_critic_prompt(critic, reviewed, review_target, reviewed_findings)
        a = adapters_to_use[critic]
        # mock_stage uses one file per pair: <critic>__on__<reviewed>.txt
        mock_pair_dir = None
        if mock_stage is not None:
            # synthesize a dir-of-one to reuse invoke()'s mock lookup
            mock_pair_dir = mock_stage
            # we need the file lookup name to be "<critic>__on__<reviewed>"
            pair_adapter = Adapter(
                name=f"{critic}__on__{reviewed}",
                enabled=a.enabled,
                binary=a.binary,
                argv=a.argv,
                prompt_via=a.prompt_via,
                prompt_flag=a.prompt_flag,
                timeout_sec=a.timeout_sec,
                notes=a.notes,
            )
            result = invoke(pair_adapter, prompt, workdir, mock_pair_dir)
        else:
            result = invoke(a, prompt, workdir, None)

        (stage_out / f"{critic}__on__{reviewed}.md").write_text(result.stdout)
        if result.stderr:
            (stage_out / f"{critic}__on__{reviewed}.stderr.log").write_text(
                result.stderr
            )
        return f"{critic}__on__{reviewed}", {
            "ok": result.ok,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_sec": result.duration_sec,
            "error": result.error,
        }

    results: dict[str, dict] = {}
    with futures.ThreadPoolExecutor(max_workers=max(1, len(pairs))) as ex:
        future_map = {ex.submit(run_one, c, r): (c, r) for c, r in pairs}
        for fut in futures.as_completed(future_map):
            key, payload = fut.result()
            results[key] = payload
    return results


def stage3_synthesize(
    synthesizer_name: str,
    adapters_to_use: dict[str, Adapter],
    stage1_results: dict[str, dict],
    stage2_results: dict[str, dict],
    review_target: str,
    workdir: Path,
    out_dir: Path,
    mock_dir: Path | None,
) -> str:
    stage_out = out_dir / "stage3"
    stage_out.mkdir(parents=True, exist_ok=True)
    mock_stage = (mock_dir / "stage3") if mock_dir else None

    all_reviews = "\n\n".join(
        f"### Reviewer: {n}\n\n{r['stdout']}"
        for n, r in sorted(stage1_results.items())
    )
    all_critiques = "\n\n".join(
        f"### {key}\n\n{r['stdout']}" for key, r in sorted(stage2_results.items())
    )
    n_reviewers = len(stage1_results)
    prompt = build_synth_prompt(n_reviewers, review_target, all_reviews, all_critiques)

    a = adapters_to_use[synthesizer_name]
    # mock lookup for synthesis: <mock_dir>/stage3/synthesizer.txt
    if mock_stage is not None:
        synth_adapter = Adapter(
            name="synthesizer",
            enabled=a.enabled,
            binary=a.binary,
            argv=a.argv,
            prompt_via=a.prompt_via,
            prompt_flag=a.prompt_flag,
            timeout_sec=a.timeout_sec,
            notes=a.notes,
        )
        result = invoke(synth_adapter, prompt, workdir, mock_stage)
    else:
        result = invoke(a, prompt, workdir, None)

    (stage_out / "synthesis.md").write_text(result.stdout)
    if result.stderr:
        (stage_out / "synthesis.stderr.log").write_text(result.stderr)
    (out_dir / "findings.md").write_text(result.stdout)
    return result.stdout


def review_target_from_path(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    p = Path(path)
    if p.is_file():
        return p.read_text()
    if p.is_dir():
        # produce a flat dump of the directory
        out: list[str] = []
        for f in sorted(p.rglob("*")):
            if f.is_file() and not _is_ignored(f):
                rel = f.relative_to(p)
                out.append(f"=== {rel} ===\n{f.read_text(errors='replace')}\n")
        return "\n".join(out)
    raise SystemExit(f"review target not found: {path}")


def _is_ignored(p: Path) -> bool:
    parts = set(p.parts)
    return bool(parts & {".git", "__pycache__", "node_modules", ".venv"})


def cmd_review(args: argparse.Namespace) -> int:
    adapters = load_adapters()

    if args.reviewers:
        wanted = [n.strip() for n in args.reviewers.split(",") if n.strip()]
        missing = [n for n in wanted if n not in adapters]
        if missing:
            print(f"unknown reviewers: {missing}", file=sys.stderr)
            return 2
        adapters_to_use = {n: adapters[n] for n in wanted}
    else:
        adapters_to_use = {n: adapters[n] for n in available(adapters)}

    if args.mock_dir is None and len(adapters_to_use) < 2:
        print(
            "MMAR needs ≥2 reviewers. Available: "
            + (", ".join(adapters_to_use) or "(none)"),
            file=sys.stderr,
        )
        print("Install another CLI, enable one in adapters.toml, or use plain PAR.")
        return 2

    workdir = Path(args.workdir).resolve() if args.workdir else Path.cwd()
    review_target = review_target_from_path(args.target)
    domain_prompt = (
        Path(args.domain_prompt).read_text()
        if args.domain_prompt
        else DEFAULT_DOMAIN_PROMPT
    )

    if args.out:
        out_dir = Path(args.out)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = Path.cwd() / ".mmar" / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    mock_dir = Path(args.mock_dir).resolve() if args.mock_dir else None

    print(f"reviewers: {sorted(adapters_to_use)}", file=sys.stderr)
    print(f"output:    {out_dir}", file=sys.stderr)
    if mock_dir:
        print(f"mock-dir:  {mock_dir}", file=sys.stderr)

    t0 = time.monotonic()
    stage1 = stage1_parallel_reviews(
        adapters_to_use, review_target, domain_prompt, workdir, out_dir, mock_dir
    )
    print(
        f"stage1 done in {time.monotonic() - t0:.1f}s "
        f"({sum(1 for r in stage1.values() if r['ok'])}/{len(stage1)} ok)",
        file=sys.stderr,
    )

    if args.skip_critique:
        stage2: dict[str, dict] = {}
    else:
        t1 = time.monotonic()
        stage2 = stage2_cross_critique(
            adapters_to_use,
            stage1,
            review_target,
            workdir,
            out_dir,
            mock_dir,
            args.max_critiques,
        )
        print(
            f"stage2 done in {time.monotonic() - t1:.1f}s "
            f"({sum(1 for r in stage2.values() if r['ok'])}/{len(stage2)} ok)",
            file=sys.stderr,
        )

    synth_name = args.synthesizer
    if synth_name not in adapters_to_use:
        synth_name = next(iter(adapters_to_use))
    t2 = time.monotonic()
    stage3_text = stage3_synthesize(
        synth_name,
        adapters_to_use,
        stage1,
        stage2,
        review_target,
        workdir,
        out_dir,
        mock_dir,
    )
    print(f"stage3 done in {time.monotonic() - t2:.1f}s", file=sys.stderr)

    run_meta = {
        "out_dir": str(out_dir),
        "reviewers": sorted(adapters_to_use),
        "synthesizer": synth_name,
        "mock_dir": str(mock_dir) if mock_dir else None,
        "stage1": {n: {k: v for k, v in r.items() if k != "stdout"} for n, r in stage1.items()},
        "stage2": {n: {k: v for k, v in r.items() if k != "stdout"} for n, r in stage2.items()},
        "wall_clock_sec": time.monotonic() - t0,
    }
    (out_dir / "run.json").write_text(json.dumps(run_meta, indent=2))

    print(f"\n=== final findings ({out_dir}/findings.md) ===\n")
    print(stage3_text)
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    adapters = load_adapters()
    width = max(len(n) for n in adapters)
    for name, a in sorted(adapters.items()):
        status = "ENABLED" if a.enabled else "DISABLED"
        installed = "installed" if a.installed else "MISSING"
        print(f"{name:<{width}}  {status:<8}  {installed:<10}  {a.binary}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="mmar.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("review", help="run MMAR pipeline")
    pr.add_argument("target", help="path to file/dir/diff, or '-' for stdin")
    pr.add_argument("--reviewers", help="comma-separated CLI names")
    pr.add_argument("--workdir", help="repo root for reviewer cwd")
    pr.add_argument("--out", help="output dir (default ./.mmar/<ts>/)")
    pr.add_argument("--mock-dir", help="read pre-recorded responses from here")
    pr.add_argument("--skip-critique", action="store_true")
    pr.add_argument("--max-critiques", type=int, default=3)
    pr.add_argument("--synthesizer", default="claude")
    pr.add_argument("--domain-prompt", help="path to domain-specific instructions")
    pr.set_defaults(func=cmd_review)

    pl = sub.add_parser("list", help="list configured CLIs")
    pl.set_defaults(func=cmd_list)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
