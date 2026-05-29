#!/usr/bin/env python3
"""Generate a small synthetic iperf3 JSON corpus for the docs.

The data is intentionally synthetic. It is shaped like common BBRv3 paper
experiments so the manifest/spec examples can be rendered by iperf3_plotter
without requiring a network lab or vendoring another repository's datasets.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Iterable


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
    rows.extend(rtt_unfairness(runs_dir))
    rows.extend(staggered_starts(runs_dir))
    rows.extend(fct_runs(runs_dir))
    rows.extend(bdp_heatmap(runs_dir))

    manifest = out_dir / "manifest.csv"
    fieldnames = [
        "file",
        "flow_id",
        "flow_label",
        "scenario",
        "cc_algo",
        "cc_mix",
        "aqm",
        "trial",
        "start_offset_s",
        "rtt_ms",
        "buffer_bdp",
        "loss_percent",
        "bottleneck_mbps",
        "propagation_delay_ms",
        "num_flows",
        "num_cubic_flows",
        "num_bbrv3_flows",
        "transfer_size_mb",
    ]
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} JSON files to {runs_dir}")
    print(f"Wrote manifest to {manifest}")


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
    duration_s: float = 30,
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
) -> dict[str, object]:
    path = runs_dir / filename
    profile = throughput_profile or [float(throughput_mbps or 100)] * max(1, math.ceil(duration_s))
    write_iperf_json(path, profile, rtt_ms=rtt_ms, retransmits_total=retransmits_total)
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


def write_iperf_json(path: Path, throughput_profile_mbps: Iterable[float], *, rtt_ms: float, retransmits_total: int) -> None:
    profile = list(throughput_profile_mbps)
    intervals = []
    total_bytes = 0
    total_retransmits = 0
    for index, throughput_mbps in enumerate(profile):
        wave = 1 + (0.04 * math.sin(index / 3))
        bps = throughput_mbps * wave * 1_000_000
        bytes_sent = int(bps / 8)
        interval_retransmits = int(round(retransmits_total / max(1, len(profile))))
        total_bytes += bytes_sent
        total_retransmits += interval_retransmits
        stream = {
            "socket": 1,
            "start": index,
            "end": index + 1,
            "seconds": 1,
            "bytes": bytes_sent,
            "bits_per_second": bps,
            "retransmits": interval_retransmits,
            "snd_cwnd": int(throughput_mbps * 2400),
            "rtt": int((rtt_ms + math.sin(index / 5)) * 1000),
            "rttvar": int(max(1, rtt_ms * 0.08) * 1000),
            "pmtu": 1500,
            "omitted": False,
        }
        intervals.append({"streams": [stream], "sum": dict(stream)})

    duration = len(profile)
    avg_bps = (total_bytes * 8 / duration) if duration else 0
    summary = {
        "socket": 1,
        "start": 0,
        "end": duration,
        "seconds": duration,
        "bytes": total_bytes,
        "bits_per_second": avg_bps,
        "retransmits": total_retransmits,
        "min_rtt": int((rtt_ms - 1) * 1000),
        "mean_rtt": int(rtt_ms * 1000),
        "max_rtt": int((rtt_ms + 1) * 1000),
        "max_snd_cwnd": int(max(profile) * 2400),
    }
    data = {
        "start": {
            "timestamp": {"time": "Tue, 14 Nov 2023 22:13:20 GMT", "timesecs": 1700000000},
            "test_start": {"protocol": "TCP", "num_streams": 1, "duration": duration, "reverse": 0},
            "connected": [
                {
                    "socket": 1,
                    "local_host": "10.0.0.1",
                    "local_port": 5201,
                    "remote_host": "10.0.0.2",
                    "remote_port": 5201,
                }
            ],
        },
        "intervals": intervals,
        "end": {
            "streams": [{"sender": summary, "receiver": summary}],
            "sum_sent": summary,
            "sum_received": summary,
            "sum": summary,
        },
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def slug(value: float) -> str:
    return str(value).replace(".", "p")


if __name__ == "__main__":
    main()
