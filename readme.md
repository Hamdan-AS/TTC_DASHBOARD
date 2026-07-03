# TTC logging + review dashboard

Turns the `ttc_v2_label_node` topics into a reviewable CSV + frame log,
either from a finished rosbag2 recording or live during a demo, and a
Streamlit app to step through the result frame by frame.

## Layout

```
configs/
  classes.yaml       locked COCO classes (reference for the perception node)
  thresholds.yaml     TTC band thresholds used by label_logic.py
src/
  label_logic.py       pure fn: (valid, distance, ttc) -> (safety_label, potential_collision)
  csv_writer.py         appends CSV rows + saves debug images for a run
  extract_from_bag.py   offline: reads a finished rosbag2 recording
  live_logger_node.py   ROS2 node: subscribes live during a demo
dashboard/
  app.py                Streamlit viewer, reads a run folder only
data/runs/<run_id>/     one folder per run: log.csv + frames/
```

`extract_from_bag.py` and `live_logger_node.py` both call the same
`label_logic.compute_label()` and `csv_writer.RunLogger`, so a bag replay
and a live demo of the same input produce identical rows.

## Assumptions to check against your actual node

- Message types: `Bool` / `Float32` / `Float32` / `String` (JSON) / `Image`
  for the five topics. If your node publishes custom message types,
  update `MSG_TYPES` / the subscription calls in both logger scripts.
- `objects_json` is a JSON list of objects with at least `class` and
  `distance_m` keys. `primary_object_class()` in each logger picks the
  nearest one as the row's `obstruction_class`. Adjust the key names if
  your schema differs.
- The five topics aren't assumed to publish in lockstep. `ttc/debug_image`
  is treated as the per-frame "tick"; a frame is only logged if the other
  four readings are all within `--sync-tolerance` seconds (default 0.1s)
  of the image. Frames without a fresh reading are skipped and counted,
  not logged with stale data.

## Label bands (`configs/thresholds.yaml`)

| condition | `safety_label` | `potential_collision` |
|---|---|---|
| `valid = false` | `INVALID` | *(blank — unknown, not "N")* |
| `valid = true`, TTC = inf | `OBSTRUCT` | N |
| TTC > 4s | `CRUISING` | N |
| 2s < TTC ≤ 4s | `WARNING` | N |
| 1.5s ≤ TTC ≤ 2s | `POTENTIAL_COLLISION` | Y |
| TTC < 1.5s | `HARD_BRAKING` | Y |

All four numbers live in `configs/thresholds.yaml`, not in code.

## Running it

**Offline, from a finished bag:**
```bash
pip install pyyaml opencv-python --break-system-packages   # inside your ROS2 env
python3 src/extract_from_bag.py /path/to/bag_dir \
    --thresholds configs/thresholds.yaml \
    --runs-root data/runs \
    --run-id 2026-07-03_demo1
```

**Live, during a ROS2 session:**
```bash
python3 src/live_logger_node.py --ros-args \
    -p thresholds_path:=configs/thresholds.yaml \
    -p runs_root:=data/runs
```
(Wire this into your package's `setup.py` console_scripts to run it as
`ros2 run <your_package> live_logger_node` instead, once it lives inside
your ROS2 workspace.)

**Dashboard (no ROS2 needed):**
```bash
pip install -r requirements.txt
cd dashboard
streamlit run app.py
```
It lists every folder under `data/runs/`, lets you filter by label and
class, step frame-by-frame, and shows a TTC/distance chart for the whole
run — useful for spotting near-miss events to pull out for edge-case
review.

## Tested so far

- `label_logic.py`: unit-tested all six band boundaries (exact 4.0s,
  2.0s, 1.5s edges) plus the `inf` and `invalid` cases.
- `csv_writer.py`: confirmed an invalid frame writes blank fields, not
  `0` or `N`.
- `dashboard/app.py`: smoke-tested against a fake run, serves without
  errors.
- `extract_from_bag.py` / `live_logger_node.py`: syntax-checked only —
  I don't have a ROS2 install in this sandbox to test against a real bag
  or live topics, so treat those two as a first draft to run against your
  actual node and adjust the message-type / objects_json assumptions
  above if they don't match.
