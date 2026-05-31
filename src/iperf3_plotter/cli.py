from __future__ import annotations

import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message="Pandas requires version .*", category=UserWarning)

import pandas as pd
import typer

from .custom import PlotSpecError, generate_custom_plots
from .experiment import ExperimentError, run_experiment, validate_experiment
from .metrics import flow_aggregates, interval_summary, jain_fairness, series_similarity
from .manifest import ManifestError, load_manifest
from .outputs import write_tables
from .parser import IperfParseError, parse_files
from .plots import generate_plots
from .report import write_report

app = typer.Typer(no_args_is_help=True, help="Analyze and plot iperf3 JSON results.")
VALID_TIME_MODES = {"relative", "global", "offset", "wall"}


@app.command("parse")
def parse_command(
    inputs: list[Path] = typer.Argument(..., exists=True, readable=True, dir_okay=False, help="iperf3 JSON file(s)."),
    out: Path = typer.Option(Path("data"), "--out", "-o", help="Directory for normalized CSV outputs."),
    manifest: Path | None = typer.Option(None, "--manifest", "-m", exists=True, readable=True, dir_okay=False, help="Optional JSON/CSV experiment manifest."),
    time_mode: str | None = typer.Option(None, "--time-mode", help="Use relative, global, offset, or wall time when computing derived tables. Defaults to relative."),
) -> None:
    """Normalize iperf3 JSON into CSV tables."""

    time_mode = _prepare_time_mode(inputs, manifest, time_mode)
    intervals, summaries, runs = _parse_or_exit(inputs, manifest)
    files = write_tables(intervals, summaries, runs, out, time_mode=time_mode)
    typer.echo(f"Wrote normalized tables to {out}")
    for name, path in files.items():
        typer.echo(f"  {name}: {path}")


@app.command("plot")
def plot_command(
    inputs: list[Path] = typer.Argument(..., exists=True, readable=True, dir_okay=False, help="iperf3 JSON file(s)."),
    out: Path = typer.Option(Path("plots"), "--out", "-o", help="Directory for generated plots."),
    formats: list[str] = typer.Option(["png"], "--format", "-f", help="Plot format. Repeat for png/pdf/svg."),
    manifest: Path | None = typer.Option(None, "--manifest", "-m", exists=True, readable=True, dir_okay=False, help="Optional JSON/CSV experiment manifest."),
    time_mode: str | None = typer.Option(None, "--time-mode", help="Use relative, global, offset, or wall time for the x-axis. Defaults to relative."),
    plot_spec: Path | None = typer.Option(None, "--plot-spec", "--spec", exists=True, readable=True, dir_okay=False, help="Optional YAML/JSON file with custom plot definitions."),
) -> None:
    """Generate plots directly from iperf3 JSON."""

    time_mode = _prepare_time_mode(inputs, manifest, time_mode)
    intervals, summaries, runs = _parse_or_exit(inputs, manifest)
    artifacts = generate_plots(intervals, summaries, out, formats=formats, time_mode=time_mode)
    artifacts.extend(_custom_plots_or_exit(intervals, summaries, runs, out, plot_spec, formats, time_mode))
    typer.echo(f"Wrote {len(artifacts)} plot file(s) to {out}")


@app.command("report")
def report_command(
    inputs: list[Path] = typer.Argument(..., exists=True, readable=True, dir_okay=False, help="iperf3 JSON file(s)."),
    out: Path = typer.Option(Path("report.html"), "--out", "-o", help="HTML report path."),
    formats: list[str] = typer.Option(["png"], "--format", "-f", help="Plot format. HTML reports use PNG assets."),
    manifest: Path | None = typer.Option(None, "--manifest", "-m", exists=True, readable=True, dir_okay=False, help="Optional JSON/CSV experiment manifest."),
    time_mode: str | None = typer.Option(None, "--time-mode", help="Use relative, global, offset, or wall time for plots and metrics. Defaults to relative."),
    plot_spec: Path | None = typer.Option(None, "--plot-spec", "--spec", exists=True, readable=True, dir_okay=False, help="Optional YAML/JSON file with custom plot definitions."),
) -> None:
    """Generate an HTML report with plots and summary tables."""

    time_mode = _prepare_time_mode(inputs, manifest, time_mode)
    intervals, summaries, runs = _parse_or_exit(inputs, manifest)
    asset_dir = out.with_suffix("").parent / f"{out.with_suffix('').name}_assets"
    plot_formats = _ensure_png(formats)
    artifacts = generate_plots(intervals, summaries, asset_dir, formats=plot_formats, time_mode=time_mode)
    artifacts.extend(_custom_plots_or_exit(intervals, summaries, runs, asset_dir, plot_spec, plot_formats, time_mode))
    write_report(intervals, summaries, runs, artifacts, out, time_mode=time_mode)
    typer.echo(f"Wrote report to {out}")


