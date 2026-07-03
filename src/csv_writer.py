"""
csv_writer.py

Appends one row per frame to a run's log.csv, and saves the debug image
for that frame to disk. Used by both extract_from_bag.py and
live_logger_node.py so the two produce identically-shaped output.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

CSV_FIELDS = [
    "frame_id",
    "stamp",
    "front_obstacle_valid",
    "front_obstacle_distance_m",
    "front_obstacle_ttc_s",
    "obstruction_class",
    "num_objects",
    "objects_json",
    "potential_collision",
    "safety_label",
    "debug_image_path",
]


@dataclass
class FrameRow:
    frame_id: int
    stamp: float
    front_obstacle_valid: bool
    front_obstacle_distance_m: Optional[float]
    front_obstacle_ttc_s: Optional[float]
    obstruction_class: Optional[str]
    num_objects: int
    objects_json: str
    potential_collision: Optional[bool]  # None -> written as "" (unknown, not "no")
    safety_label: str
    debug_image_path: str

    def to_csv_dict(self) -> dict:
        def fmt_bool(b: Optional[bool]) -> str:
            if b is None:
                return ""
            return "Y" if b else "N"

        def fmt_float(v: Optional[float]):
            return "" if v is None else v

        return {
            "frame_id": self.frame_id,
            "stamp": self.stamp,
            "front_obstacle_valid": "Y" if self.front_obstacle_valid else "N",
            "front_obstacle_distance_m": fmt_float(self.front_obstacle_distance_m),
            "front_obstacle_ttc_s": fmt_float(self.front_obstacle_ttc_s),
            "obstruction_class": self.obstruction_class or "",
            "num_objects": self.num_objects,
            "objects_json": self.objects_json,
            "potential_collision": fmt_bool(self.potential_collision),
            "safety_label": self.safety_label,
            "debug_image_path": self.debug_image_path,
        }


class RunLogger:
    """One instance per run. Creates data/runs/<run_id>/frames/ and
    log.csv, and appends rows + saves debug images as frames come in.
    Flushes to disk on every row so a live run survives a crash."""

    def __init__(self, runs_root: str = "data/runs", run_id: Optional[str] = None):
        self.run_id = run_id or datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.run_dir = Path(runs_root) / self.run_id
        self.frames_dir = self.run_dir / "frames"
        self.frames_dir.mkdir(parents=True, exist_ok=True)

        self.csv_path = self.run_dir / "log.csv"
        self._csv_file = open(self.csv_path, "w", newline="")
        self._writer = csv.DictWriter(self._csv_file, fieldnames=CSV_FIELDS)
        self._writer.writeheader()
        self._csv_file.flush()

    def save_debug_image(self, frame_id: int, image_bytes: bytes, ext: str = "jpg") -> str:
        """Writes already-encoded image bytes (e.g. from cv2.imencode) to
        disk and returns a path relative to the run folder, for the CSV."""
        filename = f"{frame_id:06d}.{ext}"
        path = self.frames_dir / filename
        with open(path, "wb") as f:
            f.write(image_bytes)
        return f"frames/{filename}"

    def append(self, row: FrameRow) -> None:
        self._writer.writerow(row.to_csv_dict())
        self._csv_file.flush()

    def close(self) -> None:
        self._csv_file.close()

    def __enter__(self) -> "RunLogger":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
