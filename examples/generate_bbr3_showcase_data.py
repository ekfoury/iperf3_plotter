#!/usr/bin/env python3
"""Generate a small synthetic iperf3 JSON corpus for the docs.

The data is intentionally synthetic. It is shaped like common BBRv3 paper
experiments so the experiment.yaml examples can be rendered by iperf3_plotter
without requiring a network lab or vendoring another repository's datasets.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Iterable

import yaml


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic BBRv3 showcase iperf3 JSON files.")
    parser.add_argument("--out", type=Path, default=Path("/tmp/iperf3-plotter-bbr3-showcase"))
    args = parser.parse_args()

    out_dir = args.out
    runs_dir = out_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    rows.extend(rtt_sweep(runs_dir))
    rows.extend(loss_sweep(runs_dir))
    rows.extend(buffer_rtt_sweep(runs_dir))
    rows.extend(rtt_unfairness(runs_dir))
    rows.extend(staggered_starts(runs_dir))
    rows.extend(fct_runs(runs_dir))
    rows.extend(bdp_heatmap(runs_dir))

    experiment = out_dir / "experiment.yaml"
    experiment.write_text(
        yaml.safe_dump(
            {
                "name": "bbr3_showcase",
                "time_mode": "offset",
                "default_plots": False,
                "inputs": {"runs": rows},
                "plots": showcase_plots(),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    print(f"Wrote {len(rows)} JSON files to {runs_dir}")
    print(f"Wrote experiment file to {experiment}")


def rtt_sweep(runs_dir: Path) -> list[dict[str, object]]:
    rows = []
    for rtt_ms in [2, 20, 40, 80, 100]:
        cubic_mbps = {2: 940, 20: 410, 40: 330, 80: 250, 100: 220}[rtt_ms]
        bbrv3_mbps = {2: 925, 20: 895, 40: 890, 80: 885, 100: 875}[rtt_ms]
        rows.append(
            add_run(
                runs_dir,
                f"rtt_sweep_cubic_rtt{rtt_ms}.json",
                flow_id=f"cubic_rtt{rtt_ms}",
                flow_label=f"CUBIC {rtt_ms} ms",
                scenario="rtt_sweep",
                cc_algo="cubic",
                throughput_mbps=cubic_mbps,
                rtt_ms=rtt_ms,
                retransmits_total=40 + (rtt_ms * 4),
                loss_percent=0.025,
                bottleneck_mbps=1000,
            )
        )
        rows.append(
            add_run(
                runs_dir,
                f"rtt_sweep_bbrv3_rtt{rtt_ms}.json",
                flow_id=f"bbrv3_rtt{rtt_ms}",
                flow_label=f"BBRv3 {rtt_ms} ms",
                scenario="rtt_sweep",
                cc_algo="bbrv3",
                throughput_mbps=bbrv3_mbps,
                rtt_ms=rtt_ms,
                retransmits_total=12 + int(rtt_ms * 0.5),
                loss_percent=0.025,
                bottleneck_mbps=1000,
            )
        )
    return rows


def loss_sweep(runs_dir: Path) -> list[dict[str, object]]:
    rows = []
    values = [
        (0.001, 930, 30),
        (0.01, 925, 90),
        (0.1, 890, 500),
        (1, 760, 5500),
        (5, 520, 22000),
        (10, 390, 48000),
    ]
    for loss_percent, throughput_mbps, retransmits in values:
        rows.append(
            add_run(
                runs_dir,
                f"loss_sweep_bbrv3_loss{slug(loss_percent)}.json",
                flow_id=f"bbrv3_loss{slug(loss_percent)}",
                flow_label=f"BBRv3 {loss_percent}% loss",
                scenario="loss_sweep",
                cc_algo="bbrv3",
                throughput_mbps=throughput_mbps,
                rtt_ms=20,
                retransmits_total=retransmits,
                loss_percent=loss_percent,
                bottleneck_mbps=1000,
            )
        )
    return rows


def buffer_rtt_sweep(runs_dir: Path) -> list[dict[str, object]]:
    rows = []
    for aqm in ["taildrop", "fq_codel"]:
        for trial in [1, 2, 3]:
            trial_factor = 0.96 + (trial * 0.02)
            for rtt_ms in [20, 50, 100]:
                for buffer_bdp in [0.25, 1, 4]:
                    efficiency = 0.62 + (0.08 * math.log2(buffer_bdp + 1)) - (0.0012 * rtt_ms)
                    if aqm == "fq_codel":
                        efficiency += 0.05
                    total_mbps = max(220, 1000 * efficiency) * trial_factor
                    flows = [
                        ("cubic", 0.34 if aqm == "fq_codel" else 0.43),
                        ("bbrv3", 0.33 if aqm == "fq_codel" else 0.30),
                        ("bbrv3", 0.33 if aqm == "fq_codel" else 0.27),
                    ]
                    for flow_index, (cc_algo, share) in enumerate(flows, start=1):
                        throughput_mbps = total_mbps * share
                        rows.append(
                            add_run(
                                runs_dir,
                                f"buffer_rtt_{aqm}_rtt{rtt_ms}_bdp{slug(buffer_bdp)}_trial{trial}_flow{flow_index}_{cc_algo}.json",
                                flow_id=f"{aqm}_rtt{rtt_ms}_bdp{slug(buffer_bdp)}_t{trial}_f{flow_index}",
                                flow_label=f"{cc_algo.upper()} flow {flow_index}",
                                scenario="buffer_rtt_sweep",
                                cc_algo=cc_algo,
                                cc_mix="cubic_vs_bbrv3",
                                aqm=aqm,
                                throughput_mbps=throughput_mbps,
                                rtt_ms=rtt_ms,
                                retransmits_total=int((rtt_ms * (1.8 if aqm == "taildrop" else 0.6)) / max(buffer_bdp, 0.25)),
                                buffer_bdp=buffer_bdp,
                                bottleneck_mbps=1000,
                                propagation_delay_ms=rtt_ms,
                                trial=trial,
                                num_flows=3,
                                num_cubic_flows=1,
                                num_bbrv3_flows=2,
                                parallel_streams=3,
                            )
                        )
    return rows


def rtt_unfairness(runs_dir: Path) -> list[dict[str, object]]:
    rows = []
    configs = {
        "taildrop": {
            0.2: (650, 210),
            0.5: (610, 260),
            1: (560, 330),
            10: (470, 440),
            50: (455, 450),
        },
        "fq_codel": {
            0.2: (440, 420),
            0.5: (445, 430),
            1: (450, 440),
            10: (455, 450),
            50: (455, 452),
        },
    }
    for aqm, bdp_values in configs.items():
        for buffer_bdp, (flow_20_mbps, flow_100_mbps) in bdp_values.items():
            rows.append(
                add_run(
                    runs_dir,
                    f"rtt_unfair_{aqm}_bdp{slug(buffer_bdp)}_20ms.json",
                    flow_id=f"{aqm}_bdp{slug(buffer_bdp)}_20ms",
                    flow_label="20 ms",
                    scenario="rtt_unfairness",
                    cc_algo="bbrv3",
                    cc_mix="bbrv3_only",
                    aqm=aqm,
                    throughput_mbps=flow_20_mbps,
                    rtt_ms=20,
                    retransmits_total=120 if aqm == "taildrop" else 20,
                    buffer_bdp=buffer_bdp,
                    bottleneck_mbps=1000,
                    propagation_delay_ms=20,
                    num_flows=2,
                    num_bbrv3_flows=2,
                )
            )
            rows.append(
                add_run(
                    runs_dir,
                    f"rtt_unfair_{aqm}_bdp{slug(buffer_bdp)}_100ms.json",
                    flow_id=f"{aqm}_bdp{slug(buffer_bdp)}_100ms",
                    flow_label="100 ms",
                    scenario="rtt_unfairness",
                    cc_algo="bbrv3",
                    cc_mix="bbrv3_only",
                    aqm=aqm,
                    throughput_mbps=flow_100_mbps,
                    rtt_ms=100,
                    retransmits_total=80 if aqm == "taildrop" else 18,
                    buffer_bdp=buffer_bdp,
                    bottleneck_mbps=1000,
                    propagation_delay_ms=100,
                    num_flows=2,
                    num_bbrv3_flows=2,
                )
            )
    return rows


def staggered_starts(runs_dir: Path) -> list[dict[str, object]]:
    rows = []
    rows.append(
        add_run(
            runs_dir,
            "staggered_cubic.json",
            flow_id="cubic_long",
            flow_label="CUBIC flow",
            scenario="staggered_coexistence",
            cc_algo="cubic",
            cc_mix="cubic_vs_bbrv3",
            throughput_profile=[900] * 40 + [380] * 40 + [230] * 40 + [170] * 60,
            rtt_ms=20,
            start_offset_s=0,
            bottleneck_mbps=1000,
            num_flows=4,
            num_cubic_flows=1,
            num_bbrv3_flows=3,
        )
    )
    rows.append(
        add_run(
            runs_dir,
            "staggered_bbrv3_1.json",
            flow_id="bbrv3_1",
            flow_label="BBRv3 flow 1",
            scenario="staggered_coexistence",
            cc_algo="bbrv3",
            cc_mix="cubic_vs_bbrv3",
            throughput_profile=[520] * 40 + [310] * 40 + [230] * 60,
            rtt_ms=20,
            start_offset_s=40,
            bottleneck_mbps=1000,
            num_flows=4,
            num_cubic_flows=1,
            num_bbrv3_flows=3,
        )
    )
    rows.append(
        add_run(
            runs_dir,
            "staggered_bbrv3_2.json",
            flow_id="bbrv3_2",
            flow_label="BBRv3 flow 2",
            scenario="staggered_coexistence",
            cc_algo="bbrv3",
            cc_mix="cubic_vs_bbrv3",
            throughput_profile=[390] * 40 + [250] * 60,
            rtt_ms=20,
            start_offset_s=80,
            bottleneck_mbps=1000,
            num_flows=4,
            num_cubic_flows=1,
            num_bbrv3_flows=3,
        )
    )
    return rows


def fct_runs(runs_dir: Path) -> list[dict[str, object]]:
    rows = []
    cubic_durations = [9.0, 8.5, 7.8, 8.1, 9.3, 7.4, 8.9, 7.9, 8.4, 9.1]
    bbrv3_durations = [5.1, 4.8, 4.6, 5.3, 4.9, 4.7, 5.0, 4.5, 5.2, 4.8]
    for index, duration in enumerate(cubic_durations, start=1):
        rows.append(
            add_run(
                runs_dir,
                f"fct_cubic_trial{index}.json",
                flow_id=f"cubic_fct_t{index}",
                flow_label="CUBIC short flow",
                scenario="fct",
                cc_algo="cubic",
                cc_mix="cubic_vs_bbrv3",
                throughput_mbps=180,
                duration_s=duration,
                rtt_ms=20,
                transfer_size_mb=10,
                bottleneck_mbps=1000,
            )
        )
    for index, duration in enumerate(bbrv3_durations, start=1):
        rows.append(
            add_run(
                runs_dir,
                f"fct_bbrv3_trial{index}.json",
                flow_id=f"bbrv3_fct_t{index}",
                flow_label="BBRv3 short flow",
                scenario="fct",
                cc_algo="bbrv3",
                cc_mix="cubic_vs_bbrv3",
                throughput_mbps=260,
                duration_s=duration,
                rtt_ms=20,
                transfer_size_mb=10,
                bottleneck_mbps=1000,
            )
        )
    return rows


def bdp_heatmap(runs_dir: Path) -> list[dict[str, object]]:
    rows = []
    for bottleneck_mbps in [100, 500, 1000]:
        for delay_ms in [20, 80, 140]:
            skew = (delay_ms / 140) * (1000 / bottleneck_mbps) * 0.12
            total = bottleneck_mbps * 0.88
            cubic_share = min(0.72, max(0.42, 0.5 + skew))
            cubic_mbps = total * cubic_share
            bbrv3_mbps = total - cubic_mbps
            common = {
                "scenario": "bdp_sweep",
                "cc_mix": "cubic_vs_bbrv3",
                "buffer_bdp": 1,
                "loss_percent": 0,
                "bottleneck_mbps": bottleneck_mbps,
                "propagation_delay_ms": delay_ms,
                "num_flows": 2,
                "num_cubic_flows": 1,
                "num_bbrv3_flows": 1,
            }
            rows.append(
                add_run(
                    runs_dir,
                    f"bdp_bw{bottleneck_mbps}_d{delay_ms}_cubic.json",
                    flow_id=f"cubic_bw{bottleneck_mbps}_d{delay_ms}",
                    flow_label=f"CUBIC {bottleneck_mbps}M/{delay_ms}ms",
                    cc_algo="cubic",
                    throughput_mbps=cubic_mbps,
                    rtt_ms=delay_ms,
                    **common,
                )
            )
            rows.append(
                add_run(
                    runs_dir,
                    f"bdp_bw{bottleneck_mbps}_d{delay_ms}_bbrv3.json",
                    flow_id=f"bbrv3_bw{bottleneck_mbps}_d{delay_ms}",
                    flow_label=f"BBRv3 {bottleneck_mbps}M/{delay_ms}ms",
                    cc_algo="bbrv3",
                    throughput_mbps=bbrv3_mbps,
                    rtt_ms=delay_ms,
                    **common,
                )
            )
    return rows


def add_run(
    runs_dir: Path,
    filename: str,
    *,
    flow_id: str,
    flow_label: str,
    scenario: str,
    cc_algo: str,
    throughput_mbps: float | None = None,
    throughput_profile: list[float] | None = None,
    duration_s: float = 12,
    rtt_ms: float = 20,
    retransmits_total: int = 0,
    start_offset_s: float = 0,
    cc_mix: str = "",
    aqm: str = "taildrop",
    trial: int = 1,
    buffer_bdp: float = 1,
    loss_percent: float = 0,
    bottleneck_mbps: float = 1000,
    propagation_delay_ms: float | None = None,
    num_flows: int = 1,
    num_cubic_flows: int = 0,
    num_bbrv3_flows: int = 0,
    transfer_size_mb: float | None = None,
    parallel_streams: int = 3,
) -> dict[str, object]:
    path = runs_dir / filename
    profile = throughput_profile or [float(throughput_mbps or 100)] * max(1, math.ceil(duration_s))
    write_iperf_json(path, profile, rtt_ms=rtt_ms, retransmits_total=retransmits_total, parallel_streams=parallel_streams)
    return {
        "file": f"runs/{filename}",
        "flow_id": flow_id,
        "flow_label": flow_label,
        "scenario": scenario,
        "cc_algo": cc_algo,
        "cc_mix": cc_mix,
        "aqm": aqm,
        "trial": trial,
        "start_offset_s": start_offset_s,
        "rtt_ms": rtt_ms,
        "buffer_bdp": buffer_bdp,
        "loss_percent": loss_percent,
        "bottleneck_mbps": bottleneck_mbps,
        "propagation_delay_ms": propagation_delay_ms if propagation_delay_ms is not None else rtt_ms,
        "num_flows": num_flows,
        "num_cubic_flows": num_cubic_flows,
        "num_bbrv3_flows": num_bbrv3_flows,
        "transfer_size_mb": transfer_size_mb or "",
    }


def write_iperf_json(
    path: Path,
    throughput_profile_mbps: Iterable[float],
    *,
    rtt_ms: float,
    retransmits_total: int,
    parallel_streams: int,
) -> None:
    profile = list(throughput_profile_mbps)
    intervals = []
    stream_totals = {stream_index: {"bytes": 0, "retransmits": 0} for stream_index in range(1, parallel_streams + 1)}
    for index, throughput_mbps in enumerate(profile):
        wave = 1 + (0.04 * math.sin(index / 3))
        streams = []
        for stream_index in range(1, parallel_streams + 1):
            stream_mbps = throughput_mbps / parallel_streams
            bps = stream_mbps * wave * 1_000_000
            bytes_sent = int(bps / 8)
            interval_retransmits = int(round(retransmits_total / max(1, len(profile) * parallel_streams)))
            stream_totals[stream_index]["bytes"] += bytes_sent
            stream_totals[stream_index]["retransmits"] += interval_retransmits
            streams.append(
                {
                    "socket": stream_index,
                    "start": index,
                    "end": index + 1,
                    "seconds": 1,
                    "bytes": bytes_sent,
                    "bits_per_second": bps,
                    "retransmits": interval_retransmits,
                    "snd_cwnd": int(stream_mbps * 2400),
                    "rtt": int((rtt_ms + math.sin((index + stream_index) / 5)) * 1000),
                    "rttvar": int(max(1, rtt_ms * 0.08) * 1000),
                    "pmtu": 1500,
                    "omitted": False,
                }
            )
        intervals.append({"streams": streams, "sum": sum_streams(streams)})

    duration = len(profile)
    end_streams = []
    for stream_index, totals in stream_totals.items():
        avg_bps = (totals["bytes"] * 8 / duration) if duration else 0
        summary = {
            "socket": stream_index,
            "start": 0,
            "end": duration,
            "seconds": duration,
            "bytes": totals["bytes"],
            "bits_per_second": avg_bps,
            "retransmits": totals["retransmits"],
            "min_rtt": int((rtt_ms - 1) * 1000),
            "mean_rtt": int(rtt_ms * 1000),
            "max_rtt": int((rtt_ms + 1) * 1000),
            "max_snd_cwnd": int((max(profile) / parallel_streams) * 2400),
        }
        end_streams.append({"sender": summary, "receiver": summary})

    sum_summary = sum_streams([stream["sender"] for stream in end_streams])
    sum_summary.update(
        {
            "socket": 0,
            "start": 0,
            "end": duration,
            "seconds": duration,
            "min_rtt": int((rtt_ms - 1) * 1000),
            "mean_rtt": int(rtt_ms * 1000),
            "max_rtt": int((rtt_ms + 1) * 1000),
            "max_snd_cwnd": int(max(profile) * 2400),
        }
    )
    connected = [
        {
            "socket": stream_index,
            "local_host": "10.0.0.1",
            "local_port": 5200 + stream_index,
            "remote_host": "10.0.0.2",
            "remote_port": 5201,
        }
        for stream_index in range(1, parallel_streams + 1)
    ]

    data = {
        "start": {
            "timestamp": {"time": "Tue, 14 Nov 2023 22:13:20 GMT", "timesecs": 1700000000},
            "test_start": {"protocol": "TCP", "num_streams": parallel_streams, "duration": duration, "reverse": 0},
            "connected": connected,
        },
        "intervals": intervals,
        "end": {
            "streams": end_streams,
            "sum_sent": sum_summary,
            "sum_received": sum_summary,
            "sum": sum_summary,
        },
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def sum_streams(streams: list[dict[str, object]]) -> dict[str, object]:
    seconds = float(streams[0].get("seconds", 1) or 1) if streams else 1
    bytes_sent = sum(int(stream.get("bytes", 0) or 0) for stream in streams)
    return {
        "socket": 0,
        "start": 0,
        "end": seconds,
        "seconds": seconds,
        "bytes": bytes_sent,
        "bits_per_second": (bytes_sent * 8) / seconds if seconds else 0,
        "retransmits": sum(int(stream.get("retransmits", 0) or 0) for stream in streams),
        "snd_cwnd": sum(int(stream.get("snd_cwnd", 0) or 0) for stream in streams),
    }


def showcase_plots() -> list[dict[str, object]]:
    return [
        {
            "name": "throughput_vs_rtt",
            "type": "line",
            "data": {"source": "flow_summary", "filter": {"scenario": "rtt_sweep"}, "x": "rtt_ms", "y": "avg_throughput_mbps", "group_by": "cc_algo", "aggregate": "mean"},
            "display": {"title": "Throughput as a function of RTT", "x_label": "Configured RTT (ms)", "y_label": "Average throughput (Mbps)", "colors": {"cubic": "#2D72B7", "bbrv3": "#95253B"}, "size": [7.2, 5.0], "marker": "o"},
        },
        {
            "name": "retransmits_vs_rtt",
            "type": "line",
            "data": {"source": "flow_summary", "filter": {"scenario": "rtt_sweep"}, "x": "rtt_ms", "y": "retransmits", "group_by": "cc_algo", "aggregate": "mean"},
            "display": {"title": "Retransmissions as a function of RTT", "x_label": "Configured RTT (ms)", "y_label": "Retransmissions (packets)", "colors": {"cubic": "#2D72B7", "bbrv3": "#95253B"}, "size": [7.2, 5.0], "marker": "o"},
        },
        {
            "name": "throughput_vs_loss",
            "type": "line",
            "data": {"source": "flow_summary", "filter": {"scenario": "loss_sweep"}, "x": "loss_percent", "y": "avg_throughput_mbps", "group_by": "cc_algo", "aggregate": "mean"},
            "display": {"title": "Throughput as a function of random loss", "x_label": "Random packet loss (%)", "y_label": "Average throughput (Mbps)", "colors": {"cubic": "#2D72B7", "bbrv3": "#95253B"}, "size": [7.2, 5.0], "marker": "o", "log_x": True},
        },
        {
            "name": "retransmits_vs_loss",
            "type": "line",
            "data": {"source": "flow_summary", "filter": {"scenario": "loss_sweep"}, "x": "loss_percent", "y": "retransmits", "group_by": "cc_algo", "aggregate": "mean"},
            "display": {"title": "Retransmissions as a function of random loss", "x_label": "Random packet loss (%)", "y_label": "Retransmissions (packets)", "colors": {"cubic": "#2D72B7", "bbrv3": "#95253B"}, "size": [7.2, 5.0], "marker": "o", "log_x": True, "log_y": True},
        },
        {
            "name": "avg_flow_throughput_heatmap",
            "type": "heatmap",
            "data": {"source": "flow_summary", "filter": {"scenario": "buffer_rtt_sweep"}, "x": "rtt_ms", "y": "buffer_bdp", "value": "avg_throughput_mbps", "aggregate": "mean", "facet_by": "aqm"},
            "display": {"title": "Average flow throughput over RTT and buffer size", "x_label": "Configured RTT (ms)", "y_label": "Buffer size (BDP)", "value_label": "Throughput (Mbps)", "cmap": "YlGnBu", "annotation_color": "black", "size": [7.5, 5.8]},
        },
        {
            "name": "rtt_unfairness_throughput_vs_buffer",
            "type": "line",
            "data": {"source": "flow_summary", "filter": {"scenario": "rtt_unfairness"}, "x": "buffer_bdp", "y": "avg_throughput_mbps", "group_by": "rtt_ms", "facet_by": "aqm", "aggregate": "mean"},
            "display": {"title": "Throughput by RTT class and buffer size", "x_label": "Buffer size (BDP)", "y_label": "Average throughput (Mbps)", "palette": "tab10", "size": [7.2, 5.0], "marker": "o", "log_x": True},
        },
        {
            "name": "rtt_unfairness_fairness_vs_buffer",
            "type": "line",
            "data": {"source": "experiment_summary", "filter": {"scenario": "rtt_unfairness"}, "x": "buffer_bdp", "y": "jain_fairness", "group_by": "aqm", "aggregate": "mean"},
            "display": {"title": "RTT fairness as a function of buffer size", "x_label": "Buffer size (BDP)", "y_label": "Jain fairness", "palette": "Set2", "size": [7.2, 5.0], "marker": "o", "log_x": True, "ylim": [0, 1.05]},
        },
        {
            "name": "staggered_flow_throughput",
            "type": "time_series",
            "data": {"source": "flow_time_bins", "filter": {"scenario": "staggered_coexistence"}, "x": "time_bin_start_s", "y": "throughput_mbps", "group_by": "flow_label", "aggregate": "mean"},
            "display": {"title": "Throughput with staggered flow starts", "x_label": "Experiment time (s)", "y_label": "Throughput (Mbps)", "palette": "tab10", "size": [9.0, 5.0]},
        },
        {
            "name": "staggered_flow_fairness",
            "type": "line",
            "data": {"source": "flow_fairness", "filter": {"scenario": "staggered_coexistence"}, "x": "time_bin_start_s", "y": "jain_fairness", "aggregate": "mean"},
            "display": {"title": "Fairness with staggered flow starts", "x_label": "Experiment time (s)", "y_label": "Jain fairness", "color": "#E5B245", "size": [9.0, 4.2], "ylim": [0, 1.05]},
        },
        {
            "name": "fct_cdf_by_cc",
            "type": "cdf",
            "data": {"source": "flow_summary", "filter": {"scenario": "fct"}, "value": "duration_s", "group_by": "cc_algo"},
            "display": {"title": "Flow completion time CDF", "x_label": "Flow completion time (s)", "colors": {"cubic": "#2D72B7", "bbrv3": "#95253B"}, "size": [7.2, 5.0]},
        },
        {
            "name": "fairness_heatmap_bandwidth_delay",
            "type": "heatmap",
            "data": {"source": "experiment_summary", "filter": {"scenario": "bdp_sweep"}, "x": "propagation_delay_ms", "y": "bottleneck_mbps", "value": "jain_fairness", "annotations": ["link_utilization_percent", "share_cubic_percent", "share_bbrv3_percent"]},
            "display": {"title": "Fairness over bandwidth-delay conditions", "x_label": "Configured RTT or propagation delay (ms)", "y_label": "Bottleneck bandwidth (Mbps)", "value_label": "Jain fairness", "cmap": "YlGnBu", "annotation_color": "black", "annotation_fontsize": 7, "size": [8.5, 6.4]},
        },
    ]


def slug(value: float) -> str:
    return str(value).replace(".", "p")


if __name__ == "__main__":
    main()
