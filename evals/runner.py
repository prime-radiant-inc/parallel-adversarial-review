#!/usr/bin/env python3
"""Eval runner for MMAR.

For each fixture, runs the MMAR pipeline (in mock or live mode) and
scores the final findings.md against truth.json. Prints per-fixture and
aggregate metrics.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent
SCRIPTS = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from findings import TruthDefect, parse_findings, score  # noqa: E402

FIXTURES_DIR = HERE / "fixtures"

DEFAULT_RECALL_THRESHOLD = 0.8
DEFAULT_PRECISION_THRESHOLD = 0.7


@dataclass
class FixtureResult:
    fixture: str
    truth_count: int
    finding_count: int
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    passed: bool
    detail: dict


def load_truth(fixture: Path) -> tuple[str, list[TruthDefect]]:
    payload = json.loads((fixture / "truth.json").read_text())
    description = payload.get("description", "")
    defects = [
        TruthDefect(
            severity=d["severity"],
            file=d["file"],
            line=int(d["line"]),
            category=d.get("category", ""),
            keywords=list(d.get("keywords", [])),
            description=d.get("description", ""),
        )
        for d in payload.get("defects", [])
    ]
    return description, defects


def run_mmar(
    fixture: Path,
    mode: str,
    reviewers: str,
    workdir: Path,
) -> str:
    """Run mmar.py review on the fixture's input dir, return findings.md."""
    out_dir = workdir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(SCRIPTS / "mmar.py"),
        "review",
        str(fixture / "input"),
        "--reviewers",
        reviewers,
        "--out",
        str(out_dir),
        "--max-critiques",
        "2",
    ]
    if mode == "mock":
        cmd.extend(["--mock-dir", str(fixture / "mocks")])
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"mmar.py failed for {fixture.name} (exit {proc.returncode})")
    findings_md = out_dir / "findings.md"
    if not findings_md.exists():
        raise SystemExit(f"mmar.py did not produce findings.md for {fixture.name}")
    return findings_md.read_text()


def evaluate_fixture(
    fixture: Path,
    mode: str,
    reviewers: str,
    recall_threshold: float,
    precision_threshold: float,
) -> FixtureResult:
    _description, truth = load_truth(fixture)
    with tempfile.TemporaryDirectory() as tmp:
        report = run_mmar(fixture, mode, reviewers, Path(tmp))
    findings = parse_findings(report)
    # only critical and serious count for scoring; minor is informational
    scored_findings = [f for f in findings if f.severity in ("critical", "serious")]
    detail = score(scored_findings, truth)

    if not truth:
        # negative-case fixture — recall is N/A; we just need precision = 1
        # (zero false positives) for it to pass.
        passed = detail["fp"] == 0
        # Override precision in detail too: the score() function returns 0.0
        # when (tp + fp) == 0, but for a negative case we want to report
        # "no false positives" as precision 1.0.
        if detail["fp"] == 0:
            detail = {**detail, "precision": 1.0, "f1": 1.0}
        return FixtureResult(
            fixture=fixture.name,
            truth_count=0,
            finding_count=len(scored_findings),
            tp=detail["tp"],
            fp=detail["fp"],
            fn=detail["fn"],
            precision=1.0 if detail["fp"] == 0 else 0.0,
            recall=1.0,
            f1=1.0 if detail["fp"] == 0 else 0.0,
            passed=passed,
            detail=detail,
        )

    passed = (
        detail["recall"] >= recall_threshold
        and detail["precision"] >= precision_threshold
    )
    return FixtureResult(
        fixture=fixture.name,
        truth_count=len(truth),
        finding_count=len(scored_findings),
        tp=detail["tp"],
        fp=detail["fp"],
        fn=detail["fn"],
        precision=detail["precision"],
        recall=detail["recall"],
        f1=detail["f1"],
        passed=passed,
        detail=detail,
    )


def list_fixtures(only: list[str] | None) -> list[Path]:
    items = sorted(p for p in FIXTURES_DIR.iterdir() if p.is_dir())
    if only:
        wanted = set(only)
        items = [p for p in items if p.name in wanted]
    return items


def main() -> int:
    p = argparse.ArgumentParser(description="MMAR eval runner")
    p.add_argument("--mode", choices=["mock", "live"], default="mock")
    p.add_argument(
        "--reviewers",
        default="claude,codex,gemini",
        help="comma-separated CLI names (default: claude,codex,gemini)",
    )
    p.add_argument("--only", action="append", help="run only these fixture IDs")
    p.add_argument(
        "--recall-threshold", type=float, default=DEFAULT_RECALL_THRESHOLD
    )
    p.add_argument(
        "--precision-threshold", type=float, default=DEFAULT_PRECISION_THRESHOLD
    )
    p.add_argument("--json", action="store_true", help="emit JSON to stdout")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    fixtures = list_fixtures(args.only)
    if not fixtures:
        print("no fixtures found", file=sys.stderr)
        return 2

    results: list[FixtureResult] = []
    for fixture in fixtures:
        try:
            r = evaluate_fixture(
                fixture,
                args.mode,
                args.reviewers,
                args.recall_threshold,
                args.precision_threshold,
            )
        except SystemExit as e:
            print(f"FAIL  {fixture.name}: {e}", file=sys.stderr)
            results.append(
                FixtureResult(
                    fixture=fixture.name,
                    truth_count=0,
                    finding_count=0,
                    tp=0,
                    fp=0,
                    fn=0,
                    precision=0.0,
                    recall=0.0,
                    f1=0.0,
                    passed=False,
                    detail={"error": str(e)},
                )
            )
            continue
        results.append(r)

    if args.json:
        print(
            json.dumps(
                [
                    {**r.__dict__, "passed": bool(r.passed)} for r in results
                ],
                indent=2,
            )
        )
    else:
        print()
        print(
            f"{'fixture':<28}  {'truth':>5}  {'found':>5}  "
            f"{'tp':>3}  {'fp':>3}  {'fn':>3}  "
            f"{'prec':>5}  {'rec':>5}  {'F1':>5}  result"
        )
        print("-" * 95)
        for r in results:
            mark = "PASS" if r.passed else "FAIL"
            print(
                f"{r.fixture:<28}  {r.truth_count:>5}  {r.finding_count:>5}  "
                f"{r.tp:>3}  {r.fp:>3}  {r.fn:>3}  "
                f"{r.precision:>5.2f}  {r.recall:>5.2f}  {r.f1:>5.2f}  {mark}"
            )
        if args.verbose:
            for r in results:
                print(f"\n--- {r.fixture} detail ---")
                print(json.dumps(r.detail, indent=2))

        positive = [r for r in results if r.truth_count > 0]
        if positive:
            agg_p = sum(r.precision for r in positive) / len(positive)
            agg_r = sum(r.recall for r in positive) / len(positive)
            agg_f = sum(r.f1 for r in positive) / len(positive)
            print()
            print(
                f"aggregate (positive cases): "
                f"precision={agg_p:.2f}  recall={agg_r:.2f}  f1={agg_f:.2f}"
            )
        passed = sum(1 for r in results if r.passed)
        print(f"passed: {passed}/{len(results)}")

    failed = sum(1 for r in results if not r.passed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