@app.command("all")
def all_command(
    inputs: list[Path] = typer.Argument(..., exists=True, readable=True, dir_okay=False, help="iperf3 JSON file(s)."),
    out: Path = typer.Option(Path("results"), "--out", "-o", help="Output directory."),
    formats: list[str] = typer.Option(["png", "pdf"], "--format", "-f", help="Plot format. Repeat for png/pdf/svg."),
    manifest: Path | None = typer.Option(None, "--manifest", "-m", exists=True, readable=True, dir_okay=False, help="Optional JSON/CSV experiment manifest."),
    time_mode: str | None = typer.Option(None, "--time-mode", help="Use relative, global, offset, or wall time for plots and metrics. Defaults to relative."),
    plot_spec: Path | None = typer.Option(None, "--plot-spec", "--spec", exists=True, readable=True, dir_okay=False, help="Optional YAML/JSON file with custom plot definitions."),
) -> None:
    """Run the complete pipeline: parse, plot, and report."""

    time_mode = _prepare_time_mode(inputs, manifest, time_mode)
    intervals, summaries, runs = _parse_or_exit(inputs, manifest)
    data_dir = out / "data"
    plots_dir = out / "plots"
    report_path = out / "report.html"
    write_tables(intervals, summaries, runs, data_dir, time_mode=time_mode)
    artifacts = generate_plots(intervals, summaries, plots_dir, formats=formats, time_mode=time_mode)
    artifacts.extend(_custom_plots_or_exit(intervals, summaries, runs, plots_dir, plot_spec, formats, time_mode))
    write_report(intervals, summaries, runs, artifacts, report_path, time_mode=time_mode)
    typer.echo(f"Wrote data to {data_dir}")
    typer.echo(f"Wrote {len(artifacts)} plot file(s) to {plots_dir}")
    typer.echo(f"Wrote report to {report_path}")


@app.command("custom")
def custom_command(
    inputs: list[Path] = typer.Argument(..., exists=True, readable=True, dir_okay=False, help="iperf3 JSON file(s)."),
    plot_spec: Path = typer.Option(..., "--plot-spec", "--spec", exists=True, readable=True, dir_okay=False, help="YAML/JSON file with custom plot definitions."),
    out: Path = typer.Option(Path("plots"), "--out", "-o", help="Directory for generated custom plots."),
    formats: list[str] = typer.Option(["png"], "--format", "-f", help="Plot format. Repeat for png/pdf/svg."),
    manifest: Path | None = typer.Option(None, "--manifest", "-m", exists=True, readable=True, dir_okay=False, help="Optional JSON/CSV experiment manifest."),
    time_mode: str | None = typer.Option(None, "--time-mode", help="Use relative, global, offset, or wall time for derived tables. Defaults to relative."),
) -> None:
    """Generate only plots defined in a YAML/JSON plot specification."""

    time_mode = _prepare_time_mode(inputs, manifest, time_mode)
    intervals, summaries, runs = _parse_or_exit(inputs, manifest)
    artifacts = _custom_plots_or_exit(intervals, summaries, runs, out, plot_spec, formats, time_mode)
    typer.echo(f"Wrote {len(artifacts)} custom plot file(s) to {out}")


@app.command("experiment")
def experiment_command(
    config: Path = typer.Argument(..., exists=True, readable=True, dir_okay=False, help="Experiment YAML/JSON file."),
    out: Path = typer.Option(Path("results"), "--out", "-o", help="Output directory."),
    formats: list[str] = typer.Option(["png", "pdf"], "--format", "-f", help="Plot format. Repeat for png/pdf/svg."),
) -> None:
    """Run parse, plot, and report from one experiment file."""

    try:
        result = run_experiment(config, out, formats=formats)
    except ExperimentError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(f"Resolved {len(result.plan.files)} input JSON file(s) from {result.plan.config_path}")
    typer.echo(f"Using time mode: {result.plan.time_mode}")
    typer.echo(f"Wrote data to {result.data_dir}")
    typer.echo(f"Wrote {len(result.artifacts)} plot file(s) to {result.plots_dir}")
    typer.echo(f"Wrote report to {result.report_path}")


@app.command("validate")
def validate_command(
    config: Path = typer.Argument(..., exists=True, readable=True, dir_okay=False, help="Experiment YAML/JSON file."),
) -> None:
    """Validate an experiment file before running it."""

    try:
        warnings = validate_experiment(config)
    except ExperimentError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(f"OK: {config}")
    for warning in warnings:
        typer.echo(f"Warning: {warning}", err=True)


