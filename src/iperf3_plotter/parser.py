from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore", message="Pandas requires version .*", category=UserWarning)

import pandas as pd

from .manifest import metadata_for_path


class IperfParseError(ValueError):
    """Raised when a file does not look like iperf3 JSON output."""


KNOWN_METADATA_KEYS = {
    "file",
    "path",
    "source_file",
    "run_id",
    "flow_id",
    "label",
    "flow_label",
    "cc_algo",
    "scenario",
    "group",
    "start_offset_s",
    "rtt_ms",
    "bottleneck_mbps",
    "buffer_bdp",
}


def parse_files(
    paths: list[Path],
    metadata_by_file: dict[str, dict[str, Any]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Parse one or more iperf3 JSON files into interval, summary, and run tables."""

    interval_records: list[dict[str, Any]] = []
    summary_records: list[dict[str, Any]] = []
    run_records: list[dict[str, Any]] = []

    for path in paths:
        metadata = metadata_for_path(metadata_by_file, path)
        intervals, summaries, run = parse_file(path, metadata=metadata)
        interval_records.extend(intervals)
        summary_records.extend(summaries)
        run_records.append(run)

    intervals_df = pd.DataFrame.from_records(interval_records)
    summaries_df = pd.DataFrame.from_records(summary_records)
    runs_df = pd.DataFrame.from_records(run_records)
    _add_global_elapsed_time(intervals_df, runs_df)

    return intervals_df, summaries_df, runs_df


def parse_file(
    path: Path,
    *,
    metadata: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Parse a single iperf3 JSON file."""

    path = Path(path)
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise IperfParseError(f"{path} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or "intervals" not in data or "start" not in data:
        raise IperfParseError(f"{path} does not look like iperf3 JSON output")

    metadata = metadata or {}
    run_id = str(metadata.get("run_id") or path.stem)
    flow_id = str(metadata.get("flow_id") or run_id)
    flow_label = str(metadata.get("label") or metadata.get("flow_label") or flow_id)
    cc_algo = metadata.get("cc_algo")
    scenario = metadata.get("scenario")
    group = metadata.get("group")
    start_offset_s = _float(metadata.get("start_offset_s")) or 0.0
    rtt_config_ms = _float(metadata.get("rtt_ms"))
    bottleneck_mbps = _float(metadata.get("bottleneck_mbps"))
    buffer_bdp = _float(metadata.get("buffer_bdp"))
    extra_metadata = _extra_metadata(metadata)
    source_file = str(path)
    start = _dict(data.get("start"))
    end = _dict(data.get("end"))
    timestamp = _dict(start.get("timestamp"))
    test_start = _dict(start.get("test_start"))
    connected = _socket_map(start.get("connected"))
    epoch = _float(timestamp.get("timesecs"))
    protocol = _str(test_start.get("protocol"), "unknown")
    num_streams = _int(test_start.get("num_streams"))
    reverse = _bool(test_start.get("reverse"))

    stream_ordinals: dict[str, int] = {}
    interval_records: list[dict[str, Any]] = []

    for interval_index, interval in enumerate(_list(data.get("intervals"))):
        interval_dict = _dict(interval)
        for stream_position, stream in enumerate(_list(interval_dict.get("streams"))):
            stream_dict = _dict(stream)
            socket = stream_dict.get("socket")
            socket_key = _socket_key(socket, stream_position)
            stream_index = stream_ordinals.setdefault(socket_key, len(stream_ordinals) + 1)
            start_s = _float(stream_dict.get("start"))
            end_s = _float(stream_dict.get("end"))
            duration_s = _float(stream_dict.get("seconds"))

            interval_records.append(
                _with_extra_metadata(
                    {
                        "source_file": source_file,
                        "run_id": run_id,
                        "flow_id": flow_id,
                        "flow_label": flow_label,
                        "cc_algo": cc_algo,
                        "scenario": scenario,
                        "group": group,
                        "start_offset_s": start_offset_s,
                        "rtt_config_ms": rtt_config_ms,
                        "bottleneck_mbps": bottleneck_mbps,
                        "buffer_bdp": buffer_bdp,
                        "stream_id": f"{flow_id}:stream-{stream_index}",
                        "stream_index": stream_index,
                        "socket": socket,
                        "local_host": connected.get(socket_key, {}).get("local_host"),
                        "local_port": connected.get(socket_key, {}).get("local_port"),
                        "remote_host": connected.get(socket_key, {}).get("remote_host"),
                        "remote_port": connected.get(socket_key, {}).get("remote_port"),
                        "protocol": protocol,
                        "num_streams": num_streams,
                        "reverse": reverse,
                        "interval_index": interval_index,
                        "start_s": start_s,
                        "end_s": end_s,
                        "midpoint_s": _midpoint(start_s, end_s),
                        "offset_start_s": _offset(start_s, start_offset_s),
                        "offset_end_s": _offset(end_s, start_offset_s),
                        "offset_midpoint_s": _offset(_midpoint(start_s, end_s), start_offset_s),
                        "absolute_start_s": _absolute(epoch, start_s),
                        "absolute_end_s": _absolute(epoch, end_s),
                        "duration_s": duration_s,
                        "bytes": _float(stream_dict.get("bytes")),
                        "transfer_mib": _bytes_to_mib(stream_dict.get("bytes")),
                        "throughput_bps": _float(stream_dict.get("bits_per_second")),
                        "throughput_mbps": _bps_to_mbps(stream_dict.get("bits_per_second")),
                        "retransmits": _float(stream_dict.get("retransmits")),
                        "cwnd_bytes": _float(stream_dict.get("snd_cwnd")),
                        "cwnd_kib": _bytes_to_kib(stream_dict.get("snd_cwnd")),
                        "rtt_us": _float(stream_dict.get("rtt")),
                        "rtt_ms": _us_to_ms(stream_dict.get("rtt")),
                        "rttvar_us": _float(stream_dict.get("rttvar")),
                        "rttvar_ms": _us_to_ms(stream_dict.get("rttvar")),
                        "pmtu_bytes": _float(stream_dict.get("pmtu")),
                        "omitted": _bool(stream_dict.get("omitted")),
                        "jitter_ms": _float(stream_dict.get("jitter_ms")),
                        "lost_packets": _float(stream_dict.get("lost_packets")),
                        "packets": _float(stream_dict.get("packets")),
                        "lost_percent": _float(stream_dict.get("lost_percent")),
                    },
                    extra_metadata,
                )
            )

    summary_records = _summary_records(
        end=end,
        run_id=run_id,
        source_file=source_file,
        protocol=protocol,
        reverse=reverse,
        flow_id=flow_id,
        flow_label=flow_label,
        cc_algo=cc_algo,
        scenario=scenario,
        group=group,
        start_offset_s=start_offset_s,
        rtt_config_ms=rtt_config_ms,
        bottleneck_mbps=bottleneck_mbps,
        buffer_bdp=buffer_bdp,
        extra_metadata=extra_metadata,
        connected=connected,
        stream_ordinals=stream_ordinals,
    )

    run_record = _with_extra_metadata(
        {
            "source_file": source_file,
            "run_id": run_id,
            "flow_id": flow_id,
            "flow_label": flow_label,
            "cc_algo": cc_algo,
            "scenario": scenario,
            "group": group,
            "start_offset_s": start_offset_s,
            "rtt_config_ms": rtt_config_ms,
            "bottleneck_mbps": bottleneck_mbps,
            "buffer_bdp": buffer_bdp,
            "timestamp": timestamp.get("time"),
            "epoch_s": epoch,
            "protocol": protocol,
            "num_streams": num_streams,
            "reverse": reverse,
            "duration_s": _float(test_start.get("duration")),
            "omit_s": _float(test_start.get("omit")),
            "block_size_bytes": _float(test_start.get("blksize")),
            "tos": _float(test_start.get("tos")),
            "local_host": _first_connected(connected, "local_host"),
            "remote_host": _first_connected(connected, "remote_host"),
        },
        extra_metadata,
    )

    return interval_records, summary_records, run_record


def _summary_records(
    *,
    end: dict[str, Any],
    run_id: str,
    source_file: str,
    protocol: str,
    reverse: bool | None,
    flow_id: str,
    flow_label: str,
    cc_algo: Any,
    scenario: Any,
    group: Any,
    start_offset_s: float,
    rtt_config_ms: float | None,
    bottleneck_mbps: float | None,
    buffer_bdp: float | None,
    extra_metadata: dict[str, Any],
    connected: dict[str, dict[str, Any]],
    stream_ordinals: dict[str, int],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for stream_position, stream in enumerate(_list(end.get("streams"))):
        stream_dict = _dict(stream)
        for direction in ("sender", "receiver"):
            details = _dict(stream_dict.get(direction))
            if not details:
                continue
            socket = details.get("socket")
            socket_key = _socket_key(socket, stream_position)
            stream_index = stream_ordinals.get(socket_key, stream_position + 1)
            records.append(
                _with_extra_metadata(
                    _summary_row(
                        details,
                        source_file=source_file,
                        run_id=run_id,
                        flow_id=flow_id,
                        flow_label=flow_label,
                        cc_algo=cc_algo,
                        scenario=scenario,
                        group=group,
                        start_offset_s=start_offset_s,
                        rtt_config_ms=rtt_config_ms,
                        bottleneck_mbps=bottleneck_mbps,
                        buffer_bdp=buffer_bdp,
                        stream_id=f"{flow_id}:stream-{stream_index}",
                        stream_index=stream_index,
                        direction=direction,
                        protocol=protocol,
                        reverse=reverse,
                        connected=connected.get(socket_key, {}),
                    ),
                    extra_metadata,
                )
            )

    for key in ("sum", "sum_sent", "sum_received"):
        details = _dict(end.get(key))
        if details:
            records.append(
                _with_extra_metadata(
                    _summary_row(
                        details,
                        source_file=source_file,
                        run_id=run_id,
                        flow_id=flow_id,
                        flow_label=flow_label,
                        cc_algo=cc_algo,
                        scenario=scenario,
                        group=group,
                        start_offset_s=start_offset_s,
                        rtt_config_ms=rtt_config_ms,
                        bottleneck_mbps=bottleneck_mbps,
                        buffer_bdp=buffer_bdp,
                        stream_id=f"{flow_id}:aggregate",
                        stream_index=0,
                        direction=key,
                        protocol=protocol,
                        reverse=reverse,
                        connected={},
                    ),
                    extra_metadata,
                )
            )

    return records


def _summary_row(
    details: dict[str, Any],
    *,
    source_file: str,
    run_id: str,
    flow_id: str,
    flow_label: str,
    cc_algo: Any,
    scenario: Any,
    group: Any,
    start_offset_s: float,
    rtt_config_ms: float | None,
    bottleneck_mbps: float | None,
    buffer_bdp: float | None,
    stream_id: str,
    stream_index: int,
    direction: str,
    protocol: str,
    reverse: bool | None,
    connected: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source_file": source_file,
        "run_id": run_id,
        "flow_id": flow_id,
        "flow_label": flow_label,
        "cc_algo": cc_algo,
        "scenario": scenario,
        "group": group,
        "start_offset_s": start_offset_s,
        "rtt_config_ms": rtt_config_ms,
        "bottleneck_mbps": bottleneck_mbps,
        "buffer_bdp": buffer_bdp,
        "stream_id": stream_id,
        "stream_index": stream_index,
        "direction": direction,
        "socket": details.get("socket"),
        "local_host": connected.get("local_host"),
        "local_port": connected.get("local_port"),
        "remote_host": connected.get("remote_host"),
        "remote_port": connected.get("remote_port"),
        "protocol": protocol,
        "reverse": reverse,
        "start_s": _float(details.get("start")),
        "end_s": _float(details.get("end")),
        "duration_s": _float(details.get("seconds")),
        "bytes": _float(details.get("bytes")),
        "transfer_mib": _bytes_to_mib(details.get("bytes")),
        "throughput_bps": _float(details.get("bits_per_second")),
        "throughput_mbps": _bps_to_mbps(details.get("bits_per_second")),
        "retransmits": _float(details.get("retransmits")),
        "max_cwnd_bytes": _float(details.get("max_snd_cwnd")),
        "max_cwnd_kib": _bytes_to_kib(details.get("max_snd_cwnd")),
        "min_rtt_us": _float(details.get("min_rtt")),
        "mean_rtt_us": _float(details.get("mean_rtt")),
        "max_rtt_us": _float(details.get("max_rtt")),
        "min_rtt_ms": _us_to_ms(details.get("min_rtt")),
        "mean_rtt_ms": _us_to_ms(details.get("mean_rtt")),
        "max_rtt_ms": _us_to_ms(details.get("max_rtt")),
        "jitter_ms": _float(details.get("jitter_ms")),
        "lost_packets": _float(details.get("lost_packets")),
        "packets": _float(details.get("packets")),
        "lost_percent": _float(details.get("lost_percent")),
    }


def _socket_map(connected: Any) -> dict[str, dict[str, Any]]:
    sockets: dict[str, dict[str, Any]] = {}
    for position, entry in enumerate(_list(connected)):
        entry_dict = _dict(entry)
        socket_key = _socket_key(entry_dict.get("socket"), position)
        sockets[socket_key] = entry_dict
    return sockets


def _socket_key(socket: Any, position: int) -> str:
    if socket is None:
        return f"position-{position}"
    return str(socket)


def _first_connected(connected: dict[str, dict[str, Any]], key: str) -> Any:
    for value in connected.values():
        if value.get(key) is not None:
            return value.get(key)
    return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _float(value)
    return int(number) if number is not None else None


def _bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.lower() in {"true", "1", "yes"}
    return None


def _str(value: Any, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _bps_to_mbps(value: Any) -> float | None:
    number = _float(value)
    return number / 1_000_000 if number is not None else None


def _bytes_to_mib(value: Any) -> float | None:
    number = _float(value)
    return number / (1024 * 1024) if number is not None else None


def _bytes_to_kib(value: Any) -> float | None:
    number = _float(value)
    return number / 1024 if number is not None else None


def _us_to_ms(value: Any) -> float | None:
    number = _float(value)
    return number / 1000 if number is not None else None


def _absolute(epoch: float | None, offset: float | None) -> float | None:
    if epoch is None or offset is None:
        return None
    return epoch + offset


def _offset(value: float | None, offset: float) -> float | None:
    if value is None:
        return None
    return value + offset


def _midpoint(start_s: float | None, end_s: float | None) -> float | None:
    if start_s is None or end_s is None:
        return None
    return start_s + ((end_s - start_s) / 2)


def _extra_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if key not in KNOWN_METADATA_KEYS}


def _with_extra_metadata(record: dict[str, Any], extra_metadata: dict[str, Any]) -> dict[str, Any]:
    for key, value in extra_metadata.items():
        record.setdefault(key, value)
    return record


def _add_global_elapsed_time(intervals: pd.DataFrame, runs: pd.DataFrame) -> None:
    """Add an experiment-wide X-axis where the earliest observed flow is time 0."""

    if intervals.empty:
        return

    if "absolute_start_s" in intervals.columns and intervals["absolute_start_s"].notna().any():
        base = intervals["absolute_start_s"].min()
        intervals["global_start_s"] = intervals["absolute_start_s"] - base
        intervals["global_end_s"] = intervals["absolute_end_s"] - base
        intervals["global_midpoint_s"] = intervals["global_start_s"] + (
            (intervals["global_end_s"] - intervals["global_start_s"]) / 2
        )
        if not runs.empty and "epoch_s" in runs.columns:
            runs["global_start_s"] = runs["epoch_s"] - base
        return

    if "offset_start_s" in intervals.columns and intervals["offset_start_s"].notna().any():
        base = intervals["offset_start_s"].min()
        intervals["global_start_s"] = intervals["offset_start_s"] - base
        intervals["global_end_s"] = intervals["offset_end_s"] - base
        intervals["global_midpoint_s"] = intervals["global_start_s"] + (
            (intervals["global_end_s"] - intervals["global_start_s"]) / 2
        )
        if not runs.empty and "start_offset_s" in runs.columns:
            runs["global_start_s"] = runs["start_offset_s"] - base
