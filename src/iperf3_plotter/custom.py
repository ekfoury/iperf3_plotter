from __future__ import annotations

import json
import os
import tempfile
import warnings
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "iperf3_plotter_mpl"))
warnings.filterwarnings("ignore", message="Pandas requires version .*", category=UserWarning)

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import yaml

from .metrics import (
    bandwidth_share,
    experiment_summary,
    fairness_over_time,
    flow_aggregates,
    interval_summary,
    resample_time_bins,
    total_aggregate,
    total_from_bins,
)
from .plots import PlotArtifact


class PlotSpecError(ValueError):
    """Raised when a custom plot specification cannot be rendered."""


def load_plot_specs(path: Path) -> list[dict[str, Any]]:
    """Load a YAML or JSON plot specification file."""

    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PlotSpecError(f"{path} is not valid YAML: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PlotSpecError(f"{path} is not valid JSON: {exc}") from exc

    if isinstance(data, dict):
        plots = data.get("plots")
    else:
        plots = data

    if not isinstance(plots, list) or not all(isinstance(item, dict) for item in plots):
        raise PlotSpecError("Plot spec must be a list or an object with a 'plots' list")
    return plots


def generate_custom_plots(
    intervals: pd.DataFrame,
    summaries: pd.DataFrame,
    runs: pd.DataFrame,
    out_dir: Path,
    *,
    spec_path: Path,
    formats: list[str] | None = None,
    time_mode: str = "relative",
) -> list[PlotArtifact]:
    """Render user-defined plots from normalized and derived iperf3 tables."""

    specs = load_plot_specs(spec_path)
    sources = build_plot_sources(intervals, summaries, runs, time_mode=time_mode)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    formats = formats or ["png"]

    artifacts: list[PlotArtifact] = []
    for index, spec in enumerate(specs, start=1):
        artifacts.extend(_render_spec(spec, index, sources, out_dir, formats))
    return artifacts


def build_plot_sources(
    intervals: pd.DataFrame,
    summaries: pd.DataFrame,
    runs: pd.DataFrame,
    *,
    time_mode: str = "relative",
) -> dict[str, pd.DataFrame]:
    """Build named tables that plot specs can reference."""

    flow_df = flow_aggregates(intervals)
    stream_bins = resample_time_bins(intervals, entity_col="stream_id", time_mode=time_mode)
    flow_bins = resample_time_bins(flow_df, entity_col="flow_id", time_mode=time_mode) if not flow_df.empty else pd.DataFrame()
    stream_summary = interval_summary(intervals, "stream_id")
    flow_summary = interval_summary(flow_df, "flow_id") if not flow_df.empty else pd.DataFrame()
    stream_fairness = fairness_over_time(stream_bins, "stream_id", "time_bin_start_s") if not stream_bins.empty else pd.DataFrame()
    flow_fairness = fairness_over_time(flow_bins, "flow_id", "time_bin_start_s") if not flow_bins.empty else pd.DataFrame()
    stream_share = bandwidth_share(stream_bins, "stream_id", "time_bin_start_s") if not stream_bins.empty else pd.DataFrame()
    flow_share = bandwidth_share(flow_bins, "flow_id", "time_bin_start_s") if not flow_bins.empty else pd.DataFrame()
    total_bins = total_from_bins(flow_bins) if not flow_bins.empty else pd.DataFrame()
    total_intervals = total_aggregate(flow_df, "start_s") if not flow_df.empty else pd.DataFrame()

    return {
        "intervals": intervals,
        "summaries": summaries,
        "runs": runs,
        "flow_intervals": flow_df,
        "stream_time_bins": stream_bins,
        "flow_time_bins": flow_bins,
        "stream_summary": stream_summary,
        "flow_summary": flow_summary,
        "stream_fairness": stream_fairness,
        "flow_fairness": flow_fairness,
        "stream_share": stream_share,
        "flow_share": flow_share,
        "total_time_bins": total_bins,
        "total_intervals": total_intervals,
        "experiment_summary": experiment_summary(flow_summary),
    }


def _render_spec(
    spec: dict[str, Any],
    index: int,
    sources: dict[str, pd.DataFrame],
    out_dir: Path,
    formats: list[str],
) -> list[PlotArtifact]:
    name = str(spec.get("name") or f"custom_plot_{index}")
    kind = str(spec.get("kind") or "").strip().lower()
    if not kind:
        raise PlotSpecError(f"{name}: missing plot kind")

    source_name = str(spec.get("source") or "intervals")
    if source_name not in sources:
        valid = ", ".join(sorted(sources))
        raise PlotSpecError(f"{name}: unknown source '{source_name}'. Valid sources: {valid}")

    df = _apply_filters(sources[source_name].copy(), spec)
    if df.empty:
        return []

    renderer = {
        "cdf": _plot_cdf,
        "ccdf": _plot_cdf,
        "hist": _plot_histogram,
        "histogram": _plot_histogram,
        "line": _plot_line,
        "time_series": _plot_line,
        "timeseries": _plot_line,
        "scatter": _plot_scatter,
        "bar": _plot_bar,
        "box": _plot_box,
        "boxplot": _plot_box,
        "heatmap": _plot_heatmap,
    }.get(kind)
    if renderer is None:
        raise PlotSpecError(f"{name}: unsupported plot kind '{kind}'")

    artifacts: list[PlotArtifact] = []
    facet_cols = _as_list(spec.get("facet_by"))
    _require_columns(df, facet_cols, name)
    facets = _facets(df, facet_cols)
    for facet_suffix, facet_title, facet_df in facets:
        facet_spec = dict(spec)
        facet_spec["_facet_title"] = facet_title
        basename = _slug("_".join(part for part in [name, facet_suffix] if part))
        artifacts.extend(renderer(facet_df, facet_spec, basename, out_dir, formats))
    return artifacts


def _plot_cdf(
    df: pd.DataFrame,
    spec: dict[str, Any],
    basename: str,
    out_dir: Path,
    formats: list[str],
) -> list[PlotArtifact]:
    metric = _metric(spec)
    name = str(spec.get("name") or basename)
    _require_columns(df, [metric], name)
    group_cols = _as_list(spec.get("group_by"))
    _require_columns(df, group_cols, name)

    ccdf = str(spec.get("kind")).lower() == "ccdf"
    fig, ax = plt.subplots(figsize=_figsize(spec, (8.0, 5.2)))
    grouped = _grouped(df, group_cols)
    for index, (label, group_df) in enumerate(grouped):
        values = pd.to_numeric(group_df[metric], errors="coerce").dropna().sort_values()
        if values.empty:
            continue
        probabilities = pd.Series(range(1, len(values) + 1), dtype=float) / len(values)
        y_values = 1 - probabilities if ccdf else probabilities
        ax.step(
            values,
            y_values,
            where="post",
            linewidth=_float_option(spec, "linewidth", "line_width", default=1.9),
            linestyle=str(_option(spec, "linestyle", "line_style", default="-")),
            color=_series_color(spec, label, index, len(grouped)),
            alpha=_float_option(spec, "alpha", default=1.0),
            label=label,
        )

    title = _title(spec, f"{_pretty(metric)} {'CCDF' if ccdf else 'CDF'}")
    _finish_axis(ax, spec, title=title, xlabel=_xlabel(spec, _pretty(metric)), ylabel=_ylabel(spec, "Probability"))
    _legend(ax, len(grouped), spec)
    return _save(fig, out_dir, basename, title, _description(spec, "Custom distribution plot."), formats, spec)


def _plot_histogram(
    df: pd.DataFrame,
    spec: dict[str, Any],
    basename: str,
    out_dir: Path,
    formats: list[str],
) -> list[PlotArtifact]:
    metric = _metric(spec)
    name = str(spec.get("name") or basename)
    group_cols = _as_list(spec.get("group_by"))
    _require_columns(df, [metric, *group_cols], name)

    fig, ax = plt.subplots(figsize=_figsize(spec, (8.0, 5.2)))
    grouped = _grouped(df, group_cols)
    bins = int(spec.get("bins", 30))
    for index, (label, group_df) in enumerate(grouped):
        values = pd.to_numeric(group_df[metric], errors="coerce").dropna()
        if values.empty:
            continue
        ax.hist(
            values,
            bins=bins,
            alpha=_float_option(spec, "alpha", default=0.45),
            color=_series_color(spec, label, index, len(grouped)),
            label=label,
        )

    title = _title(spec, f"{_pretty(metric)} histogram")
    _finish_axis(ax, spec, title=title, xlabel=_xlabel(spec, _pretty(metric)), ylabel=_ylabel(spec, "Count"))
    _legend(ax, len(grouped), spec)
    return _save(fig, out_dir, basename, title, _description(spec, "Custom histogram."), formats, spec)


def _plot_line(
    df: pd.DataFrame,
    spec: dict[str, Any],
    basename: str,
    out_dir: Path,
    formats: list[str],
) -> list[PlotArtifact]:
    x = _required_field(spec, "x")
    y = _metric(spec)
    name = str(spec.get("name") or basename)
    group_cols = _as_list(spec.get("group_by"))
    _require_columns(df, [x, y, *group_cols], name)

    plot_df = _aggregate_for_plot(df, [x, *group_cols], y, _aggregate(spec, "mean"))
    plot_df = _label_groups(plot_df, group_cols)
    fig, ax = plt.subplots(figsize=_figsize(spec, (9.0, 5.2)))
    grouped = _grouped(plot_df, ["_series_label"] if group_cols else [])
    for index, (label, group_df) in enumerate(grouped):
        group_df = group_df.sort_values(x)
        ax.plot(
            group_df[x],
            group_df[y],
            linewidth=_float_option(spec, "linewidth", "line_width", default=1.9),
            linestyle=str(_option(spec, "linestyle", "line_style", default="-")),
            marker=_marker(spec),
            markersize=_float_option(spec, "markersize", "marker_size", default=6.0),
            color=_series_color(spec, label, index, len(grouped)),
            alpha=_float_option(spec, "alpha", default=1.0),
            label=label,
        )

    title = _title(spec, f"{_pretty(y)} by {_pretty(x)}")
    _finish_axis(ax, spec, title=title, xlabel=_xlabel(spec, _pretty(x)), ylabel=_ylabel(spec, _pretty(y)))
    _legend(ax, plot_df["_series_label"].nunique() if "_series_label" in plot_df.columns else 1, spec)
    return _save(fig, out_dir, basename, title, _description(spec, "Custom line plot."), formats, spec)


def _plot_scatter(
    df: pd.DataFrame,
    spec: dict[str, Any],
    basename: str,
    out_dir: Path,
    formats: list[str],
) -> list[PlotArtifact]:
    x = _required_field(spec, "x")
    y = _required_field(spec, "y")
    name = str(spec.get("name") or basename)
    group_cols = _as_list(spec.get("group_by"))
    _require_columns(df, [x, y, *group_cols], name)

    if spec.get("aggregate"):
        df = _aggregate_for_plot(df, [x, *group_cols], y, _aggregate(spec, "mean"))
    plot_df = _label_groups(df.dropna(subset=[x, y]).copy(), group_cols)
    fig, ax = plt.subplots(figsize=_figsize(spec, (8.0, 5.8)))
    grouped = _grouped(plot_df, ["_series_label"] if group_cols else [])
    for index, (label, group_df) in enumerate(grouped):
        ax.scatter(
            group_df[x],
            group_df[y],
            s=_float_option(spec, "size", "marker_size", "markersize", default=42),
            alpha=_float_option(spec, "alpha", default=0.82),
            color=_series_color(spec, label, index, len(grouped)),
            marker=_marker(spec) or "o",
            label=label,
        )

    title = _title(spec, f"{_pretty(y)} vs {_pretty(x)}")
    _finish_axis(ax, spec, title=title, xlabel=_xlabel(spec, _pretty(x)), ylabel=_ylabel(spec, _pretty(y)))
    _legend(ax, plot_df["_series_label"].nunique() if "_series_label" in plot_df.columns else 1, spec)
    return _save(fig, out_dir, basename, title, _description(spec, "Custom scatter plot."), formats, spec)


def _plot_bar(
    df: pd.DataFrame,
    spec: dict[str, Any],
    basename: str,
    out_dir: Path,
    formats: list[str],
) -> list[PlotArtifact]:
    x = _required_field(spec, "x")
    y = _metric(spec)
    name = str(spec.get("name") or basename)
    group_cols = _as_list(spec.get("group_by"))
    _require_columns(df, [x, y, *group_cols], name)

    plot_df = _aggregate_for_plot(df, [x, *group_cols], y, _aggregate(spec, "mean"))
    plot_df = _label_groups(plot_df, group_cols)
    fig, ax = plt.subplots(figsize=_figsize(spec, (9.0, 5.4)))
    if group_cols:
        pivot = plot_df.pivot_table(index=x, columns="_series_label", values=y, aggfunc="mean")
        pivot = _sort_axes(pivot)
        pivot.plot(kind="bar", ax=ax, width=_float_option(spec, "bar_width", default=0.82), color=_series_colors(spec, list(pivot.columns)))
        _legend(ax, len(pivot.columns), spec)
    else:
        plot_df = _sort_values(plot_df, x)
        ax.bar(plot_df[x].astype(str), plot_df[y], color=_series_color(spec, "", 0, 1), width=_float_option(spec, "bar_width", default=0.82), alpha=_float_option(spec, "alpha", default=1.0))

    title = _title(spec, f"{_pretty(y)} by {_pretty(x)}")
    _finish_axis(ax, spec, title=title, xlabel=_xlabel(spec, _pretty(x)), ylabel=_ylabel(spec, _pretty(y)))
    return _save(fig, out_dir, basename, title, _description(spec, "Custom bar plot."), formats, spec)


def _plot_box(
    df: pd.DataFrame,
    spec: dict[str, Any],
    basename: str,
    out_dir: Path,
    formats: list[str],
) -> list[PlotArtifact]:
    y = _metric(spec)
    category_cols = _as_list(spec.get("group_by")) or _as_list(spec.get("x"))
    name = str(spec.get("name") or basename)
    _require_columns(df, [y, *category_cols], name)

    plot_df = _label_groups(df.dropna(subset=[y]).copy(), category_cols)
    grouped = list(_grouped(plot_df, ["_series_label"] if category_cols else []))
    labels = [label for label, _ in grouped]
    values = [pd.to_numeric(group_df[y], errors="coerce").dropna() for _, group_df in grouped]
    labels_values = [(label, vals) for label, vals in zip(labels, values) if not vals.empty]
    if not labels_values:
        return []

    fig, ax = plt.subplots(figsize=_figsize(spec, (9.0, 5.4)))
    box = ax.boxplot(
        [vals for _, vals in labels_values],
        labels=[label for label, _ in labels_values],
        showfliers=_bool_option(spec, "show_fliers", default=False),
        patch_artist=True,
    )
    box_colors = _series_colors(spec, [label for label, _ in labels_values]) or [None] * len(labels_values)
    for patch, color in zip(box["boxes"], box_colors):
        if color:
            patch.set_facecolor(color)
        patch.set_alpha(_float_option(spec, "alpha", default=0.72))
    title = _title(spec, f"{_pretty(y)} distribution")
    _finish_axis(ax, spec, title=title, xlabel=_xlabel(spec, _pretty(" / ".join(category_cols)) if category_cols else ""), ylabel=_ylabel(spec, _pretty(y)))
    ax.tick_params(axis="x", labelrotation=_float_option(spec, "x_tick_rotation", "tick_rotation", default=30))
    return _save(fig, out_dir, basename, title, _description(spec, "Custom box plot."), formats, spec)


def _plot_heatmap(
    df: pd.DataFrame,
    spec: dict[str, Any],
    basename: str,
    out_dir: Path,
    formats: list[str],
) -> list[PlotArtifact]:
    x = _required_field(spec, "x")
    y = _required_field(spec, "y")
    value = _metric(spec)
    name = str(spec.get("name") or basename)
    annotation_cols = _annotation_columns(spec)
    _require_columns(df, [x, y, value, *annotation_cols], name)

    plot_df = _aggregate_for_plot(df, [y, x], value, _aggregate(spec, "mean"))
    pivot = plot_df.pivot(index=y, columns=x, values=value)
    pivot = _sort_axes(pivot)
    if pivot.empty:
        return []

    fig, ax = plt.subplots(figsize=_figsize(spec, (8.0, 6.2)))
    image = ax.imshow(
        pivot.to_numpy(dtype=float),
        aspect=str(_option(spec, "aspect", default="auto")),
        cmap=str(_option(spec, "cmap", "colormap", default="viridis")),
        vmin=_option(spec, "vmin", default=None),
        vmax=_option(spec, "vmax", default=None),
    )
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([_format_tick(value) for value in pivot.columns], rotation=_float_option(spec, "x_tick_rotation", "tick_rotation", default=30), ha="right")
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([_format_tick(value) for value in pivot.index], rotation=_float_option(spec, "y_tick_rotation", default=0))
    if _bool_option(spec, "colorbar", "show_colorbar", default=True):
        colorbar = fig.colorbar(image, ax=ax)
        colorbar.set_label(_ylabel(spec, _pretty(value)))

    if spec.get("annotate", True):
        annotation_tables = {
            col: _aggregate_for_plot(df, [y, x], col, _aggregate(spec, "mean")).pivot(index=y, columns=x, values=col)
            for col in annotation_cols
        }
        for row_index, row_value in enumerate(pivot.index):
            for col_index, col_value in enumerate(pivot.columns):
                cell_value = pivot.loc[row_value, col_value]
                if pd.isna(cell_value):
                    continue
                text = _format_number(cell_value)
                for annotation_col, annotation_pivot in annotation_tables.items():
                    if row_value in annotation_pivot.index and col_value in annotation_pivot.columns:
                        annotation_value = annotation_pivot.loc[row_value, col_value]
                        if pd.notna(annotation_value):
                            text += f"\n{_short_label(annotation_col)}={_format_number(annotation_value)}"
                ax.text(
                    col_index,
                    row_index,
                    text,
                    ha="center",
                    va="center",
                    color=str(_option(spec, "annotation_color", default="white")),
                    fontsize=_float_option(spec, "annotation_fontsize", "annotation_size", default=8),
                )

    title = _title(spec, f"{_pretty(value)} heatmap")
    _finish_axis(ax, spec, title=title, xlabel=_xlabel(spec, _pretty(x)), ylabel=_ylabel(spec, _pretty(y)))
    return _save(fig, out_dir, basename, title, _description(spec, "Custom heatmap."), formats, spec)


def _apply_filters(df: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    filters = spec.get("filters", spec.get("filter", {}))
    if not filters:
        return df
    if isinstance(filters, dict):
        for col, expected in filters.items():
            if col not in df.columns:
                raise PlotSpecError(f"{spec.get('name', 'plot')}: filter column '{col}' is not available")
            if isinstance(expected, list):
                df = df[df[col].isin(expected)]
            elif expected is None:
                df = df[df[col].isna()]
            else:
                df = df[df[col].eq(expected)]
        return df
    if isinstance(filters, list):
        for item in filters:
            if not isinstance(item, dict):
                raise PlotSpecError("Filter entries must be objects")
            col = str(item.get("column"))
            op = str(item.get("op", "=="))
            value = item.get("value")
            if col not in df.columns:
                raise PlotSpecError(f"{spec.get('name', 'plot')}: filter column '{col}' is not available")
            df = _apply_filter_condition(df, col, op, value)
        return df
    raise PlotSpecError("filters must be an object or a list")


def _apply_filter_condition(df: pd.DataFrame, col: str, op: str, value: Any) -> pd.DataFrame:
    if op in {"==", "eq"}:
        return df[df[col].eq(value)]
    if op in {"!=", "ne"}:
        return df[df[col].ne(value)]
    if op in {">", "gt"}:
        return df[pd.to_numeric(df[col], errors="coerce") > float(value)]
    if op in {">=", "ge"}:
        return df[pd.to_numeric(df[col], errors="coerce") >= float(value)]
    if op in {"<", "lt"}:
        return df[pd.to_numeric(df[col], errors="coerce") < float(value)]
    if op in {"<=", "le"}:
        return df[pd.to_numeric(df[col], errors="coerce") <= float(value)]
    if op == "in":
        return df[df[col].isin(value if isinstance(value, list) else [value])]
    if op == "not_in":
        return df[~df[col].isin(value if isinstance(value, list) else [value])]
    if op == "contains":
        return df[df[col].astype(str).str.contains(str(value), na=False)]
    raise PlotSpecError(f"Unsupported filter operator '{op}'")


def _aggregate_for_plot(df: pd.DataFrame, group_cols: list[str], value_col: str, aggregate: str) -> pd.DataFrame:
    if not group_cols:
        return pd.DataFrame({value_col: [_aggregate_series(df[value_col], aggregate)]})
    grouped = df.groupby(group_cols, dropna=False)[value_col].apply(lambda values: _aggregate_series(values, aggregate))
    return grouped.reset_index(name=value_col)


def _aggregate_series(values: pd.Series, aggregate: str) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if aggregate == "mean":
        return float(numeric.mean())
    if aggregate == "median":
        return float(numeric.median())
    if aggregate == "sum":
        return float(numeric.sum())
    if aggregate == "min":
        return float(numeric.min())
    if aggregate == "max":
        return float(numeric.max())
    if aggregate == "std":
        return float(numeric.std())
    if aggregate == "count":
        return float(numeric.count())
    if aggregate == "p95":
        return float(numeric.quantile(0.95))
    if aggregate == "p99":
        return float(numeric.quantile(0.99))
    if aggregate == "first":
        return float(numeric.iloc[0]) if not numeric.empty else float("nan")
    if aggregate == "last":
        return float(numeric.iloc[-1]) if not numeric.empty else float("nan")
    if aggregate == "jain":
        values_list = [float(value) for value in numeric]
        if not values_list:
            return float("nan")
        squared_sum = sum(values_list) ** 2
        sum_of_squares = sum(value * value for value in values_list)
        return float(squared_sum / (len(values_list) * sum_of_squares)) if sum_of_squares else 1.0
    raise PlotSpecError(f"Unsupported aggregate '{aggregate}'")


def _facets(df: pd.DataFrame, facet_cols: list[str]) -> list[tuple[str, str, pd.DataFrame]]:
    if not facet_cols:
        return [("", "", df)]
    facets = []
    for values, group_df in df.groupby(facet_cols, dropna=False):
        value_tuple = values if isinstance(values, tuple) else (values,)
        labels = [f"{col}={_format_tick(value)}" for col, value in zip(facet_cols, value_tuple)]
        suffix = "_".join(_slug(label) for label in labels)
        facets.append((suffix, ", ".join(labels), group_df))
    return facets


def _label_groups(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if not group_cols:
        return df
    df = df.copy()
    df["_series_label"] = df[group_cols].astype(str).agg(" / ".join, axis=1)
    return df


def _grouped(df: pd.DataFrame, group_cols: list[str]) -> list[tuple[str, pd.DataFrame]]:
    if not group_cols:
        return [("", df)]
    grouped = []
    for values, group_df in df.groupby(group_cols, dropna=False):
        value_tuple = values if isinstance(values, tuple) else (values,)
        grouped.append((" / ".join(str(value) for value in value_tuple), group_df))
    return grouped


def _sort_values(df: pd.DataFrame, col: str) -> pd.DataFrame:
    numeric = pd.to_numeric(df[col], errors="coerce")
    if numeric.notna().all():
        return df.assign(_sort_value=numeric).sort_values("_sort_value").drop(columns=["_sort_value"])
    return df.sort_values(col)


def _sort_axes(pivot: pd.DataFrame) -> pd.DataFrame:
    try:
        pivot = pivot.reindex(sorted(pivot.index, key=float), axis=0)
    except (TypeError, ValueError):
        pivot = pivot.sort_index(axis=0)
    try:
        pivot = pivot.reindex(sorted(pivot.columns, key=float), axis=1)
    except (TypeError, ValueError):
        pivot = pivot.sort_index(axis=1)
    return pivot


def _finish_axis(ax: plt.Axes, spec: dict[str, Any], *, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(_with_facet(title, spec), fontsize=_option(spec, "title_fontsize", "title_size", default=None))
    ax.set_xlabel(xlabel, fontsize=_option(spec, "label_fontsize", "label_size", default=None))
    ax.set_ylabel(ylabel, fontsize=_option(spec, "label_fontsize", "label_size", default=None))
    ax.grid(_bool_option(spec, "grid", default=True), which="major", linestyle=":", linewidth=0.8, alpha=0.7)
    if spec.get("log_x"):
        ax.set_xscale("log")
    if spec.get("log_y"):
        ax.set_yscale("log")
    if "xlim" in spec:
        ax.set_xlim(spec["xlim"])
    if "ylim" in spec:
        ax.set_ylim(spec["ylim"])
    tick_size = _option(spec, "tick_fontsize", "tick_size", default=None)
    ax.tick_params(axis="both", labelsize=tick_size)
    if _option(spec, "x_tick_rotation", "tick_rotation", default=None) is not None:
        ax.tick_params(axis="x", labelrotation=_float_option(spec, "x_tick_rotation", "tick_rotation", default=0))
    if _option(spec, "y_tick_rotation", default=None) is not None:
        ax.tick_params(axis="y", labelrotation=_float_option(spec, "y_tick_rotation", default=0))


def _save(
    fig: plt.Figure,
    out_dir: Path,
    basename: str,
    title: str,
    description: str,
    formats: list[str],
    spec: dict[str, Any],
) -> list[PlotArtifact]:
    if _bool_option(spec, "tight_layout", default=True):
        fig.tight_layout()
    artifacts = []
    for fmt in formats:
        clean_format = str(fmt).lower().lstrip(".")
        path = out_dir / f"{basename}.{clean_format}"
        fig.savefig(path, dpi=int(_float_option(spec, "dpi", default=160)), bbox_inches=str(_option(spec, "bbox_inches", default="tight")))
        artifacts.append(PlotArtifact(name=basename, title=title, path=path, description=description))
    plt.close(fig)
    return artifacts


def _legend(ax: plt.Axes, item_count: int, spec: dict[str, Any]) -> None:
    if item_count <= 1 or not _legend_visible(spec):
        return

    kwargs: dict[str, Any] = {
        "loc": str(_legend_option(spec, "loc", "location", "legend_loc", default="center left")),
        "frameon": _as_bool(_legend_option(spec, "frame", "frameon", "legend_frame", default=False), False),
        "fontsize": _legend_option(spec, "fontsize", "font_size", "legend_fontsize", default=8),
    }
    anchor = _legend_option(spec, "anchor", "bbox_to_anchor", "legend_anchor", default=[1.02, 0.5])
    if anchor is not None and anchor is not False:
        kwargs["bbox_to_anchor"] = tuple(anchor) if isinstance(anchor, list) else anchor
    ax.legend(**kwargs)


def _require_columns(df: pd.DataFrame, columns: list[str], name: str) -> None:
    missing = [col for col in columns if col not in df.columns]
    if missing:
        raise PlotSpecError(f"{name}: missing column(s): {', '.join(missing)}")


def _required_field(spec: dict[str, Any], field: str) -> str:
    value = spec.get(field)
    if not value:
        raise PlotSpecError(f"{spec.get('name', 'plot')}: missing required field '{field}'")
    return str(value)


def _metric(spec: dict[str, Any]) -> str:
    for key in ("metric", "value", "y"):
        if spec.get(key):
            return str(spec[key])
    raise PlotSpecError(f"{spec.get('name', 'plot')}: missing metric/value/y field")


def _aggregate(spec: dict[str, Any], default: str) -> str:
    return str(spec.get("aggregate") or default).strip().lower()


def _annotation_columns(spec: dict[str, Any]) -> list[str]:
    annotations = spec.get("annotations", [])
    if isinstance(annotations, str):
        return [annotations]
    if isinstance(annotations, list):
        return [str(item) for item in annotations]
    return []


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _option(spec: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in spec:
            return spec[key]
    style = spec.get("style")
    if isinstance(style, dict):
        for key in keys:
            if key in style:
                return style[key]
    return default


def _float_option(spec: dict[str, Any], *keys: str, default: float) -> float:
    value = _option(spec, *keys, default=default)
    return float(value)


def _bool_option(spec: dict[str, Any], *keys: str, default: bool) -> bool:
    value = _option(spec, *keys, default=default)
    return _as_bool(value, default)


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", "none"}
    return bool(value)


def _legend_visible(spec: dict[str, Any]) -> bool:
    legend = spec.get("legend")
    if isinstance(legend, dict):
        return _as_bool(legend.get("show", legend.get("visible", True)), True)
    if legend is not None:
        return _as_bool(legend, True)
    return _bool_option(spec, "show_legend", default=True)


def _legend_option(spec: dict[str, Any], *keys: str, default: Any = None) -> Any:
    legend = spec.get("legend")
    if isinstance(legend, dict):
        for key in keys:
            if key in legend:
                return legend[key]
    return _option(spec, *keys, default=default)


def _series_color(spec: dict[str, Any], label: object, index: int, total: int) -> Any:
    colors = _option(spec, "colors", default=None)
    label_text = str(label)
    if isinstance(colors, dict):
        return (
            colors.get(label)
            or colors.get(label_text)
            or colors.get(label_text.lower())
            or colors.get(_slug(label_text))
            or colors.get("default")
        )
    if isinstance(colors, list) and colors:
        return colors[index % len(colors)]
    if colors and not isinstance(colors, (dict, list)):
        return colors

    palette = _option(spec, "palette", default=None)
    if palette:
        cmap = plt.get_cmap(str(palette))
        position = index / max(total - 1, 1)
        return cmap(position)
    return _option(spec, "color", default=None)


def _series_colors(spec: dict[str, Any], labels: list[object]) -> list[Any] | None:
    colors = [_series_color(spec, label, index, len(labels)) for index, label in enumerate(labels)]
    return colors if colors and all(color is not None for color in colors) else None


def _title(spec: dict[str, Any], default: str) -> str:
    return str(spec.get("title") or default)


def _description(spec: dict[str, Any], default: str) -> str:
    return str(spec.get("description") or default)


def _xlabel(spec: dict[str, Any], default: str) -> str:
    return str(spec.get("x_label") or spec.get("xlabel") or default)


def _ylabel(spec: dict[str, Any], default: str) -> str:
    return str(spec.get("y_label") or spec.get("ylabel") or default)


def _with_facet(title: str, spec: dict[str, Any]) -> str:
    facet_title = spec.get("_facet_title")
    return f"{title} ({facet_title})" if facet_title else title


def _figsize(spec: dict[str, Any], default: tuple[float, float]) -> tuple[float, float]:
    value = _option(spec, "figsize", "dimensions", "figure_size", default=None)
    if isinstance(value, list) and len(value) == 2:
        return float(value[0]), float(value[1])
    width = _option(spec, "width", "fig_width", default=None)
    height = _option(spec, "height", "fig_height", default=None)
    if width is not None or height is not None:
        return float(width if width is not None else default[0]), float(height if height is not None else default[1])
    return default


def _marker(spec: dict[str, Any]) -> str | None:
    marker = spec.get("marker")
    return str(marker) if marker else None


def _pretty(value: str) -> str:
    return value.replace("_", " ").strip().title()


def _short_label(value: str) -> str:
    replacements = {
        "link_utilization_percent": "util",
        "jain_fairness": "fair",
        "total_throughput_mbps": "total",
    }
    return replacements.get(value, value.replace("_percent", "").replace("_mbps", "").replace("_", " "))


def _format_tick(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _format_number(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.3g}"


def _slug(value: object) -> str:
    text = str(value).strip().lower()
    chars = [char if char.isalnum() else "_" for char in text]
    slug = "_".join(part for part in "".join(chars).split("_") if part)
    return slug or "plot"
