"""
extract_from_bag.py

Offline extraction: reads a finished rosbag2 recording of the
ttc_v2_label_node topics and writes a review run (log.csv + frames/)
using the same label_logic and csv_writer as live_logger_node.py.

Assumes these standard message types -- edit MSG_TYPES below if your
node actually publishes custom ones:
    ttc/front_obstacle_valid     std_msgs/msg/Bool
    ttc/front_obstacle_distance  std_msgs/msg/Float32
    ttc/front_obstacle           std_msgs/msg/Float32   (TTC seconds, may be inf)
    ttc/objects_json             std_msgs/msg/String    (JSON array of objects)
    ttc/debug_image              sensor_msgs/msg/Image

The five topics aren't assumed to publish in lockstep. ttc/debug_image is
treated as the "tick": each image triggers one CSV row, paired with
whatever the latest valid/distance/ttc/objects readings were -- as long
as none of them are older than --sync-tolerance seconds. If a topic is
older than that, the frame is skipped rather than paired with stale data.

Usage:
    python3 extract_from_bag.py /path/to/bag_dir \
        --thresholds ../configs/thresholds.yaml \
        --runs-root ../data/runs \
        --run-id 2026-07-03_demo1 \
        --sync-tolerance 0.1

objects_json is expected to be a JSON list of objects, each with at
least "class" and "distance_m" keys -- adjust primary_object_class()
below if your node's schema differs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import cv2
import rclpy.serialization
import rosbag2_py
from cv_bridge import CvBridge
from sensor_msgs.msg import Image
from std_msgs.msg import Bool, Float32, String

sys.path.insert(0, str(Path(__file__).parent))
from csv_writer import FrameRow, RunLogger
from label_logic import Thresholds, compute_label

TOPIC_VALID = "ttc/front_obstacle_valid"
TOPIC_DISTANCE = "ttc/front_obstacle_distance"
TOPIC_TTC = "ttc/front_obstacle"
TOPIC_OBJECTS = "ttc/objects_json"
TOPIC_IMAGE = "ttc/debug_image"

MSG_TYPES = {
    TOPIC_VALID: Bool,
    TOPIC_DISTANCE: Float32,
    TOPIC_TTC: Float32,
    TOPIC_OBJECTS: String,
    TOPIC_IMAGE: Image,
}


def open_reader(bag_path: str) -> rosbag2_py.SequentialReader:
    reader = rosbag2_py.SequentialReader()
    storage_options = rosbag2_py.StorageOptions(uri=bag_path, storage_id="sqlite3")
    converter_options = rosbag2_py.ConverterOptions(
        input_serialization_format="cdr", output_serialization_format="cdr"
    )
    reader.open(storage_options, converter_options)
    return reader


def primary_object_class(objects_json: str) -> Optional[str]:
    """Pulls the class of the nearest tracked object out of objects_json.
    Adjust the key names here if your node's schema differs."""
    if not objects_json:
        return None
    try:
        objects = json.loads(objects_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not objects:
        return None
    nearest = min(objects, key=lambda o: o.get("distance_m", float("inf")))
    return nearest.get("class")


def count_objects(objects_json: str) -> int:
    if not objects_json:
        return 0
    try:
        objects = json.loads(objects_json)
    except (json.JSONDecodeError, TypeError):
        return 0
    return len(objects) if isinstance(objects, list) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bag_path", help="Path to the rosbag2 directory")
    parser.add_argument("--thresholds", default="../configs/thresholds.yaml")
    parser.add_argument("--runs-root", default="../data/runs")
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--sync-tolerance",
        type=float,
        default=0.1,
        help="Max seconds between a debug_image and the latest known "
        "valid/distance/ttc/objects reading for them to be paired into one row.",
    )
    args = parser.parse_args()

    thresholds = Thresholds.from_yaml(args.thresholds)
    bridge = CvBridge()
    reader = open_reader(args.bag_path)

    available = {t.name for t in reader.get_all_topics_and_types()}
    missing = set(MSG_TYPES) - available
    if missing:
        print(f"Warning: bag is missing topics {missing}; those fields will stay unknown for every frame.")

    latest_valid: Optional[bool] = None
    latest_valid_stamp: Optional[float] = None
    latest_distance: Optional[float] = None
    latest_distance_stamp: Optional[float] = None
    latest_ttc: Optional[float] = None
    latest_ttc_stamp: Optional[float] = None
    latest_objects_json = ""
    latest_objects_stamp: Optional[float] = None

    frame_id = 0
    skipped_stale = 0

    with RunLogger(runs_root=args.runs_root, run_id=args.run_id) as logger:
        while reader.has_next():
            topic, data, t_ns = reader.read_next()
            stamp = t_ns / 1e9

            if topic == TOPIC_VALID:
                msg = rclpy.serialization.deserialize_message(data, Bool)
                latest_valid, latest_valid_stamp = msg.data, stamp

            elif topic == TOPIC_DISTANCE:
                msg = rclpy.serialization.deserialize_message(data, Float32)
                latest_distance, latest_distance_stamp = msg.data, stamp

            elif topic == TOPIC_TTC:
                msg = rclpy.serialization.deserialize_message(data, Float32)
                latest_ttc, latest_ttc_stamp = msg.data, stamp

            elif topic == TOPIC_OBJECTS:
                msg = rclpy.serialization.deserialize_message(data, String)
                latest_objects_json, latest_objects_stamp = msg.data, stamp

            elif topic == TOPIC_IMAGE:
                stamps = [
                    s
                    for s in (latest_valid_stamp, latest_distance_stamp, latest_ttc_stamp, latest_objects_stamp)
                    if s is not None
                ]
                stale = any(abs(stamp - s) > args.sync_tolerance for s in stamps)
                if not stamps or stale:
                    skipped_stale += 1
                    continue

                msg = rclpy.serialization.deserialize_message(data, Image)
                cv_image = bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
                ok, encoded = cv2.imencode(".jpg", cv_image)
                if not ok:
                    continue
                image_path = logger.save_debug_image(frame_id, encoded.tobytes())

                result = compute_label(
                    valid=bool(latest_valid),
                    distance_m=latest_distance,
                    ttc_s=latest_ttc,
                    thresholds=thresholds,
                )

                row = FrameRow(
                    frame_id=frame_id,
                    stamp=stamp,
                    front_obstacle_valid=bool(latest_valid),
                    front_obstacle_distance_m=latest_distance if latest_valid else None,
                    front_obstacle_ttc_s=latest_ttc if latest_valid else None,
                    obstruction_class=primary_object_class(latest_objects_json) if latest_valid else None,
                    num_objects=count_objects(latest_objects_json),
                    objects_json=latest_objects_json,
                    potential_collision=result.potential_collision,
                    safety_label=result.safety_label,
                    debug_image_path=image_path,
                )
                logger.append(row)
                frame_id += 1

        print(f"Wrote {frame_id} rows to {logger.run_dir}")

    if skipped_stale:
        print(f"Skipped {skipped_stale} debug_image frames with no fresh reading within {args.sync_tolerance}s")


if __name__ == "__main__":
    main()
