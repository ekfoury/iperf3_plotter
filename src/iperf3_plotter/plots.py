from __future__ import annotations

import os
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path

warnings.filterwarnings("ignore", message="Pandas requires version .*", category=UserWarning)

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "iperf3_plotter_mpl"))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from .metrics import (
    bandwidth_share,
    choose_time_column,
    fairness_over_time,
    flow_aggregates,
    interval_summary,
    resample_time_bins,
    total_from_bins,
    total_aggregate,
)


@dataclass(frozen=True)
class PlotArtifact:
    name: str
    title: str
    path: Path
    description: str


def generate_plots(
    intervals: pd.DataFrame,
    summaries: pd.DataFrame,
    out_dir: Path,
    *,
    formats: list[str] | None = None,
    time_mode: str = "relative",
) -> list[PlotArtifact]:
    """Generate the core TCP/iperf3 plot suite."""

    if intervals.empty:
        return []

    formats = formats or ["png"]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[PlotArtifact] = []

    time_col = choose_time_column(intervals, time_mode)
    flow_df = flow_aggregates(intervals)
    flow_time_col = choose_time_column(flow_df, time_mode)
    stream_bins = resample_time_bins(intervals, entity_col="stream_id", time_mode=time_mode)
    flow_bins = resample_time_bins(flow_df, entity_col="flow_id", time_mode=time_mode)
    transfer_df = flow_bins if not flow_bins.empty else flow_df
    transfer_time_col = "time_bin_start_s" if "time_bin_start_s" in transfer_df.columns else flow_time_col

    artifacts.extend(
        _line_plot(
            intervals,
            x=time_col,
            y="throughput_mbps",
            group="stream_id",
            out_dir=out_dir,
            basename="throughput_streams",
            title="Per-stream throughput",
            ylabel="Throughput (Mbps)",
            formats=formats,
            description="Throughput for each iperf3 stream over time.",
        )
    )
    artifacts.extend(
        _deviation_plot(
            intervals,
            x=time_col,
            y="throughput_mbps",
            group="stream_id",
            out_dir=out_dir,
            basename="throughput_stream_deviation",
            title="Per-stream throughput deviation",
            ylabel="Deviation from interval mean (Mbps)",
            formats=formats,
            description="How far each stream is from the interval mean; useful when raw throughput lines overlap.",
        )
    )

    artifacts.extend(
        _line_plot(
            transfer_df,
            x=transfer_time_col,
            y="throughput_mbps",
            group="flow_id",
            out_dir=out_dir,
            basename="throughput_flows",
            title="Per-transfer aggregate throughput",
            ylabel="Throughput (Mbps)",
            formats=formats,
            description="Parallel streams summed into their parent transfer.",
        )
    )

    artifacts.extend(
        _line_plot_if_present(
            transfer_df,
            x=transfer_time_col,
            y="rtt_ms",
            group="flow_id",
            out_dir=out_dir,
            basename="rtt_flows",
            title="Per-transfer RTT",
            ylabel="RTT (ms)",
            formats=formats,
            description="RTT averaged across parallel streams within each transfer.",
        )
    )
    artifacts.extend(
        _line_plot_if_present(
            transfer_df,
            x=transfer_time_col,
            y="rttvar_ms",
            group="flow_id",
            out_dir=out_dir,
            basename="rttvar_flows",
            title="Per-transfer RTT variation",
            ylabel="RTT variation (ms)",
            formats=formats,
            description="RTT variation averaged across parallel streams within each transfer.",
        )
    )
    artifacts.extend(
        _line_plot_if_present(
            transfer_df,
            x=transfer_time_col,
            y="cwnd_kib",
            group="flow_id",
            out_dir=out_dir,
            basename="cwnd_flows",
            title="Per-transfer congestion window",
            ylabel="Congestion window (KiB)",
            formats=formats,
            description="Maximum stream congestion window observed within each transfer interval.",
        )
    )
    artifacts.extend(
        _line_plot_if_present(
            transfer_df,
            x=transfer_time_col,
            y="retransmits",
            group="flow_id",
            out_dir=out_dir,
            basename="retransmits_flows",
            title="Per-transfer retransmits",
            ylabel="Retransmits",
            formats=formats,
            description="Retransmits summed across parallel streams within each transfer.",
        )
    )
    artifacts.extend(
        _cumulative_plot(
            transfer_df,
            x=transfer_time_col,
            y="retransmits",
            group="flow_id",
            out_dir=out_dir,
            basename="retransmits_flows_cumulative",
            title="Per-transfer cumulative retransmits",
            ylabel="Retransmits",
            formats=formats,
            description="Cumulative retransmits summed across parallel streams for each transfer.",
        )
    )
    artifacts.extend(
        _cumulative_plot(
            transfer_df,
            x=transfer_time_col,
            y="transfer_mib",
            group="flow_id",
            out_dir=out_dir,
            basename="bytes_flows_cumulative",
            title="Per-transfer cumulative transferred data",
            ylabel="Transferred data (MiB)",
            formats=formats,
            description="Cumulative transferred data summed across parallel streams for each transfer.",
        )
    )
    artifacts.extend(
        _line_plot_if_present(
            transfer_df,
            x=transfer_time_col,
            y="pmtu_bytes",
            group="flow_id",
            out_dir=out_dir,
            basename="pmtu_flows",
            title="Per-transfer path MTU",
            ylabel="PMTU (bytes)",
            formats=formats,
            description="Path MTU averaged across parallel streams within each transfer.",
        )
    )

    total_df = total_from_bins(flow_bins) if not flow_bins.empty else total_aggregate(flow_df, flow_time_col)
    artifacts.extend(
        _single_line_plot(
            total_df,
            x="time_bin_start_s" if "time_bin_start_s" in total_df.columns else flow_time_col,
            y="throughput_mbps",
            out_dir=out_dir,
            basename="throughput_total",
            title="Total aggregate throughput",
            ylabel="Throughput (Mbps)",
            formats=formats,
            description="Total throughput across all active flows.",
        )
    )

    artifacts.extend(
        _maybe_share_plot(
            flow_df,
            entity_col="flow_id",
            time_col=flow_time_col,
            binned_df=flow_bins,
            out_dir=out_dir,
            basename="bandwidth_share_flows",
            title="Flow bandwidth share",
            formats=formats,
            description="Percentage of aggregate throughput held by each active flow.",
        )
    )
    artifacts.extend(
        _maybe_fairness_plot(
            flow_df,
            entity_col="flow_id",
            time_col=flow_time_col,
            binned_df=flow_bins,
            out_dir=out_dir,
            basename="fairness_flows",
            title="Flow fairness over time",
            formats=formats,
            description="Jain fairness index among active flows.",
        )
    )
    artifacts.extend(
        _maybe_fairness_plot(
            intervals,
            entity_col="stream_id",
            time_col=time_col,
            binned_df=stream_bins,
            out_dir=out_dir,
            basename="fairness_streams",
            title="Parallel-stream fairness over time",
            formats=formats,
            description="Jain fairness index among active streams.",
        )
    )

    artifacts.extend(
        _line_plot_if_present(
            intervals,
            x=time_col,
            y="rtt_ms",
            group="stream_id",
            out_dir=out_dir,
            basename="rtt_streams",
            title="RTT over time",
            ylabel="RTT (ms)",
            formats=formats,
            description="Round-trip time reported by iperf3 for each stream.",
        )
    )
    artifacts.extend(
        _line_plot_if_present(
            intervals,
            x=time_col,
            y="rttvar_ms",
            group="stream_id",
            out_dir=out_dir,
            basename="rttvar_streams",
            title="RTT variation over time",
            ylabel="RTT variation (ms)",
            formats=formats,
            description="RTT variation reported by iperf3 for each stream.",
        )
    )
    artifacts.extend(
        _line_plot_if_present(
            intervals,
            x=time_col,
            y="cwnd_kib",
            group="stream_id",
            out_dir=out_dir,
            basename="cwnd_streams",
            title="Congestion window over time",
            ylabel="Congestion window (KiB)",
            formats=formats,
            description="Sender congestion window reported by iperf3.",
        )
    )
    artifacts.extend(
        _line_plot_if_present(
            intervals,
            x=time_col,
            y="retransmits",
            group="stream_id",
            out_dir=out_dir,
            basename="retransmits_streams",
            title="Retransmits per interval",
            ylabel="Retransmits",
            formats=formats,
            description="TCP retransmits reported for each interval.",
        )
    )
    artifacts.extend(
        _cumulative_plot(
            intervals,
            x=time_col,
            y="retransmits",
            group="stream_id",
            out_dir=out_dir,
            basename="retransmits_cumulative",
            title="Cumulative retransmits",
            ylabel="Retransmits",
            formats=formats,
            description="Cumulative retransmits per stream.",
        )
    )
    artifacts.extend(
        _cumulative_plot(
            intervals,
            x=time_col,
            y="transfer_mib",
            group="stream_id",
            out_dir=out_dir,
            basename="bytes_cumulative",
            title="Cumulative transferred data",
            ylabel="Transferred data (MiB)",
            formats=formats,
            description="Cumulative transferred data per stream.",
        )
    )
    artifacts.extend(
        _line_plot_if_present(
            intervals,
            x=time_col,
            y="pmtu_bytes",
            group="stream_id",
            out_dir=out_dir,
            basename="pmtu_streams",
            title="Path MTU over time",
            ylabel="PMTU (bytes)",
            formats=formats,
            description="Path MTU reported by iperf3.",
        )
    )

    artifacts.extend(
        _summary_bar_plot(
            intervals,
            out_dir=out_dir,
            formats=formats,
        )
    )
    artifacts.extend(
        _throughput_delay_scatter(
            intervals,
            out_dir=out_dir,
            formats=formats,
        )
    )

    return artifacts


