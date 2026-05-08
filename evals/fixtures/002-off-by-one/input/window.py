"""Sliding-window utilities used by the metrics aggregator."""


def last_n(items: list[int], n: int) -> list[int]:
    """Return the last n items from the list."""
    return items[-n:]


def windowed_sum(items: list[int], window: int) -> list[int]:
    """Sum each consecutive `window` items. Returns one entry per window."""
    out = []
    # BUG: should be range(len(items) - window + 1), this overruns by one
    for i in range(len(items) - window + 2):
        out.append(sum(items[i : i + window]))
    return out


def normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    total = sum(values)
    if total == 0:
        return [0.0 for _ in values]
    return [v / total for v in values]
