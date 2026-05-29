from __future__ import annotations

from itertools import combinations
import warnings
from typing import Iterable

warnings.filterwarnings("ignore", message="Pandas requires version .*", category=UserWarning)

import pandas as pd

STREAM_DETAIL_COLUMNS = {
    "stream_id",
    "stream_index",
    "socket",
    "local_host",
    "local_port",
    "remote_host",
    "remote_port",
}

MEASUREMENT_COLUMNS = {
    "interval_index",
    "start_s",
    "end_s",
    "midpoint_s",
    "offset_start_s",
    "offset_end_s",
    "offset_midpoint_s",
    "global_start_s",
    "global_end_s",
    "global_midpoint_s",
    "absolute_start_s",
    "absolute_end_s",
    "duration_s",
    "bytes",
    "transfer_mib",
    "throughput_bps",
    "throughput_mbps",
    "retransmits",
    "cwnd_bytes",
    "cwnd_kib",
    "rtt_us",
    "rtt_ms",
    "rttvar_us",
    "rttvar_ms",
    "pmtu_bytes",
    "omitted",
    "jitter_ms",
    "lost_packets",
    "packets",
    "lost_percent",
    "active_duration_s",
    "active_streams",
}

SUMMARY_MEASUREMENT_COLUMNS = {
    "intervals",
    "duration_s",
    "total_mib",
    "avg_throughput_mbps",
    "mean_interval_mbps",
    "p95_interval_mbps",
    "retransmits",
    "mean_rtt_ms",
    "p95_rtt_ms",
    "max_rtt_ms",
}


def jain_fairness(values: Iterable[float]) -> float | None:
    vals = [float(value) for value in values if value is not None and pd.notna(value)]
    if not vals:
        return None
    squared_sum = sum(vals) ** 2
    sum_of_squares = sum(value * value for value in vals)
    if sum_of_squares == 0:
        return 1.0
    return squared_sum / (len(vals) * sum_of_squares)


def flow_aggregates(intervals: pd.DataFrame) -> pd.DataFrame:
    """Aggregate parallel streams into one row per flow and interval."""

    if intervals.empty:
        return pd.DataFrame()

    group_cols = [
        "source_file",
        "run_id",
        "flow_id",
        "flow_label",
        "cc_algo",
        "scenario",
        "group",
        "protocol",
        "reverse",
        "interval_index",
    ]
    numeric_sums = [
        "bytes",
        "transfer_mib",
        "throughput_bps",
        "throughput_mbps",
        "retransmits",
        "lost_packets",
        "packets",
    ]
    numeric_means = [
        "start_s",
        "end_s",
        "midpoint_s",
        "offset_start_s",
        "offset_end_s",
        "offset_midpoint_s",
        "global_start_s",
        "global_end_s",
        "global_midpoint_s",
        "absolute_start_s",
        "absolute_end_s",
        "duration_s",
        "rtt_us",
        "rtt_ms",
        "rttvar_us",
        "rttvar_ms",
        "pmtu_bytes",
        "jitter_ms",
        "lost_percent",
    ]
    numeric_max = ["cwnd_bytes", "cwnd_kib"]

    agg_spec: dict[str, str] = {}
    for col in numeric_sums:
        if col in intervals.columns:
            agg_spec[col] = "sum"
    for col in numeric_means:
        if col in intervals.columns:
            agg_spec[col] = "mean"
    for col in numeric_max:
        if col in intervals.columns:
            agg_spec[col] = "max"
    if "omitted" in intervals.columns:
        agg_spec["omitted"] = "any"
    if "stream_id" in intervals.columns:
        agg_spec["stream_id"] = "nunique"

    excluded = set(group_cols) | set(numeric_sums) | set(numeric_means) | set(numeric_max) | STREAM_DETAIL_COLUMNS
    for col in _first_value_columns(intervals, excluded):
        agg_spec.setdefault(col, "first")

    grouped = intervals.groupby(group_cols, dropna=False).agg(agg_spec).reset_index()
    if "stream_id" in grouped.columns:
        grouped = grouped.rename(columns={"stream_id": "active_streams"})
    return grouped.sort_values(["run_id", "flow_id", "interval_index"])