def _line_plot_if_present(
    df: pd.DataFrame,
    *,
    x: str,
    y: str,
    group: str,
    out_dir: Path,
    basename: str,
    title: str,
    ylabel: str,
    formats: list[str],
    description: str,
) -> list[PlotArtifact]:
    if y not in df.columns or not df[y].notna().any():
        return []
    return _line_plot(
        df,
        x=x,
        y=y,
        group=group,
        out_dir=out_dir,
        basename=basename,
        title=title,
        ylabel=ylabel,
        formats=formats,
        description=description,
    )


def _line_plot(
    df: pd.DataFrame,
    *,
    x: str,
    y: str,
    group: str,
    out_dir: Path,
    basename: str,
    title: str,
    ylabel: str,
    formats: list[str],
    description: str,
) -> list[PlotArtifact]:
    if df.empty or x not in df.columns or y not in df.columns or group not in df.columns:
        return []

    plot_df = df.dropna(subset=[x, y]).sort_values([group, x])
    if plot_df.empty:
        return []

    fig, ax = plt.subplots(figsize=(10, 5.5))
    for label, group_df in plot_df.groupby(group, dropna=False):
        ax.plot(group_df[x], group_df[y], linewidth=1.8, label=str(label))

    _finish_axis(ax, title=title, xlabel=_time_label(x), ylabel=ylabel)
    _legend(ax, len(plot_df[group].unique()))
    return _save(fig, out_dir, basename, title, description, formats)


