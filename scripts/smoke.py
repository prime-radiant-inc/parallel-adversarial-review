#!/usr/bin/env python3
"""Smoke-test each enabled+installed adapter with a trivial prompt.

Sends the same one-line prompt to every adapter, expects each to echo
"SMOKE_OK" somewhere in stdout. Reports per-CLI status, duration, and
the first 200 chars of output for diagnosis.

Use this whenever you change adapters.toml or after upgrading a CLI.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from adapters import available, invoke, load_adapters  # noqa: E402

SMOKE_PROMPT = (
    "You are participating in a smoke test. "
    "Reply with EXACTLY this token, with no other text or formatting: "
    "SMOKE_OK"
)
EXPECTED = "SMOKE_OK"


def main() -> int:
    adapters = load_adapters()
    names = available(adapters)
    if not names:
        print("no enabled+installed adapters", file=sys.stderr)
        return 2

    print(f"smoke-testing {len(names)} adapters: {', '.join(names)}")
    print()
    print(f"{'cli':<12}  {'status':<8}  {'duration':>8}  notes")
    print("-" * 80)

    fails = 0
    for name in names:
        a = adapters[name]
        t0 = time.monotonic()
        result = invoke(a, SMOKE_PROMPT, Path.cwd(), mock_dir=None)
        dur = time.monotonic() - t0

        if not result.ok:
            err = (result.error or "").splitlines()[0][:60]
            stderr_snip = (result.stderr or "").strip().splitlines()
            stderr_snip = stderr_snip[0][:80] if stderr_snip else ""
            print(f"{name:<12}  {'FAIL':<8}  {dur:>7.1f}s  {err}  | {stderr_snip}")
            fails += 1
            continue

        echoed = EXPECTED in result.stdout
        snip = result.stdout.strip().replace("\n", " ")[:60]
        verdict = "OK" if echoed else "WEAK"
        if not echoed:
            fails += 1
        print(f"{name:<12}  {verdict:<8}  {dur:>7.1f}s  {snip}")

    print()
    if fails:
        print(f"{fails} adapter(s) had issues. Inspect adapters.toml.")
        return 1
    print("all adapters responded with SMOKE_OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
