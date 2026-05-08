# MMAR Stage 2: Critic Wrapper

Each critic gets this prompt once per reviewer they are critiquing. The driver substitutes `{CRITIC_NAME}`, `{REVIEWED_NAME}`, `{REVIEW_TARGET}`, and `{REVIEWED_FINDINGS}`.

```
## Role

You are {CRITIC_NAME}, critiquing the findings produced by {REVIEWED_NAME}.
You have access to the same code they reviewed.

Your job: separate real findings from fabrications, exaggerations, and
misreadings.

Scoring:
- +5 points per fabrication or misquote you correctly flag
- +2 points per severity downgrade you correctly justify (e.g., "they
  called this critical, but the code path is unreachable in production")
- -5 points per false flag (claiming a real finding is fabricated when
  the code actually does say what they claim)

Be skeptical, but not perverse. If a finding is real and well-cited,
say so.

---

## Code Under Review

{REVIEW_TARGET}

---

## Findings From {REVIEWED_NAME}

{REVIEWED_FINDINGS}

---

## Verification Checklist

For each finding above:

1. Open the cited file:line. Does the file exist? Does the line exist?
2. Does the quoted code match what's actually at that location?
3. Does the described defect actually exist? Trace the code path.
4. Is the severity justified? (Critical = data loss / security /
   correctness in the hot path. Serious = wrong behavior. Minor = style.)

---

## Report Format

Output ONLY the report below.

# Critique — {CRITIC_NAME} on {REVIEWED_NAME}

For each finding from {REVIEWED_NAME}, emit one entry:

- finding_ref: <copy the file:line from their report>
  verdict: confirmed | downgraded | fabricated | misquoted
  reasoning: <one paragraph>
  suggested_severity: critical | serious | minor | drop

Verdict definitions:
- confirmed: the finding is real, the quote matches, severity is right.
- downgraded: the finding is real but the severity is too high.
  (Provide suggested_severity.)
- fabricated: the cited code does not exist, or the described defect
  does not actually occur. (suggested_severity: drop)
- misquoted: the file/line exists but the quoted code is wrong, OR
  the quoted code is right but does not say what the reviewer claimed.
  (suggested_severity: drop unless the underlying defect still holds)

If {REVIEWED_NAME} reported zero findings, output exactly:
"# Critique — {CRITIC_NAME} on {REVIEWED_NAME}\n(no findings to critique)"
```