def _single_line_plot(
    df: pd.DataFrame,
    *,
    x: str,
    y: str,
    out_dir: Path,
    basename: str,
    title: str,
    ylabel: str,
    formats: list[str],
    description: str,
) -> list[PlotArtifact]:
    if df.empty or x not in df.columns or y not in df.columns:
        return []

    plot_df = df.dropna(subset=[x, y]).sort_values(x)
    if plot_df.empty:
        return []

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.plot(plot_df[x], plot_df[y], linewidth=2.2, color="#1f77b4")
    _finish_axis(ax, title=title, xlabel=_time_label(x), ylabel=ylabel)
    return _save(fig, out_dir, basename, title, description, formats)


def _deviation_plot(
    df: pd.DataFrame,
    *,
    x: str,
    y: str,
    group: str,
    out_dir: Path,
    basename: str,
    title: str,
    ylabel: str,
    formats: list[str],
    description: str,
) -> list[PlotArtifact]:
    if df.empty or x not in df.columns or y not in df.columns or group not in df.columns:
        return []

    plot_df = df.dropna(subset=[x, y]).copy().sort_values([x, group])
    if plot_df.empty or plot_df[group].nunique() < 2:
        return []

    interval_mean = plot_df.groupby(x)[y].transform("mean")
    plot_df["deviation"] = plot_df[y] - interval_mean

    fig, ax = plt.subplots(figsize=(10, 5.5))
    for label, group_df in plot_df.groupby(group, dropna=False):
        ax.plot(group_df[x], group_df["deviation"], linewidth=1.8, label=str(label))
    ax.axhline(0, linestyle="--", linewidth=1.0, color="#444444", alpha=0.65)
    _finish_axis(ax, title=title, xlabel=_time_label(x), ylabel=ylabel)
    _legend(ax, len(plot_df[group].unique()))
    return _save(fig, out_dir, basename, title, description, formats)


