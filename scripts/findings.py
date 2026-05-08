"""Findings parsing and matching.

Reviewers emit markdown reports with severity headings. We parse those
into structured records, then match against ground truth or against each
other for dedupe.

Matching is fuzzy because model output won't match exact wording. A
finding matches a ground-truth defect if:
  - The cited file matches (basename comparison if path differs).
  - The cited line is within ±LINE_TOLERANCE of the truth line.
  - At least one keyword from the truth's keyword list appears in the
    finding's description (case-insensitive).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

LINE_TOLERANCE = 5

SEVERITIES = ("critical", "serious", "minor")


@dataclass
class Finding:
    severity: str
    file: str
    line: int | None
    description: str
    quote: str = ""
    raw: str = ""

    def keywords(self) -> set[str]:
        text = f"{self.description} {self.quote}".lower()
        return set(re.findall(r"[a-z][a-z_]{2,}", text))


@dataclass
class TruthDefect:
    """A planted defect in an eval fixture."""

    severity: str
    file: str
    line: int
    category: str
    keywords: list[str] = field(default_factory=list)
    description: str = ""


_HEADING_RE = re.compile(r"^\s*#{1,4}\s*(critical|serious|minor)\b", re.IGNORECASE)
# Match a file:line reference. Files come in two shapes:
#   1. dotted-suffix files (foo/bar.py, src/x.ts)
#   2. extensionless conventional names (Dockerfile, Makefile, Rakefile, ...)
# Both shapes followed by `:<digits>`.
_FILE_LINE_RE = re.compile(
    r"""
    (?:^|\s|`)
    (?P<file>
        # extensionless conventional names with optional path prefix
        (?: [\w./\-]+ / )?
        (?: Dockerfile | Makefile | Rakefile | Gemfile | Podfile
            | Procfile | Vagrantfile | Jenkinsfile | Brewfile
            | CMakeLists\.txt
        )
        |
        # dotted-suffix files
        [\w./\-]+? \. [a-zA-Z0-9]+
    )
    : (?P<line> \d+ )
    """,
    re.VERBOSE,
)
_BULLET_RE = re.compile(r"^\s*[-*]\s+")


def parse_findings(report: str) -> list[Finding]:
    """Parse a reviewer's markdown report into findings.

    Approach: find severity headings, then take all bullet items under each
    heading until the next heading. Each bullet is one finding. Extract the
    first file:line reference from the bullet's text.
    """
    lines = report.splitlines()
    findings: list[Finding] = []

    current_severity: str | None = None
    current_bullet: list[str] = []

    def flush_bullet() -> None:
        nonlocal current_bullet
        if not current_bullet or current_severity is None:
            current_bullet = []
            return
        text = "\n".join(current_bullet).strip()
        if not text:
            current_bullet = []
            return
        if text.lower() in ("(none)", "none", "n/a"):
            current_bullet = []
            return
        m = _FILE_LINE_RE.search(text)
        file = m.group("file") if m else ""
        line = int(m.group("line")) if m else None
        # quote: pull lines indented under the bullet that look like code
        quote_lines: list[str] = []
        in_quote = False
        for ln in current_bullet:
            stripped = ln.strip()
            if stripped.startswith("```") or stripped.startswith("quote:"):
                in_quote = True
                continue
            if in_quote and (ln.startswith("    ") or ln.startswith("\t")):
                quote_lines.append(ln.lstrip())
            elif in_quote and not stripped:
                continue
            elif in_quote:
                in_quote = False
        findings.append(
            Finding(
                severity=current_severity,
                file=file,
                line=line,
                description=text,
                quote="\n".join(quote_lines),
                raw=text,
            )
        )
        current_bullet = []

    in_fenced_block = False
    for ln in lines:
        # Track fenced code blocks so a `# comment` line inside ``` ... ```
        # is not mistaken for a markdown heading.
        if ln.lstrip().startswith("```"):
            if current_bullet:
                current_bullet.append(ln)
            in_fenced_block = not in_fenced_block
            continue

        h = _HEADING_RE.match(ln)
        if h and not in_fenced_block:
            flush_bullet()
            current_severity = h.group(1).lower()
            continue
        # Any other heading ends the current section. Only un-indented `#`
        # lines count as markdown headings — quoted code (which reviewers
        # are explicitly told to include) often starts with `#` (Python,
        # shell, TOML, Makefile comments) and must not be misread as a
        # heading. CommonMark allows up to 3 spaces of indent; we treat
        # those as non-heading too because reviewer wrappers always emit
        # un-indented headings.
        if ln.startswith("#") and not h and not in_fenced_block:
            flush_bullet()
            current_severity = None
            continue
        if current_severity is None:
            continue
        if _BULLET_RE.match(ln):
            flush_bullet()
            current_bullet = [_BULLET_RE.sub("", ln, count=1)]
        elif current_bullet:
            current_bullet.append(ln)
    flush_bullet()

    return findings


def match_finding_to_truth(f: Finding, t: TruthDefect) -> bool:
    """Does this finding match this planted defect?"""
    if not f.file:
        return False
    f_basename = Path(f.file).name
    t_basename = Path(t.file).name
    if f_basename != t_basename:
        return False
    if f.line is None:
        # if no line cited, fall back to keyword-only with a stricter bar
        return _keyword_overlap(f, t, min_required=2)
    if abs(f.line - t.line) > LINE_TOLERANCE:
        return False
    return _keyword_overlap(f, t, min_required=1)


def _keyword_overlap(f: Finding, t: TruthDefect, min_required: int) -> bool:
    if not t.keywords:
        return True
    fk = f.keywords()
    hits = sum(1 for kw in t.keywords if kw.lower() in fk)
    return hits >= min_required


def score(
    findings: list[Finding],
    truth: list[TruthDefect],
) -> dict:
    """Compute precision, recall, and per-truth match status.

    A truth defect is "found" if at least one finding matches it.
    A finding is a "true positive" if it matches at least one truth.
    A finding that matches no truth is a false positive.
    """
    truth_found = [False] * len(truth)
    finding_matched = [False] * len(findings)

    for fi, f in enumerate(findings):
        for ti, t in enumerate(truth):
            if match_finding_to_truth(f, t):
                truth_found[ti] = True
                finding_matched[fi] = True

    tp = sum(1 for x in finding_matched if x)
    fp = sum(1 for x in finding_matched if not x)
    fn = sum(1 for x in truth_found if not x)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else (1.0 if not truth else 0.0)
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "truth_found": [
            {
                "file": t.file,
                "line": t.line,
                "severity": t.severity,
                "category": t.category,
                "found": truth_found[ti],
            }
            for ti, t in enumerate(truth)
        ],
        "false_positives": [
            {"file": f.file, "line": f.line, "description": f.description[:200]}
            for fi, f in enumerate(findings)
            if not finding_matched[fi]
        ],
    }
