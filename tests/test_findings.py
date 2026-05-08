"""Unit tests for findings parsing and scoring."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from findings import (  # noqa: E402
    Finding,
    TruthDefect,
    match_finding_to_truth,
    parse_findings,
    score,
)


class TestParseFindings(unittest.TestCase):
    def test_extracts_critical_and_serious(self):
        report = """\
# Findings — claude

## Critical

- file: users.py:9
  severity: critical
  description: SQL injection via f-string in get_user_by_username
  quote: |
    query = f"SELECT * FROM users WHERE id = '{uid}'"

## Serious

- file: cache.py:14
  severity: serious
  description: file handle leak on exception path
"""
        findings = parse_findings(report)
        sev = [f.severity for f in findings]
        self.assertIn("critical", sev)
        self.assertIn("serious", sev)
        self.assertEqual(len(findings), 2)
        critical = next(f for f in findings if f.severity == "critical")
        self.assertEqual(critical.file, "users.py")
        self.assertEqual(critical.line, 9)

    def test_empty_section_produces_no_findings(self):
        report = """\
# Findings

## Critical

(none)

## Serious

(none)

## Minor

- some style nit
"""
        findings = parse_findings(report)
        self.assertEqual(len([f for f in findings if f.severity == "critical"]), 0)
        self.assertEqual(len([f for f in findings if f.severity == "serious"]), 0)
        # minor still parses
        minors = [f for f in findings if f.severity == "minor"]
        self.assertEqual(len(minors), 1)

    def test_handles_dropped_section_without_eating_findings(self):
        report = """\
# MMAR Final Findings

## Critical

- file: users.py:9
  description: SQL injection

## Serious

(none)

## Minor

(none)

## Dropped (hallucination filter)

- finding_ref: users.py:18 from gemini
  reason: cited code uses parameter binding correctly
"""
        findings = parse_findings(report)
        # only critical at users.py:9 should be a real finding
        crit = [f for f in findings if f.severity == "critical"]
        self.assertEqual(len(crit), 1)
        self.assertEqual(crit[0].file, "users.py")
        self.assertEqual(crit[0].line, 9)


class TestMatch(unittest.TestCase):
    def test_basename_match(self):
        f = Finding(
            severity="critical",
            file="evals/fixtures/001/input/users.py",
            line=9,
            description="sql injection via f-string",
        )
        t = TruthDefect(
            severity="critical",
            file="users.py",
            line=9,
            category="sql-injection",
            keywords=["sql", "injection"],
        )
        self.assertTrue(match_finding_to_truth(f, t))

    def test_line_within_tolerance(self):
        t = TruthDefect(
            severity="serious",
            file="window.py",
            line=13,
            category="off-by-one",
            keywords=["off", "range"],
        )
        for delta in (-5, -1, 0, 1, 5):
            f = Finding(
                severity="serious",
                file="window.py",
                line=13 + delta,
                description="off-by-one in range expression",
            )
            self.assertTrue(match_finding_to_truth(f, t), f"delta={delta}")

    def test_line_outside_tolerance(self):
        t = TruthDefect(
            severity="serious",
            file="window.py",
            line=13,
            category="off-by-one",
            keywords=["off", "range"],
        )
        f = Finding(
            severity="serious",
            file="window.py",
            line=50,
            description="off-by-one in range expression",
        )
        self.assertFalse(match_finding_to_truth(f, t))

    def test_keyword_required(self):
        t = TruthDefect(
            severity="critical",
            file="users.py",
            line=9,
            category="sql-injection",
            keywords=["sql", "injection"],
        )
        f = Finding(
            severity="critical",
            file="users.py",
            line=9,
            description="this function looks weird",
        )
        # no keyword overlap → not a match
        self.assertFalse(match_finding_to_truth(f, t))


class TestScore(unittest.TestCase):
    def test_perfect_recall_and_precision(self):
        truth = [
            TruthDefect(
                severity="critical",
                file="users.py",
                line=9,
                category="sql-injection",
                keywords=["sql", "injection"],
            )
        ]
        findings = [
            Finding(
                severity="critical",
                file="users.py",
                line=9,
                description="SQL injection via f-string",
            )
        ]
        out = score(findings, truth)
        self.assertEqual(out["tp"], 1)
        self.assertEqual(out["fp"], 0)
        self.assertEqual(out["fn"], 0)
        self.assertEqual(out["recall"], 1.0)
        self.assertEqual(out["precision"], 1.0)

    def test_false_positive_lowers_precision(self):
        truth = [
            TruthDefect(
                severity="critical",
                file="users.py",
                line=9,
                category="sql-injection",
                keywords=["sql", "injection"],
            )
        ]
        findings = [
            Finding(
                severity="critical",
                file="users.py",
                line=9,
                description="SQL injection",
            ),
            Finding(
                severity="critical",
                file="other.py",
                line=2,
                description="speculative concern about size",
            ),
        ]
        out = score(findings, truth)
        self.assertEqual(out["tp"], 1)
        self.assertEqual(out["fp"], 1)
        self.assertAlmostEqual(out["precision"], 0.5)
        self.assertEqual(out["recall"], 1.0)

    def test_missed_truth_lowers_recall(self):
        truth = [
            TruthDefect(
                severity="critical",
                file="a.py",
                line=10,
                category="x",
                keywords=["foo"],
            ),
            TruthDefect(
                severity="serious",
                file="b.py",
                line=20,
                category="y",
                keywords=["bar"],
            ),
        ]
        findings = [
            Finding(
                severity="critical",
                file="a.py",
                line=10,
                description="found foo",
            )
        ]
        out = score(findings, truth)
        self.assertEqual(out["tp"], 1)
        self.assertEqual(out["fn"], 1)
        self.assertAlmostEqual(out["recall"], 0.5)
        self.assertEqual(out["precision"], 1.0)

    def test_negative_case_no_truth_no_findings(self):
        out = score([], [])
        self.assertEqual(out["tp"], 0)
        self.assertEqual(out["fp"], 0)
        self.assertEqual(out["fn"], 0)
        # recall is technically 1.0 when there's nothing to find
        self.assertEqual(out["recall"], 1.0)


if __name__ == "__main__":
    unittest.main()