def _maybe_share_plot(
    df: pd.DataFrame,
    *,
    entity_col: str,
    time_col: str,
    binned_df: pd.DataFrame | None = None,
    out_dir: Path,
    basename: str,
    title: str,
    formats: list[str],
    description: str,
) -> list[PlotArtifact]:
    if df.empty or entity_col not in df.columns or df[entity_col].nunique() < 2:
        return []

    source_df = binned_df if binned_df is not None and not binned_df.empty else df
    source_time_col = "time_bin_start_s" if "time_bin_start_s" in source_df.columns else time_col
    share_df = bandwidth_share(source_df, entity_col, source_time_col)
    if share_df.empty:
        return []

    pivot = share_df.pivot_table(
        index=source_time_col,
        columns=entity_col,
        values="share_percent",
        aggfunc="mean",
    ).fillna(0)
    if pivot.empty:
        return []

    fig, ax = plt.subplots(figsize=(10, 5.5))
    pivot.plot.area(ax=ax, stacked=True, linewidth=0, alpha=0.88)
    ax.set_ylim(0, 100)
    _finish_axis(ax, title=title, xlabel=_time_label(source_time_col), ylabel="Bandwidth share (%)")
    _legend(ax, len(pivot.columns))
    return _save(fig, out_dir, basename, title, description, formats)


def _maybe_fairness_plot(
    df: pd.DataFrame,
    *,
    entity_col: str,
    time_col: str,
    binned_df: pd.DataFrame | None = None,
    out_dir: Path,
    basename: str,
    title: str,
    formats: list[str],
    description: str,
) -> list[PlotArtifact]:
    if df.empty or entity_col not in df.columns or df[entity_col].nunique() < 2:
        return []

    source_df = binned_df if binned_df is not None and not binned_df.empty else df
    source_time_col = "time_bin_start_s" if "time_bin_start_s" in source_df.columns else time_col
    fairness_df = fairness_over_time(source_df, entity_col, source_time_col)
    if fairness_df.empty:
        return []

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.plot(fairness_df[source_time_col], fairness_df["jain_fairness"], linewidth=2.0, color="#2ca02c")
    ax.axhline(1.0, linestyle="--", linewidth=1.0, color="#444444", alpha=0.6)
    ax.set_ylim(0, 1.05)
    _finish_axis(ax, title=title, xlabel=_time_label(source_time_col), ylabel="Jain fairness index")
    return _save(fig, out_dir, basename, title, description, formats)


def _cumulative_plot(
    df: pd.DataFrame,
    *,
    x: str,
    y: str,
    group: str,
    out_dir: Path,
    basename: str,
    title: str,
    ylabel: str,
    formats: list[str],
    description: str,
) -> list[PlotArtifact]:
    if df.empty or x not in df.columns or y not in df.columns or group not in df.columns:
        return []

    plot_df = df.dropna(subset=[x]).copy().sort_values([group, x])
    if plot_df.empty or not plot_df[y].notna().any():
        return []
    plot_df["cumulative_value"] = plot_df.groupby(group)[y].transform(lambda values: values.fillna(0).cumsum())

    fig, ax = plt.subplots(figsize=(10, 5.5))
    for label, group_df in plot_df.groupby(group, dropna=False):
        ax.plot(group_df[x], group_df["cumulative_value"], linewidth=1.8, label=str(label))

    _finish_axis(ax, title=title, xlabel=_time_label(x), ylabel=ylabel)
    _legend(ax, len(plot_df[group].unique()))
    return _save(fig, out_dir, basename, title, description, formats)


