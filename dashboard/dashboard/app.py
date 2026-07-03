"""
dashboard/app.py

Streamlit viewer for a logging run produced by extract_from_bag.py or
live_logger_node.py. Reads log.csv + frames/ only -- it doesn't know or
care which of the two wrote them, or whether YOLO26 ran live or offline.

Usage:
    cd dashboard
    streamlit run app.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw

RUNS_ROOT = Path(__file__).parent.parent / "data" / "runs"

LABEL_COLORS = {
    "INVALID": "#888888",
    "OBSTRUCT": "#3B82F6",
    "CRUISING": "#22C55E",
    "WARNING": "#EAB308",
    "POTENTIAL_COLLISION": "#F97316",
    "HARD_BRAKING": "#EF4444",
}

st.set_page_config(page_title="TTC Run Viewer", layout="wide")


@st.cache_data
def load_run(run_dir: str) -> pd.DataFrame:
    return pd.read_csv(Path(run_dir) / "log.csv")


def list_runs() -> list[str]:
    if not RUNS_ROOT.exists():
        return []
    return sorted((p.name for p in RUNS_ROOT.iterdir() if p.is_dir()), reverse=True)


def draw_bbox(image_path: Path, bbox_json) -> Image.Image:
    img = Image.open(image_path).convert("RGB")
    if not bbox_json or pd.isna(bbox_json):
        return img
    try:
        x, y, w, h = json.loads(bbox_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        return img
    draw = ImageDraw.Draw(img)
    draw.rectangle([x, y, x + w, y + h], outline="red", width=3)
    return img


def main() -> None:
    st.title("TTC logging run viewer")

    runs = list_runs()
    if not runs:
        st.warning(f"No runs found in {RUNS_ROOT}. Run extract_from_bag.py or the live logger first.")
        return

    run_name = st.sidebar.selectbox("Run", runs)
    run_dir = RUNS_ROOT / run_name
    df = load_run(str(run_dir))

    label_options = sorted(df["safety_label"].dropna().unique().tolist())
    label_filter = st.sidebar.multiselect("Filter by label", label_options, default=label_options)

    class_options = sorted(df["obstruction_class"].dropna().unique().tolist())
    class_filter = st.sidebar.multiselect("Filter by class", class_options, default=class_options)

    filtered = df[
        df["safety_label"].isin(label_filter)
        & (df["obstruction_class"].isin(class_filter) | df["obstruction_class"].isna())
    ].reset_index(drop=True)

    if filtered.empty:
        st.info("No frames match the current filters.")
        return

    if "frame_pos" not in st.session_state:
        st.session_state.frame_pos = 0
    st.session_state.frame_pos = min(st.session_state.frame_pos, len(filtered) - 1)

    col_prev, col_slider, col_next = st.columns([1, 8, 1])
    with col_prev:
        if st.button("< Prev") and st.session_state.frame_pos > 0:
            st.session_state.frame_pos -= 1
    with col_next:
        if st.button("Next >") and st.session_state.frame_pos < len(filtered) - 1:
            st.session_state.frame_pos += 1
    with col_slider:
        st.session_state.frame_pos = st.slider(
            "Frame", 0, len(filtered) - 1, st.session_state.frame_pos, label_visibility="collapsed"
        )

    row = filtered.iloc[st.session_state.frame_pos]

    img_col, info_col = st.columns([2, 1])
    with img_col:
        image_path = run_dir / row["debug_image_path"]
        if image_path.exists():
            bbox_json = row["bbox"] if "bbox" in filtered.columns else None
            st.image(draw_bbox(image_path, bbox_json), use_container_width=True)
        else:
            st.warning(f"Missing frame image: {image_path}")

    with info_col:
        label = row["safety_label"]
        color = LABEL_COLORS.get(label, "#888888")
        st.markdown(
            f"<div style='background-color:{color};padding:12px;border-radius:8px;"
            f"text-align:center;color:white;font-weight:bold;font-size:20px'>{label}</div>",
            unsafe_allow_html=True,
        )
        dist = row["front_obstacle_distance_m"]
        ttc = row["front_obstacle_ttc_s"]
        pc = row["potential_collision"]
        st.metric("Distance (m)", f"{dist:.1f}" if pd.notna(dist) else "—")
        st.metric("TTC (s)", f"{ttc:.1f}" if pd.notna(ttc) else "—")
        st.metric("Potential collision", pc if pd.notna(pc) and pc != "" else "unknown")
        st.metric("Obstruction", row["obstruction_class"] if pd.notna(row["obstruction_class"]) else "none")
        st.caption(f"Frame {row['frame_id']} · valid={row['front_obstacle_valid']} · objects={row['num_objects']}")

    st.subheader("TTC and distance over the run")
    chart_df = df[["frame_id", "front_obstacle_ttc_s", "front_obstacle_distance_m"]].set_index("frame_id")
    st.line_chart(chart_df)

    st.subheader("Full log")
    st.dataframe(df, use_container_width=True, height=300)


if __name__ == "__main__":
    main()
