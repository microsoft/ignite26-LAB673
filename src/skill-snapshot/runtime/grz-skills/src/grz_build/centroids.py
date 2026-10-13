"""Community centroid data shared by native build adapters and sidecar consumers."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Centroid:
    level: int
    community_id: str
    members: tuple[str, ...]
    parent: str | None
    vector: np.ndarray