@app.command("fairness")
def fairness_command(
    inputs: list[Path] = typer.Argument(..., exists=True, readable=True, dir_okay=False, help="iperf3 JSON file(s)."),
    level: str = typer.Option("flow", "--level", "-l", help="Fairness level: flow or stream."),
    manifest: Path | None = typer.Option(None, "--manifest", "-m", exists=True, readable=True, dir_okay=False, help="Optional JSON/CSV experiment manifest."),
) -> None:
    """Compute Jain fairness from average throughput."""

    intervals, _summaries, _runs = _parse_or_exit(inputs, manifest)
    if level not in {"flow", "stream"}:
        raise typer.BadParameter("--level must be 'flow' or 'stream'")

    if level == "flow":
        entity_col = "flow_id"
        metrics_df = interval_summary(flow_aggregates(intervals), entity_col)
    else:
        entity_col = "stream_id"
        metrics_df = interval_summary(intervals, entity_col)

    values = metrics_df["avg_throughput_mbps"].fillna(0)
    fairness = jain_fairness(values)
    typer.echo(f"Jain fairness ({level}): {fairness:.5f}" if fairness is not None else f"Jain fairness ({level}): n/a")
    if not metrics_df.empty:
        typer.echo(metrics_df[[entity_col, "avg_throughput_mbps", "total_mib", "retransmits"]].to_string(index=False))


@app.command("diagnose")
def diagnose_command(
    inputs: list[Path] = typer.Argument(..., exists=True, readable=True, dir_okay=False, help="iperf3 JSON file(s)."),
    manifest: Path | None = typer.Option(None, "--manifest", "-m", exists=True, readable=True, dir_okay=False, help="Optional JSON/CSV experiment manifest."),
) -> None:
    """Inspect whether stream lines overlap because the raw data is similar."""

    intervals, _summaries, _runs = _parse_or_exit(inputs, manifest)
    summary = interval_summary(intervals, "stream_id")
    similarity = series_similarity(intervals)

    typer.echo("Stream summary:")
    cols = [
        "stream_id",
        "avg_throughput_mbps",
        "total_mib",
        "mean_rtt_ms",
        "p95_rtt_ms",
        "retransmits",
    ]
    existing_cols = [col for col in cols if col in summary.columns]
    typer.echo(summary[existing_cols].to_string(index=False) if not summary.empty else "  n/a")

    typer.echo("\nExact-overlap checks:")
    exact = similarity[similarity["exact_equal"]] if not similarity.empty else pd.DataFrame()
    typer.echo(exact.to_string(index=False) if not exact.empty else "  No exactly equal stream pairs found.")

    typer.echo("\nLargest throughput differences:")
    throughput = similarity[similarity["metric"].eq("throughput_mbps")] if not similarity.empty else pd.DataFrame()
    if throughput.empty:
        typer.echo("  n/a")
    else:
        display = throughput.sort_values("max_abs_diff", ascending=False).head(10)
        typer.echo(display.to_string(index=False))


def _parse_or_exit(inputs: list[Path], manifest: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    try:
        metadata = load_manifest(manifest) if manifest else None
        return parse_files(inputs, metadata)
    except (IperfParseError, ManifestError) as exc:
        raise typer.BadParameter(str(exc)) from exc


def _custom_plots_or_exit(
    intervals: pd.DataFrame,
    summaries: pd.DataFrame,
    runs: pd.DataFrame,
    out: Path,
    plot_spec: Path | None,
    formats: list[str],
    time_mode: str,
) -> list:
    if plot_spec is None:
        return []
    try:
        return generate_custom_plots(intervals, summaries, runs, out, spec_path=plot_spec, formats=formats, time_mode=time_mode)
    except PlotSpecError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _prepare_time_mode(inputs: list[Path], manifest: Path | None, time_mode: str | None) -> str:
    explicit_time_mode = time_mode is not None
    mode = (time_mode or "relative").strip().lower()
    if mode not in VALID_TIME_MODES:
        valid = ", ".join(sorted(VALID_TIME_MODES))
        raise typer.BadParameter(f"--time-mode must be one of: {valid}")

    warning = _relative_time_warning(inputs, manifest, mode, explicit_time_mode)
    if warning:
        typer.echo(warning, err=True)
    return mode


def _relative_time_warning(
    inputs: list[Path],
    manifest: Path | None,
    time_mode: str,
    explicit_time_mode: bool,
) -> str | None:
    if explicit_time_mode or time_mode != "relative" or len(inputs) <= 1:
        return None
    if manifest:
        return (
            "Warning: multiple JSON files are using default --time-mode relative, "
            "so each file starts at X=0. Use --time-mode offset with your manifest "
            "to preserve staggered starts, or --time-mode global if JSON timestamps "
            "are synchronized."
        )
    return (
        "Warning: multiple JSON files are using default --time-mode relative, "
        "so each file starts at X=0. Use --time-mode global to align by iperf3 "
        "timestamps, or use 'iperfplot experiment' with start_offset_s metadata "
        "when clocks are not synchronized."
    )


def _ensure_png(formats: list[str]) -> list[str]:
    cleaned = [fmt.lower().lstrip(".") for fmt in formats]
    return cleaned if "png" in cleaned else ["png", *cleaned]