def total_aggregate(flow_df: pd.DataFrame, time_col: str) -> pd.DataFrame:
    """Aggregate all active flows at each time point."""

    if flow_df.empty:
        return pd.DataFrame()

    sum_cols = [
        col
        for col in [
            "bytes",
            "transfer_mib",
            "throughput_bps",
            "throughput_mbps",
            "retransmits",
            "lost_packets",
            "packets",
        ]
        if col in flow_df.columns
    ]
    mean_cols = [
        col
        for col in [
            "duration_s",
            "rtt_ms",
            "rttvar_ms",
            "jitter_ms",
            "lost_percent",
        ]
        if col in flow_df.columns
    ]

    agg_spec = {col: "sum" for col in sum_cols}
    agg_spec.update({col: "mean" for col in mean_cols})
    if "flow_id" in flow_df.columns:
        agg_spec["flow_id"] = "nunique"

    total = flow_df.groupby(time_col, dropna=False).agg(agg_spec).reset_index()
    if "flow_id" in total.columns:
        total = total.rename(columns={"flow_id": "active_flows"})
    return total.sort_values(time_col)


def resample_time_bins(
    df: pd.DataFrame,
    *,
    entity_col: str,
    time_mode: str = "relative",
    bin_s: float = 1.0,
    min_active_fraction: float = 0.05,
) -> pd.DataFrame:
    """Project interval data onto a common time grid using overlap weighting."""

    if df.empty or entity_col not in df.columns or bin_s <= 0:
        return pd.DataFrame()

    start_col, end_col = time_bounds_columns(df, time_mode)
    if start_col not in df.columns or end_col not in df.columns:
        return pd.DataFrame()

    usable = df.dropna(subset=[start_col, end_col]).copy()
    usable = usable[usable[end_col] > usable[start_col]]
    if usable.empty:
        return pd.DataFrame()

    origin = _grid_origin(usable[start_col].min(), bin_s)
    records: dict[tuple[object, int], dict[str, object]] = {}
    metadata_cols = [
        "source_file",
        "run_id",
        "flow_id",
        "flow_label",
        "cc_algo",
        "scenario",
        "group",
        "protocol",
        "reverse",
    ]
    metadata_cols.extend(col for col in _first_value_columns(df, set(metadata_cols) | MEASUREMENT_COLUMNS | STREAM_DETAIL_COLUMNS) if col not in metadata_cols)
    weighted_cols = [
        "rtt_ms",
        "rttvar_ms",
        "rtt_us",
        "rttvar_us",
        "cwnd_kib",
        "cwnd_bytes",
        "pmtu_bytes",
        "jitter_ms",
        "lost_percent",
    ]

    for _, row in usable.iterrows():
        start = float(row[start_col])
        end = float(row[end_col])
        duration = end - start
        if duration <= 0:
            continue
        first_bin = int((start - origin) // bin_s)
        last_bin = int(((end - origin) - 1e-12) // bin_s)
        for bin_index in range(first_bin, last_bin + 1):
            bin_start = origin + (bin_index * bin_s)
            bin_end = bin_start + bin_s
            overlap = max(0.0, min(end, bin_end) - max(start, bin_start))
            if overlap <= 0:
                continue
            entity = row[entity_col]
            key = (entity, bin_index)
            record = records.setdefault(
                key,
                {
                    entity_col: entity,
                    "time_bin_index": bin_index,
                    "time_bin_start_s": bin_start,
                    "time_bin_end_s": bin_end,
                    "time_bin_midpoint_s": bin_start + (bin_s / 2),
                    "active_duration_s": 0.0,
                    "bytes": 0.0,
                    "transfer_mib": 0.0,
                    "retransmits": 0.0,
                    "lost_packets": 0.0,
                    "packets": 0.0,
                    "omitted": False,
                    "_weighted_duration": 0.0,
                },
            )
            for col in metadata_cols:
                if col in row.index and col not in record:
                    record[col] = row[col]

            fraction = overlap / duration
            bytes_value = _value(row, "bytes")
            if bytes_value is None:
                throughput = _value(row, "throughput_bps") or 0.0
                bytes_contrib = (throughput * overlap) / 8
            else:
                bytes_contrib = bytes_value * fraction
            record["bytes"] = float(record["bytes"]) + bytes_contrib
            record["transfer_mib"] = float(record["transfer_mib"]) + (bytes_contrib / (1024 * 1024))
            record["active_duration_s"] = float(record["active_duration_s"]) + overlap

            for col in ("retransmits", "lost_packets", "packets"):
                value = _value(row, col)
                if value is not None:
                    record[col] = float(record[col]) + (value * fraction)
            if bool(row.get("omitted", False)):
                record["omitted"] = True
            if "active_streams" in row.index:
                record["active_streams"] = max(float(record.get("active_streams", 0)), _value(row, "active_streams") or 0)

            for col in weighted_cols:
                value = _value(row, col)
                if value is None:
                    continue
                record[f"_{col}_weighted"] = float(record.get(f"_{col}_weighted", 0.0)) + (value * overlap)
            record["_weighted_duration"] = float(record["_weighted_duration"]) + overlap

    rows = []
    for record in records.values():
        if float(record["active_duration_s"]) < (bin_s * min_active_fraction):
            continue
        record["throughput_bps"] = (float(record["bytes"]) * 8) / bin_s
        record["throughput_mbps"] = float(record["throughput_bps"]) / 1_000_000
        weighted_duration = float(record.pop("_weighted_duration", 0.0))
        for col in weighted_cols:
            weighted_key = f"_{col}_weighted"
            if weighted_key in record:
                record[col] = float(record.pop(weighted_key)) / weighted_duration if weighted_duration else None
        rows.append(record)

    return pd.DataFrame.from_records(rows).sort_values(["time_bin_start_s", entity_col])


def total_from_bins(binned_df: pd.DataFrame) -> pd.DataFrame:
    if binned_df.empty:
        return pd.DataFrame()

    sum_cols = [
        col
        for col in [
            "bytes",
            "transfer_mib",
            "throughput_bps",
            "throughput_mbps",
            "retransmits",
            "lost_packets",
            "packets",
        ]
        if col in binned_df.columns
    ]
    mean_cols = [
        col
        for col in ["rtt_ms", "rttvar_ms", "jitter_ms", "lost_percent", "active_duration_s"]
        if col in binned_df.columns
    ]
    agg_spec = {col: "sum" for col in sum_cols}
    agg_spec.update({col: "mean" for col in mean_cols})
    if "flow_id" in binned_df.columns:
        agg_spec["flow_id"] = "nunique"

    total = binned_df.groupby("time_bin_start_s", dropna=False).agg(agg_spec).reset_index()
    if "flow_id" in total.columns:
        total = total.rename(columns={"flow_id": "active_flows"})
    return total.sort_values("time_bin_start_s")


def fairness_over_time(df: pd.DataFrame, entity_col: str, time_col: str) -> pd.DataFrame:
    """Compute Jain fairness and share diagnostics among active entities."""

    if df.empty or entity_col not in df.columns or "throughput_bps" not in df.columns:
        return pd.DataFrame()

    group_cols = _fairness_group_columns(df, entity_col, time_col)
    grouping = [*group_cols, time_col]
    records = []
    for key, group in df.groupby(grouping, dropna=False):
        key_values = key if isinstance(key, tuple) else (key,)
        metadata_values = key_values[: len(group_cols)]
        time_value = key_values[-1]
        values = group["throughput_bps"].fillna(0)
        total = float(values.sum())
        active = len(group)
        record = {
            time_col: time_value,
            "active_entities": active,
            "total_throughput_mbps": total / 1_000_000,
            "jain_fairness": jain_fairness(values),
            "fair_share_mbps": (total / active / 1_000_000) if active else None,
            "min_share_percent": _min_share_percent(values),
            "max_share_percent": _max_share_percent(values),
        }
        record.update(dict(zip(group_cols, metadata_values)))
        records.append(record)
    return pd.DataFrame.from_records(records).sort_values(grouping)


def bandwidth_share(df: pd.DataFrame, entity_col: str, time_col: str) -> pd.DataFrame:
    """Return throughput share percentage per entity and time."""

    if df.empty or entity_col not in df.columns:
        return pd.DataFrame()

    share_df = df[[time_col, entity_col, "throughput_bps"]].copy()
    totals = share_df.groupby(time_col)["throughput_bps"].transform("sum")
    share_df["share_percent"] = share_df["throughput_bps"].where(totals == 0, share_df["throughput_bps"] / totals * 100)
    share_df.loc[totals == 0, "share_percent"] = 0
    return share_df.sort_values([time_col, entity_col])


def interval_summary(intervals: pd.DataFrame, entity_col: str) -> pd.DataFrame:
    """Summarize throughput, delay, and loss/retransmission behavior per entity."""

    if intervals.empty or entity_col not in intervals.columns:
        return pd.DataFrame()

    records = []
    for entity, group in intervals.groupby(entity_col, dropna=False):
        duration = float(group["end_s"].max() - group["start_s"].min())
        total_bytes = float(group["bytes"].fillna(0).sum())
        avg_bps = (total_bytes * 8 / duration) if duration > 0 else None
        row = {
            entity_col: entity,
            "intervals": len(group),
            "duration_s": duration,
            "total_mib": total_bytes / (1024 * 1024),
            "avg_throughput_mbps": (avg_bps / 1_000_000) if avg_bps is not None else None,
            "mean_interval_mbps": group["throughput_mbps"].mean(),
            "p95_interval_mbps": group["throughput_mbps"].quantile(0.95),
            "retransmits": group.get("retransmits", pd.Series(dtype=float)).fillna(0).sum(),
        }
        if "rtt_ms" in group.columns and group["rtt_ms"].notna().any():
            row.update(
                {
                    "mean_rtt_ms": group["rtt_ms"].mean(),
                    "p95_rtt_ms": group["rtt_ms"].quantile(0.95),
                    "max_rtt_ms": group["rtt_ms"].max(),
                }
            )
        for col in _summary_metadata_columns(group, entity_col):
            row[col] = _first_non_null(group[col])
        records.append(row)

    return pd.DataFrame.from_records(records).sort_values(entity_col)


def experiment_summary(flow_summary: pd.DataFrame) -> pd.DataFrame:
    """Summarize a sweep condition across all flows that share experiment metadata."""

    if flow_summary.empty or "avg_throughput_mbps" not in flow_summary.columns:
        return pd.DataFrame()

    group_cols = _experiment_group_columns(flow_summary)
    grouped = flow_summary.groupby(group_cols, dropna=False) if group_cols else [((), flow_summary)]
    records = []
    for key, group in grouped:
        values = group["avg_throughput_mbps"].fillna(0)
        total = float(values.sum())
        record = {
            "flows": int(group["flow_id"].nunique()) if "flow_id" in group.columns else int(len(group)),
            "total_throughput_mbps": total,
            "avg_flow_throughput_mbps": float(values.mean()) if len(values) else None,
            "jain_fairness": jain_fairness(values),
            "retransmits": float(group["retransmits"].fillna(0).sum()) if "retransmits" in group.columns else None,
        }
        if group_cols:
            key_values = key if isinstance(key, tuple) else (key,)
            record.update(dict(zip(group_cols, key_values)))
        if "bottleneck_mbps" in group.columns and group["bottleneck_mbps"].notna().any():
            bottleneck = float(group["bottleneck_mbps"].dropna().iloc[0])
            record["link_utilization_percent"] = (total / bottleneck * 100) if bottleneck > 0 else None
        if "mean_rtt_ms" in group.columns and group["mean_rtt_ms"].notna().any():
            record["mean_rtt_ms"] = float(group["mean_rtt_ms"].mean())
        if "p95_rtt_ms" in group.columns and group["p95_rtt_ms"].notna().any():
            record["p95_rtt_ms"] = float(group["p95_rtt_ms"].mean())
        if "cc_algo" in group.columns:
            for cc_algo, cc_group in group.groupby("cc_algo", dropna=False):
                key_name = _slug(cc_algo)
                cc_total = float(cc_group["avg_throughput_mbps"].fillna(0).sum())
                record[f"throughput_{key_name}_mbps"] = cc_total
                record[f"share_{key_name}_percent"] = (cc_total / total * 100) if total > 0 else 0
        records.append(record)

    return pd.DataFrame.from_records(records)


def series_similarity(
    df: pd.DataFrame,
    *,
    entity_col: str = "stream_id",
    time_col: str = "interval_index",
    metrics: list[str] | None = None,
) -> pd.DataFrame:
    """Compare entity time series to identify truly overlapping lines."""

    if df.empty or entity_col not in df.columns or time_col not in df.columns:
        return pd.DataFrame()

    metrics = metrics or [
        "throughput_mbps",
        "transfer_mib",
        "retransmits",
        "cwnd_kib",
        "rtt_ms",
        "rttvar_ms",
        "pmtu_bytes",
    ]
    records = []
    for metric in metrics:
        if metric not in df.columns:
            continue
        pivot = df.pivot_table(index=time_col, columns=entity_col, values=metric, aggfunc="mean")
        if pivot.shape[1] < 2:
            continue
        for left, right in combinations(pivot.columns, 2):
            pair = pivot[[left, right]].dropna()
            if pair.empty:
                continue
            diff = pair[left] - pair[right]
            corr = _correlation(pair[left], pair[right])
            records.append(
                {
                    "metric": metric,
                    "left": left,
                    "right": right,
                    "points": len(pair),
                    "exact_equal": bool((diff == 0).all()),
                    "max_abs_diff": float(diff.abs().max()),
                    "mean_abs_diff": float(diff.abs().mean()),
                    "correlation": None if pd.isna(corr) else float(corr),
                }
            )
    return pd.DataFrame.from_records(records)


def _correlation(left: pd.Series, right: pd.Series) -> float | None:
    if left.std() == 0 or right.std() == 0:
        return None
    corr = left.corr(right)
    return None if pd.isna(corr) else float(corr)


def choose_time_column(df: pd.DataFrame, mode: str) -> str:
    if mode == "global" and "global_start_s" in df.columns and df["global_start_s"].notna().any():
        return "global_start_s"
    if mode == "offset" and "offset_start_s" in df.columns and df["offset_start_s"].notna().any():
        return "offset_start_s"
    if mode == "wall" and "absolute_start_s" in df.columns and df["absolute_start_s"].notna().any():
        return "absolute_start_s"
    return "start_s"


def time_bounds_columns(df: pd.DataFrame, mode: str) -> tuple[str, str]:
    start_col = choose_time_column(df, mode)
    if start_col.startswith("global_"):
        return start_col, "global_end_s"
    if start_col.startswith("offset_"):
        return start_col, "offset_end_s"
    if start_col.startswith("absolute_"):
        return start_col, "absolute_end_s"
    return start_col, "end_s"


def _first_value_columns(df: pd.DataFrame, excluded: set[str]) -> list[str]:
    columns = []
    for col in df.columns:
        if col in excluded or col.startswith("_"):
            continue
        columns.append(col)
    return columns


def _summary_metadata_columns(group: pd.DataFrame, entity_col: str) -> list[str]:
    excluded = SUMMARY_MEASUREMENT_COLUMNS | MEASUREMENT_COLUMNS | STREAM_DETAIL_COLUMNS | {entity_col}
    return _first_value_columns(group, excluded)


def _experiment_group_columns(flow_summary: pd.DataFrame) -> list[str]:
    excluded = (
        SUMMARY_MEASUREMENT_COLUMNS
        | {
            "source_file",
            "run_id",
            "flow_id",
            "flow_label",
            "stream_id",
            "cc_algo",
            "protocol",
            "reverse",
            "num_streams",
            "start_offset_s",
            "rtt_config_ms",
        }
    )
    return _first_value_columns(flow_summary, excluded)


def _fairness_group_columns(df: pd.DataFrame, entity_col: str, time_col: str) -> list[str]:
    excluded = (
        MEASUREMENT_COLUMNS
        | STREAM_DETAIL_COLUMNS
        | {
            entity_col,
            time_col,
            "source_file",
            "run_id",
            "flow_id",
            "flow_label",
            "stream_id",
            "cc_algo",
            "protocol",
            "reverse",
            "num_streams",
            "start_offset_s",
            "rtt_config_ms",
            "time_bin_index",
            "time_bin_start_s",
            "time_bin_end_s",
            "time_bin_midpoint_s",
            "throughput_bps",
            "throughput_mbps",
            "omitted",
        }
    )
    return _first_value_columns(df, excluded)


def _first_non_null(series: pd.Series) -> object:
    non_null = series.dropna()
    return None if non_null.empty else non_null.iloc[0]


def _slug(value: object) -> str:
    text = str(value if value is not None and not pd.isna(value) else "unknown").strip().lower()
    chars = [char if char.isalnum() else "_" for char in text]
    slug = "_".join(part for part in "".join(chars).split("_") if part)
    return slug or "unknown"


def _grid_origin(value: float, bin_s: float) -> float:
    if value >= 0:
        return (value // bin_s) * bin_s
    return -((-value // bin_s) * bin_s)


def _value(row: pd.Series, col: str) -> float | None:
    if col not in row.index or pd.isna(row[col]):
        return None
    return float(row[col])


def _min_share_percent(values: pd.Series) -> float | None:
    total = float(values.sum())
    if total <= 0 or values.empty:
        return None
    return float(values.min() / total * 100)


def _max_share_percent(values: pd.Series) -> float | None:
    total = float(values.sum())
    if total <= 0 or values.empty:
        return None
    return float(values.max() / total * 100)
