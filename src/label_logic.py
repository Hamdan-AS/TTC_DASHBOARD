"""
label_logic.py

Pure, side-effect-free logic that turns a single perception reading
(valid flag, distance, TTC) into a safety_label and a potential_collision
flag. Used identically by extract_from_bag.py and live_logger_node.py so
behavior never drifts between an offline replay and a live demo run.

Gatekeeper rule: if `valid` is False, distance/TTC/labels are all treated
as unknown -- never defaulted to 0 or to "safe". That silent-default is
exactly the failure mode this module exists to avoid.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import yaml

VALID_LABELS = (
    "INVALID",
    "OBSTRUCT",
    "CRUISING",
    "WARNING",
    "POTENTIAL_COLLISION",
    "HARD_BRAKING",
)


@dataclass(frozen=True)
class Thresholds:
    cruising_min_s: float = 4.0
    warning_min_s: float = 2.0
    potential_collision_min_s: float = 1.5
    potential_collision_cutoff_s: float = 2.0

    @classmethod
    def from_yaml(cls, path: str) -> "Thresholds":
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        bands = data.get("ttc_bands", {})
        return cls(
            cruising_min_s=float(bands.get("cruising_min_s", cls.cruising_min_s)),
            warning_min_s=float(bands.get("warning_min_s", cls.warning_min_s)),
            potential_collision_min_s=float(
                bands.get("potential_collision_min_s", cls.potential_collision_min_s)
            ),
            potential_collision_cutoff_s=float(
                data.get("potential_collision_cutoff_s", cls.potential_collision_cutoff_s)
            ),
        )


@dataclass(frozen=True)
class LabelResult:
    safety_label: str
    potential_collision: Optional[bool]  # None means "unknown", never treat as False


def compute_label(
    valid: bool,
    distance_m: Optional[float],
    ttc_s: Optional[float],
    thresholds: Thresholds = Thresholds(),
) -> LabelResult:
    """Decide the safety_label and potential_collision flag for one frame.

    distance_m is accepted for symmetry/future use (e.g. a distance-based
    override) but the current bands are TTC-driven only, matching the
    node's own AEB-style logic.
    """
    if not valid:
        return LabelResult(safety_label="INVALID", potential_collision=None)

    if ttc_s is None:
        # valid=True with no TTC shouldn't happen in practice; treat as
        # unknown rather than guessing which band it belongs in.
        return LabelResult(safety_label="INVALID", potential_collision=None)

    if math.isinf(ttc_s):
        # Object present and tracked, but not closing -> no collision risk.
        return LabelResult(safety_label="OBSTRUCT", potential_collision=False)

    if ttc_s > thresholds.cruising_min_s:
        label = "CRUISING"
    elif ttc_s > thresholds.warning_min_s:
        label = "WARNING"
    elif ttc_s >= thresholds.potential_collision_min_s:
        label = "POTENTIAL_COLLISION"
    else:
        label = "HARD_BRAKING"

    potential_collision = ttc_s <= thresholds.potential_collision_cutoff_s
    return LabelResult(safety_label=label, potential_collision=potential_collision)
