"""Simple disk-backed cache. There is a bug in `read_value`."""

import json
from pathlib import Path


def write_value(cache_dir: Path, key: str, value: dict) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{key}.json"
    with path.open("w") as f:
        json.dump(value, f)


def read_value(cache_dir: Path, key: str) -> dict | None:
    path = cache_dir / f"{key}.json"
    if not path.exists():
        return None
    f = path.open("r")
    data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("cache value is not a dict")
    f.close()
    return data
