"""CLI adapter invocation.

Reads adapters.toml, runs the configured CLI with a given prompt, returns
stdout. Supports a mock mode that reads pre-recorded responses from disk
for cheap, deterministic eval runs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore


HERE = Path(__file__).resolve().parent
ADAPTERS_TOML = HERE / "adapters.toml"


@dataclass
class Adapter:
    name: str
    enabled: bool
    binary: str
    argv: list[str]
    prompt_via: str
    prompt_flag: str | None
    timeout_sec: int
    notes: str

    @property
    def installed(self) -> bool:
        return shutil.which(self.binary) is not None


def load_adapters(path: Path = ADAPTERS_TOML) -> dict[str, Adapter]:
    raw = tomllib.loads(path.read_text())
    out: dict[str, Adapter] = {}
    for name, cfg in raw.items():
        out[name] = Adapter(
            name=name,
            enabled=cfg.get("enabled", True),
            binary=cfg["binary"],
            argv=list(cfg.get("argv", [])),
            prompt_via=cfg.get("prompt_via", "stdin"),
            prompt_flag=cfg.get("prompt_flag"),
            timeout_sec=int(cfg.get("timeout_sec", 300)),
            notes=cfg.get("notes", ""),
        )
    return out


def available(adapters: dict[str, Adapter]) -> list[str]:
    return sorted(n for n, a in adapters.items() if a.enabled and a.installed)


@dataclass
class InvocationResult:
    name: str
    ok: bool
    stdout: str
    stderr: str
    duration_sec: float
    error: str | None = None


def invoke(
    adapter: Adapter,
    prompt: str,
    workdir: Path,
    mock_dir: Path | None = None,
) -> InvocationResult:
    """Run the adapter with `prompt` and return the result.

    If mock_dir is provided, read from <mock_dir>/<adapter.name>.txt
    instead of running the CLI.
    """
    import time

    start = time.monotonic()

    if mock_dir is not None:
        mock_file = mock_dir / f"{adapter.name}.txt"
        if mock_file.exists():
            return InvocationResult(
                name=adapter.name,
                ok=True,
                stdout=mock_file.read_text(),
                stderr="",
                duration_sec=time.monotonic() - start,
            )
        return InvocationResult(
            name=adapter.name,
            ok=False,
            stdout="",
            stderr="",
            duration_sec=time.monotonic() - start,
            error=f"mock file not found: {mock_file}",
        )

    if not adapter.installed:
        return InvocationResult(
            name=adapter.name,
            ok=False,
            stdout="",
            stderr="",
            duration_sec=0.0,
            error=f"{adapter.binary} not installed",
        )

    cmd = [adapter.binary, *adapter.argv]
    stdin_data: str | None = None

    if adapter.prompt_via == "argv":
        cmd.append(prompt)
    elif adapter.prompt_via == "argv-after-flag":
        flag = adapter.prompt_flag
        if flag is None or flag not in cmd:
            return InvocationResult(
                name=adapter.name,
                ok=False,
                stdout="",
                stderr="",
                duration_sec=0.0,
                error=f"prompt_flag '{flag}' not found in argv for {adapter.name}",
            )
        idx = cmd.index(flag)
        cmd.insert(idx + 1, prompt)
    elif adapter.prompt_via == "stdin":
        stdin_data = prompt
    else:
        return InvocationResult(
            name=adapter.name,
            ok=False,
            stdout="",
            stderr="",
            duration_sec=0.0,
            error=f"unknown prompt_via: {adapter.prompt_via}",
        )

    try:
        proc = subprocess.run(
            cmd,
            cwd=workdir,
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=adapter.timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return InvocationResult(
            name=adapter.name,
            ok=False,
            stdout="",
            stderr="",
            duration_sec=time.monotonic() - start,
            error=f"timeout after {adapter.timeout_sec}s",
        )
    except FileNotFoundError as e:
        return InvocationResult(
            name=adapter.name,
            ok=False,
            stdout="",
            stderr="",
            duration_sec=time.monotonic() - start,
            error=str(e),
        )

    return InvocationResult(
        name=adapter.name,
        ok=proc.returncode == 0,
        stdout=proc.stdout,
        stderr=proc.stderr,
        duration_sec=time.monotonic() - start,
        error=None if proc.returncode == 0 else f"exit {proc.returncode}",
    )


def main() -> int:
    """`python adapters.py list` — show installed adapters."""
    if len(sys.argv) < 2 or sys.argv[1] != "list":
        print("usage: adapters.py list", file=sys.stderr)
        return 2
    adapters = load_adapters()
    width = max(len(n) for n in adapters)
    for name, a in sorted(adapters.items()):
        status = "ENABLED" if a.enabled else "DISABLED"
        installed = "installed" if a.installed else "MISSING"
        print(f"{name:<{width}}  {status:<8}  {installed:<10}  {a.binary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
