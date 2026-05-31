from __future__ import annotations

from dataclasses import dataclass
import glob
import json
import re
from pathlib import Path
from typing import Any

import yaml

from .custom import PlotSpecError, build_plot_sources, generate_custom_plots_from_specs
from .outputs import write_tables
from .parser import IperfParseError, parse_files
from .plots import PlotArtifact, generate_plots
from .report import write_report


VALID_TIME_MODES = {"relative", "global", "offset", "wall"}
SUMMARY_SOURCES = {"flow_summary", "stream_summary", "experiment_summary", "runs"}


class ExperimentError(ValueError):
    """Raised when an experiment YAML file cannot be resolved or run."""


@dataclass(frozen=True)
class ExperimentPlan:
    config_path: Path
    name: str
    files: list[Path]
    metadata: dict[str, dict[str, Any]]
    plot_specs: list[dict[str, Any]]
    time_mode: str
    include_default_plots: bool


@dataclass(frozen=True)
class ExperimentResult:
    plan: ExperimentPlan
    data_dir: Path
    plots_dir: Path
    report_path: Path
    artifacts: list[PlotArtifact]


def load_experiment(path: Path) -> dict[str, Any]:
    """Load an experiment YAML or JSON file."""

    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ExperimentError(f"{path} is not valid YAML: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ExperimentError(f"{path} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ExperimentError("Experiment file must be a YAML/JSON object")
    return data


def resolve_experiment(path: Path) -> ExperimentPlan:
    """Resolve input paths, metadata, plots, and defaults from one experiment file."""

    config_path = Path(path).resolve()
    config = load_experiment(config_path)
    base_dir = config_path.parent
    name = str(config.get("name") or config_path.stem)

    files, explicit_metadata = _resolve_inputs(config, base_dir)
    if not files:
        raise ExperimentError("Experiment file did not match any input JSON files")

    defaults = _object(config.get("defaults"), "defaults")
    inferred = _infer_metadata(config, base_dir, files)
    overrides = _override_metadata(config, base_dir)
    metadata = _metadata_map(files, defaults, inferred, explicit_metadata, overrides)
    specs = expand_plot_specs(config.get("plots", []))
    time_mode = _resolve_time_mode(config, metadata)
    include_default_plots = _as_bool(config.get("default_plots", config.get("include_default_plots", True)), True)

    return ExperimentPlan(
        config_path=config_path,
        name=name,
        files=files,
        metadata=metadata,
        plot_specs=specs,
        time_mode=time_mode,
        include_default_plots=include_default_plots,
    )


def run_experiment(config_path: Path, out: Path, *, formats: list[str] | None = None) -> ExperimentResult:
    """Run the full parser, plotting, and HTML report pipeline from an experiment file."""

    plan = resolve_experiment(config_path)
    formats = formats or ["png", "pdf"]
    out = Path(out)
    data_dir = out / "data"
    plots_dir = out / "plots"
    report_path = out / "report.html"

    try:
        intervals, summaries, runs = parse_files(plan.files, plan.metadata)
        write_tables(intervals, summaries, runs, data_dir, time_mode=plan.time_mode)
        artifacts: list[PlotArtifact] = []
        if plan.include_default_plots:
            artifacts.extend(generate_plots(intervals, summaries, plots_dir, formats=formats, time_mode=plan.time_mode))
        artifacts.extend(
            generate_custom_plots_from_specs(
                intervals,
                summaries,
                runs,
                plots_dir,
                specs=plan.plot_specs,
                formats=formats,
                time_mode=plan.time_mode,
            )
        )
        write_report(intervals, summaries, runs, artifacts, report_path, time_mode=plan.time_mode)
    except (IperfParseError, PlotSpecError) as exc:
        raise ExperimentError(str(exc)) from exc

    return ExperimentResult(plan=plan, data_dir=data_dir, plots_dir=plots_dir, report_path=report_path, artifacts=artifacts)


def validate_experiment(path: Path) -> list[str]:
    """Validate an experiment file and return non-fatal warnings."""

    plan = resolve_experiment(path)
    missing_files = [file for file in plan.files if not file.exists()]
    if missing_files:
        joined = ", ".join(str(file) for file in missing_files[:5])
        raise ExperimentError(f"Input file(s) do not exist: {joined}")

    warnings: list[str] = []
    try:
        intervals, summaries, runs = parse_files(plan.files, plan.metadata)
    except IperfParseError as exc:
        raise ExperimentError(str(exc)) from exc

    sources = build_plot_sources(intervals, summaries, runs, time_mode=plan.time_mode)
    for spec in plan.plot_specs:
        _validate_plot_spec(spec, sources, warnings)
    return warnings


def expand_plot_specs(plots: Any) -> list[dict[str, Any]]:
    if plots is None:
        return []
    if not isinstance(plots, list) or not all(isinstance(item, dict) for item in plots):
        raise ExperimentError("'plots' must be a list of plot objects")

    specs: list[dict[str, Any]] = []
    for item in plots:
        specs.extend(_expand_plot_item(item))
    return specs


def _resolve_inputs(config: dict[str, Any], base_dir: Path) -> tuple[list[Path], dict[str, dict[str, Any]]]:
    inputs = config.get("inputs", {})
    if isinstance(inputs, str) or isinstance(inputs, list):
        inputs = {"files": inputs}
    inputs = _object(inputs, "inputs")

    patterns = inputs.get("files", inputs.get("glob", config.get("files")))
    explicit_runs = inputs.get("runs", config.get("runs", []))

    files = _expand_patterns(patterns, base_dir)
    explicit_files, explicit_metadata = _resolve_explicit_runs(explicit_runs, base_dir)
    return _unique_paths([*files, *explicit_files]), explicit_metadata


def _expand_patterns(patterns: Any, base_dir: Path) -> list[Path]:
    if not patterns:
        return []
    values = patterns if isinstance(patterns, list) else [patterns]
    files: list[Path] = []
    for value in values:
        pattern = Path(str(value))
        raw_pattern = str(pattern if pattern.is_absolute() else base_dir / pattern)
        matches = [Path(match).resolve() for match in glob.glob(raw_pattern, recursive=True)]
        matches = [match for match in matches if match.is_file()]
        if not matches and not _has_glob_chars(raw_pattern):
            candidate = Path(raw_pattern).resolve()
            if candidate.exists() and candidate.is_file():
                matches = [candidate]
        files.extend(sorted(matches))
    return files


def _resolve_explicit_runs(runs: Any, base_dir: Path) -> tuple[list[Path], dict[str, dict[str, Any]]]:
    if not runs:
        return [], {}
    if not isinstance(runs, list) or not all(isinstance(run, dict) for run in runs):
        raise ExperimentError("'inputs.runs' must be a list of objects")

    files: list[Path] = []
    metadata: dict[str, dict[str, Any]] = {}
    for run in runs:
        file_value = run.get("file") or run.get("path") or run.get("source_file")
        if not file_value:
            raise ExperimentError("Each inputs.runs entry must include file/path/source_file")
        path = _resolve_path(base_dir, file_value)
        files.append(path)
        clean = {key: _coerce(value) for key, value in run.items() if key not in {"file", "path", "source_file"}}
        metadata[str(path)] = clean
        metadata[path.as_posix()] = clean
        metadata[path.name] = clean
    return files, metadata


def _infer_metadata(config: dict[str, Any], base_dir: Path, files: list[Path]) -> dict[str, dict[str, Any]]:
    infer = config.get("infer", config.get("derive", {}))
    infer = _object(infer, "infer")
    regex_source = _regex_source(infer)
    pattern_source = _pattern_source(infer)
    if regex_source and pattern_source:
        raise ExperimentError("Use only one infer filename/path rule: filename_regex, path_regex, filename_pattern, or path_pattern")
    if not regex_source and not pattern_source:
        return {}

    if regex_source:
        key, value = regex_source
        regex = _compile_metadata_regex(str(value))
        match_name_only = key == "filename_regex"
        use_search = True
    else:
        key, value = pattern_source or ("filename_pattern", "")
        regex = _filename_pattern_to_regex(str(value))
        match_name_only = key == "filename_pattern"
        use_search = False

    metadata: dict[str, dict[str, Any]] = {}
    for file in files:
        target = file.name if match_name_only else _relative_or_name(base_dir, file)
        match = regex.search(target) if use_search else regex.match(target)
        if not match:
            continue
        metadata[str(file)] = {key: _coerce(value) for key, value in match.groupdict().items()}
    return metadata


def _override_metadata(config: dict[str, Any], base_dir: Path) -> dict[str, dict[str, Any]]:
    overrides = config.get("overrides", {})
    if not overrides:
        return {}

    result: dict[str, dict[str, Any]] = {}
    if isinstance(overrides, dict):
        items = overrides.items()
    elif isinstance(overrides, list) and all(isinstance(item, dict) for item in overrides):
        items = []
        for item in overrides:
            file_value = item.get("file") or item.get("path") or item.get("source_file")
            if not file_value:
                raise ExperimentError("Each override entry must include file/path/source_file")
            items.append((file_value, {key: value for key, value in item.items() if key not in {"file", "path", "source_file"}}))
    else:
        raise ExperimentError("'overrides' must be an object or a list of objects")

    for file_value, values in items:
        if not isinstance(values, dict):
            raise ExperimentError("Each override value must be an object")
        path = _resolve_path(base_dir, file_value)
        result[str(path)] = {key: _coerce(value) for key, value in values.items()}
    return result


def _metadata_map(
    files: list[Path],
    defaults: dict[str, Any],
    inferred: dict[str, dict[str, Any]],
    explicit: dict[str, dict[str, Any]],
    overrides: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for file in files:
        metadata: dict[str, Any] = dict(defaults)
        metadata.update(inferred.get(str(file), {}))
        metadata.update(explicit.get(str(file), explicit.get(file.as_posix(), explicit.get(file.name, {}))))
        metadata.update(overrides.get(str(file), overrides.get(file.as_posix(), overrides.get(file.name, {}))))
        metadata.setdefault("run_id", file.stem)
        metadata.setdefault("flow_id", file.stem)
        for key in (str(file), file.as_posix(), file.name):
            mapping[key] = metadata
    return mapping


def _expand_plot_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    data = _object(item.get("data", {}), f"{item.get('name', 'plot')}.data")
    display = _object(item.get("display", {}), f"{item.get('name', 'plot')}.display")
    style = _object(item.get("style", {}), f"{item.get('name', 'plot')}.style")

    spec = {
        key: value
        for key, value in item.items()
        if key not in {"type", "recipe", "kind", "data", "display", "style"}
    }
    kind = item.get("kind") or item.get("type") or item.get("recipe")
    if not kind:
        raise ExperimentError(f"{item.get('name', 'plot')}: missing type/kind")
    spec["kind"] = _normalize_kind(kind)

    spec.update(_map_data_section(data))
    spec.update(_map_display_section(display))
    if style:
        existing_style = spec.get("style")
        spec["style"] = {**(existing_style if isinstance(existing_style, dict) else {}), **style}

    return [_apply_plot_aliases(spec)]


def _map_data_section(data: dict[str, Any]) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    aliases = {
        "filter": "filters",
        "where": "filters",
        "value": "value",
        "metric": "metric",
        "x": "x",
        "y": "y",
        "source": "source",
        "group_by": "group_by",
        "facet_by": "facet_by",
        "aggregate": "aggregate",
        "annotations": "annotations",
    }
    for key, value in data.items():
        mapped[aliases.get(key, key)] = value
    return mapped


def _map_display_section(display: dict[str, Any]) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    aliases = {
        "size": "figsize",
        "dimensions": "figsize",
        "width": "width",
        "height": "height",
        "legend": "legend",
        "show_legend": "legend",
        "title": "title",
        "x_label": "x_label",
        "y_label": "y_label",
        "value_label": "colorbar_label",
        "colors": "colors",
        "palette": "palette",
        "color": "color",
        "cmap": "cmap",
        "dpi": "dpi",
        "marker": "marker",
        "line_width": "linewidth",
        "linewidth": "linewidth",
        "xlim": "xlim",
        "ylim": "ylim",
        "log_x": "log_x",
        "log_y": "log_y",
    }
    for key, value in display.items():
        mapped[aliases.get(key, key)] = value
    return mapped


def _apply_plot_aliases(spec: dict[str, Any]) -> dict[str, Any]:
    source = str(spec.get("source") or "intervals")
    if source not in SUMMARY_SOURCES:
        return spec

    spec = dict(spec)
    for key in ("x", "y", "value", "metric"):
        if spec.get(key) == "rtt_ms":
            spec[key] = "rtt_config_ms"
    for key in ("group_by", "facet_by", "annotations"):
        spec[key] = _replace_field_aliases(spec.get(key))
    filters = spec.get("filters")
    if isinstance(filters, dict) and "rtt_ms" in filters:
        filters = dict(filters)
        filters["rtt_config_ms"] = filters.pop("rtt_ms")
        spec["filters"] = filters
    return spec


def _replace_field_aliases(value: Any) -> Any:
    if isinstance(value, list):
        return ["rtt_config_ms" if item == "rtt_ms" else item for item in value]
    if value == "rtt_ms":
        return "rtt_config_ms"
    return value


def _validate_plot_spec(spec: dict[str, Any], sources: dict[str, Any], warnings: list[str]) -> None:
    name = str(spec.get("name") or "plot")
    source = str(spec.get("source") or "intervals")
    if source not in sources:
        valid = ", ".join(sorted(sources))
        raise ExperimentError(f"{name}: unknown source '{source}'. Valid sources: {valid}")

    df = sources[source]
    if df.empty:
        warnings.append(f"{name}: source '{source}' is empty")
        return

    filters = spec.get("filters", spec.get("filter", {}))
    if isinstance(filters, dict):
        missing_filters = [col for col in filters if col not in df.columns]
        if missing_filters:
            raise ExperimentError(f"{name}: missing filter column(s): {', '.join(missing_filters)}")

    required = _required_plot_columns(spec)
    missing = [col for col in required if col and col not in df.columns]
    if missing:
        raise ExperimentError(f"{name}: missing column(s): {', '.join(missing)}")


def _required_plot_columns(spec: dict[str, Any]) -> list[str]:
    kind = str(spec.get("kind") or "").lower()
    columns: list[str] = []
    if kind in {"line", "time_series", "timeseries", "bar", "heatmap"}:
        columns.append(str(spec.get("x") or ""))
    if kind in {"scatter", "heatmap"}:
        columns.append(str(spec.get("y") or ""))
    if kind in {"cdf", "ccdf", "hist", "histogram", "box", "boxplot", "line", "time_series", "timeseries", "bar"}:
        columns.append(str(spec.get("metric") or spec.get("value") or spec.get("y") or ""))
    if kind == "heatmap":
        columns.append(str(spec.get("metric") or spec.get("value") or ""))
    for key in ("group_by", "facet_by", "annotations"):
        columns.extend(_as_list(spec.get(key)))
    return [col for col in columns if col]


def _resolve_time_mode(config: dict[str, Any], metadata: dict[str, dict[str, Any]]) -> str:
    configured = config.get("time_mode")
    if configured:
        mode = str(configured).strip().lower()
        if mode not in VALID_TIME_MODES:
            valid = ", ".join(sorted(VALID_TIME_MODES))
            raise ExperimentError(f"time_mode must be one of: {valid}")
        return mode

    seen: set[int] = set()
    for values in metadata.values():
        marker = id(values)
        if marker in seen:
            continue
        seen.add(marker)
        offset = _coerce(values.get("start_offset_s"))
        if isinstance(offset, (int, float)) and offset != 0:
            return "offset"
    return "relative"


def _filename_pattern_to_regex(pattern: str) -> re.Pattern[str]:
    fields: set[str] = set()
    parts: list[str] = []
    last = 0
    for match in re.finditer(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", pattern):
        field = match.group(1)
        if field in fields:
            raise ExperimentError(f"Duplicate field '{field}' in filename_pattern")
        fields.add(field)
        parts.append(re.escape(pattern[last : match.start()]))
        parts.append(f"(?P<{field}>[^/]+?)")
        last = match.end()
    parts.append(re.escape(pattern[last:]))
    if not fields:
        raise ExperimentError("infer.filename_pattern must contain at least one {field}")
    return re.compile("^" + "".join(parts) + "$")


def _compile_metadata_regex(pattern: str) -> re.Pattern[str]:
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise ExperimentError(f"infer filename/path regex is invalid: {exc}") from exc
    if not regex.groupindex:
        raise ExperimentError("infer filename/path regex must include named groups such as (?P<rtt_ms>\\d+)")
    return regex


def _regex_source(infer: dict[str, Any]) -> tuple[str, Any] | None:
    for key in ("filename_regex", "path_regex"):
        if infer.get(key):
            return key, infer[key]
    return None


def _pattern_source(infer: dict[str, Any]) -> tuple[str, Any] | None:
    for key in ("filename_pattern", "path_pattern"):
        if infer.get(key):
            return key, infer[key]
    return None


def _resolve_path(base_dir: Path, value: Any) -> Path:
    path = Path(str(value))
    return (path if path.is_absolute() else base_dir / path).resolve()


def _relative_or_name(base_dir: Path, file: Path) -> str:
    try:
        return file.relative_to(base_dir).as_posix()
    except ValueError:
        return file.name


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _object(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ExperimentError(f"'{name}' must be an object")
    return value


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _normalize_kind(kind: Any) -> str:
    value = str(kind).strip().lower().replace("-", "_")
    aliases = {
        "time_series": "time_series",
        "timeseries": "time_series",
        "time": "time_series",
        "distribution": "cdf",
    }
    return aliases.get(value, value)


def _coerce(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if stripped == "":
        return None
    lowered = stripped.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        if any(char in stripped for char in [".", "e", "E"]):
            return float(stripped)
        return int(stripped)
    except ValueError:
        return stripped


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", "none"}
    return bool(value)


def _has_glob_chars(pattern: str) -> bool:
    return any(char in pattern for char in "*?[")
