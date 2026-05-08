"""Tiny config parser. No defects planted in this fixture."""

from pathlib import Path


def parse_kv(text: str) -> dict[str, str]:
    """Parse `key=value` lines, ignoring blanks and `#` comments."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"malformed line: {raw!r}")
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def load_config(path: Path) -> dict[str, str]:
    return parse_kv(path.read_text())
