"""Quality metrics that separate reconciliation evidence from source accuracy."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any


def zero_error_upper_bound(sample_size: int, confidence: float = 0.95) -> float:
    """Exact one-sided upper bound after observing zero errors.

    This is ``1 - (1-confidence)**(1/n)``. The familiar rule of three is its
    95% large-sample approximation. A zero-error sample is not proof of zero
    population error.
    """

    if sample_size <= 0:
        raise ValueError("sample_size must be positive")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    return 1.0 - math.pow(1.0 - confidence, 1.0 / sample_size)


def summarize_statuses(items: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    materialized = list(items)
    statuses = Counter(str(item.get("status", "unknown")) for item in materialized)
    total = sum(statuses.values())
    unresolved = sum(
        1
        for item in materialized
        if item.get("resolved") is False
        or (
            "resolved" not in item
            and str(item.get("status", "unknown"))
            in {
                "conflict",
                "missing",
                "missing_source",
                "structural_conflict",
                "unresolved",
            }
        )
    )
    return {
        "total_cells": total,
        "status_counts": dict(sorted(statuses.items())),
        "unresolved_cells": unresolved,
        "unresolved_rate": (unresolved / total) if total else 0.0,
        "claim_boundary": (
            "Reconciliation agreement measures internal multi-source consistency; "
            "it does not by itself establish accuracy against the scanned source."
        ),
    }
