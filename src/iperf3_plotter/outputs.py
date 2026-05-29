from __future__ import annotations

import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message="Pandas requires version .*", category=UserWarning)

import pandas as pd

from . import __version__
from .metrics import (
    bandwidth_share,
    experiment_summary,
    fairness_over_time,
    flow_aggregates,
    interval_summary,
    resample_time_bins,
    series_similarity,
)


def write_tables(
    intervals: pd.DataFrame,
    summaries: pd.DataFrame,
    runs: pd.DataFrame,
    out_dir: Path,
    *,
    time_mode: str = "relative",
) -> dict[str, Path]:
    """Write normalized CSV tables and derived metric tables."""

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}

    files["intervals"] = out_dir / "intervals.csv"
    intervals.to_csv(files["intervals"], index=False)

    files["summaries"] = out_dir / "summaries.csv"
    summaries.to_csv(files["summaries"], index=False)

    files["runs"] = out_dir / "runs.csv"
    runs.to_csv(files["runs"], index=False)

    flow_df = flow_aggregates(intervals)
    files["flow_intervals"] = out_dir / "flow_intervals.csv"
    flow_df.to_csv(files["flow_intervals"], index=False)

    stream_bins = resample_time_bins(intervals, entity_col="stream_id", time_mode=time_mode)
    files["stream_time_bins"] = out_dir / "stream_time_bins.csv"
    stream_bins.to_csv(files["stream_time_bins"], index=False)

    flow_bins = resample_time_bins(flow_df, entity_col="flow_id", time_mode=time_mode) if not flow_df.empty else pd.DataFrame()
    files["flow_time_bins"] = out_dir / "flow_time_bins.csv"
    flow_bins.to_csv(files["flow_time_bins"], index=False)

    stream_summary = interval_summary(intervals, "stream_id")
    files["stream_summary"] = out_dir / "stream_summary.csv"
    stream_summary.to_csv(files["stream_summary"], index=False)

    stream_similarity = series_similarity(intervals)
    files["stream_similarity"] = out_dir / "stream_similarity.csv"
    stream_similarity.to_csv(files["stream_similarity"], index=False)

    flow_summary = interval_summary(flow_df, "flow_id") if not flow_df.empty else pd.DataFrame()
    files["flow_summary"] = out_dir / "flow_summary.csv"
    flow_summary.to_csv(files["flow_summary"], index=False)

    experiment_df = experiment_summary(flow_summary)
    files["experiment_summary"] = out_dir / "experiment_summary.csv"
    experiment_df.to_csv(files["experiment_summary"], index=False)

    stream_fairness = fairness_over_time(stream_bins, "stream_id", "time_bin_start_s") if not stream_bins.empty else pd.DataFrame()
    files["stream_fairness"] = out_dir / "stream_fairness.csv"
    stream_fairness.to_csv(files["stream_fairness"], index=False)

    flow_fairness = fairness_over_time(flow_bins, "flow_id", "time_bin_start_s") if not flow_bins.empty else pd.DataFrame()
    files["flow_fairness"] = out_dir / "flow_fairness.csv"
    flow_fairness.to_csv(files["flow_fairness"], index=False)

    stream_share = bandwidth_share(stream_bins, "stream_id", "time_bin_start_s") if not stream_bins.empty else pd.DataFrame()
    files["stream_share"] = out_dir / "stream_share.csv"
    stream_share.to_csv(files["stream_share"], index=False)

    flow_share = bandwidth_share(flow_bins, "flow_id", "time_bin_start_s") if not flow_bins.empty else pd.DataFrame()
    files["flow_share"] = out_dir / "flow_share.csv"
    flow_share.to_csv(files["flow_share"], index=False)

    metadata = {
        "version": __version__,
        "runs": int(runs["run_id"].nunique()) if "run_id" in runs.columns else 0,
        "flows": int(intervals["flow_id"].nunique()) if "flow_id" in intervals.columns else 0,
        "streams": int(intervals["stream_id"].nunique()) if "stream_id" in intervals.columns else 0,
        "interval_rows": int(len(intervals)),
        "summary_rows": int(len(summaries)),
        "time_mode": time_mode,
        "files": {key: str(path.name) for key, path in files.items()},
    }
    files["metadata"] = out_dir / "metadata.json"
    files["metadata"].write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return files