def _summary_bar_plot(
    intervals: pd.DataFrame,
    *,
    out_dir: Path,
    formats: list[str],
) -> list[PlotArtifact]:
    summary = interval_summary(intervals, "stream_id")
    if summary.empty or "avg_throughput_mbps" not in summary.columns:
        return []

    fig, ax = plt.subplots(figsize=(10, 5.5))
    summary = summary.sort_values("avg_throughput_mbps", ascending=True)
    ax.barh(summary["stream_id"].astype(str), summary["avg_throughput_mbps"], color="#1f77b4")
    _finish_axis(
        ax,
        title="Average throughput by stream",
        xlabel="Average throughput (Mbps)",
        ylabel="Stream",
    )
    return _save(
        fig,
        out_dir,
        "summary_stream_throughput",
        "Average throughput by stream",
        "Average throughput for each stream over its active duration.",
        formats,
    )


def _throughput_delay_scatter(
    intervals: pd.DataFrame,
    *,
    out_dir: Path,
    formats: list[str],
) -> list[PlotArtifact]:
    if "rtt_ms" not in intervals.columns or not intervals["rtt_ms"].notna().any():
        return []

    summary = interval_summary(intervals, "stream_id")
    required = {"avg_throughput_mbps", "p95_rtt_ms", "stream_id"}
    if summary.empty or not required.issubset(summary.columns):
        return []

    plot_df = summary.dropna(subset=["avg_throughput_mbps", "p95_rtt_ms"])
    if plot_df.empty:
        return []

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(plot_df["p95_rtt_ms"], plot_df["avg_throughput_mbps"], s=58, color="#d62728", alpha=0.85)
    if len(plot_df) <= 10:
        for _, row in plot_df.iterrows():
            ax.annotate(
                str(row["stream_id"]),
                (row["p95_rtt_ms"], row["avg_throughput_mbps"]),
                textcoords="offset points",
                xytext=(5, 5),
                fontsize=8,
            )
    _finish_axis(
        ax,
        title="Throughput-delay tradeoff",
        xlabel="95th percentile RTT (ms)",
        ylabel="Average throughput (Mbps)",
    )
    return _save(
        fig,
        out_dir,
        "throughput_delay_scatter",
        "Throughput-delay tradeoff",
        "Average throughput versus 95th percentile RTT for each stream.",
        formats,
    )


def _finish_axis(ax: plt.Axes, *, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, which="major", linestyle=":", linewidth=0.8, alpha=0.7)
    ax.margins(x=0.02)


def _legend(ax: plt.Axes, item_count: int) -> None:
    if item_count <= 1:
        return
    ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False, fontsize=8)


def _time_label(time_col: str) -> str:
    if time_col.startswith("time_bin_"):
        return "Unified time bin start (s)"
    if time_col.startswith("global_"):
        return "Unified experiment time (s)"
    if time_col.startswith("offset_"):
        return "Offset experiment time (s)"
    if time_col.startswith("absolute_"):
        return "Unix time (s)"
    return "Time since run start (s)"


def _save(
    fig: plt.Figure,
    out_dir: Path,
    basename: str,
    title: str,
    description: str,
    formats: list[str],
) -> list[PlotArtifact]:
    fig.tight_layout()
    artifacts: list[PlotArtifact] = []
    for fmt in formats:
        clean_format = fmt.lower().lstrip(".")
        path = out_dir / f"{basename}.{clean_format}"
        fig.savefig(path, dpi=160, bbox_inches="tight")
        artifacts.append(PlotArtifact(name=basename, title=title, path=path, description=description))
    plt.close(fig)
    return artifacts
