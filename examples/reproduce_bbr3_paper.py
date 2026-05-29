#!/usr/bin/env python3
"""Reproduce selected BBRv3 paper figures from the public experiment repo.

The script downloads only the JSON and DAT files needed for the plots below
from https://github.com/gomezgaona/bbr3 and caches them locally. It does not
vendor the upstream experiment data into this repository.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "iperf3_plotter_mpl"))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


BASE_RAW_URL = "https://raw.githubusercontent.com/gomezgaona/bbr3/main/experiments"

GOLD = "#E5B245"
BLUE = "#2D72B7"
GREEN = "#82AA45"
GARNET = "#95253B"
ORANGE = "#FFA500"
VIOLET = "#7F00FF"
LIGHT_BLUE = "#ADD8E6"

DEFAULT_FIGURES = [
    "dmz",
    "retrans-loss",
    "rtt-unfairness",
    "fairness-time",
    "queue-occupancy",
]


def main() -> None:
    args = parse_args()
    cache_dir = Path(args.cache)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    selected = args.figure or DEFAULT_FIGURES
    generated: list[Path] = []
    for figure in selected:
        if figure == "dmz":
            generated.extend(plot_dmz(cache_dir, out_dir, args.format))
        elif figure == "retrans-loss":
            generated.extend(plot_retrans_loss(cache_dir, out_dir, args.format))
        elif figure == "rtt-unfairness":
            generated.extend(plot_rtt_unfairness(cache_dir, out_dir, args.format))
        elif figure == "fairness-time":
            generated.extend(plot_fairness_time(cache_dir, out_dir, args.format))
        elif figure == "queue-occupancy":
            generated.extend(plot_queue_occupancy(cache_dir, out_dir, args.format))
        else:
            raise SystemExit(f"Unknown figure selection: {figure}")

    print(f"Wrote {len(generated)} file(s) to {out_dir}")
    for path in generated:
        print(f"  {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Regenerate selected BBRv3 paper-style figures from the upstream experiment data.",
    )
    parser.add_argument(
        "--out",
        default="docs/images/bbr3",
        help="Directory where generated figures are written.",
    )
    parser.add_argument(
        "--cache",
        default=".cache/bbr3-paper",
        help="Directory used to cache downloaded upstream data files.",
    )
    parser.add_argument(
        "--format",
        action="append",
        default=None,
        choices=["png", "pdf", "svg"],
        help="Output format. Repeat to generate multiple formats.",
    )
    parser.add_argument(
        "--figure",
        action="append",
        choices=DEFAULT_FIGURES,
        help="Figure family to generate. Repeat for multiple families. Defaults to all supported families.",
    )
    args = parser.parse_args()
    args.format = args.format or ["png"]
    return args


def plot_dmz(cache_dir: Path, out_dir: Path, formats: list[str]) -> list[Path]:
    """Reproduce the throughput and retransmission vs RTT plots."""

    configure_style()
    delays = [0.002, 0.02, 0.04, 0.06, 0.08, 0.1]
    delay_labels = [2, 20, 40, 60, 80, 100]
    loss = 0.025
    runs = range(1, 11)

    throughput: dict[str, list[float]] = {"CUBIC": [], "BBRv3": []}
    retransmits: dict[str, list[float]] = {"CUBIC": [], "BBRv3": []}
    for delay in delays:
        for label, filename_algo in [("CUBIC", "cubic"), ("BBRv3", "bbr")]:
            files = [
                f"DMZ/json_files/h1_{filename_algo}_{delay}_{loss}out_{run}.json"
                for run in runs
            ]
            throughput[label].append(mean_from_json(files, cache_dir, summary_gbps))
            retransmits[label].append(mean_from_json(files, cache_dir, summary_retransmits))

    paths: list[Path] = []
    fig, ax = plt.subplots(figsize=(9, 7.5))
    paper_grid(ax)
    ax.plot(delay_labels, throughput["CUBIC"], color=BLUE, linewidth=2, marker="o", label="CUBIC")
    ax.plot(delay_labels, throughput["BBRv3"], color=GARNET, linewidth=2, marker="o", label="BBRv3")
    ax.set_ylabel("Throughput [Gbps]")
    ax.set_xlabel("RTT [ms]")
    ax.set_ylim(0, 1.15)
    ax.legend(loc="upper right", ncol=2, fontsize=14)
    paths.extend(save_figure(fig, out_dir, "bbr3_paper_throughput_rtt", formats))

    fig, ax = plt.subplots(figsize=(9, 7.5))
    paper_grid(ax)
    ax.plot(delay_labels, retransmits["CUBIC"], color=BLUE, linewidth=2, marker="o", label="CUBIC")
    ax.plot(delay_labels, retransmits["BBRv3"], color=GARNET, linewidth=2, marker="o", label="BBRv3")
    ax.set_ylabel("Retransmissions [Packets]")
    ax.set_xlabel("RTT [ms]")
    ax.legend(loc="upper right", ncol=2, fontsize=14)
    paths.extend(save_figure(fig, out_dir, "bbr3_paper_retrans_rtt", formats))
    return paths


def plot_retrans_loss(cache_dir: Path, out_dir: Path, formats: list[str]) -> list[Path]:
    """Reproduce the BBRv3 throughput and retransmission vs loss plots."""

    configure_style()
    losses = [0.001, 0.01, 0.1, 0.5, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20]
    delay = 0.02
    files = [f"retrans_loss/json_files/h1_bbr_{delay}_{loss}out.json" for loss in losses]
    throughput = [summary_gbps(load_json(path, cache_dir)) for path in files]
    retransmits = [summary_retransmits(load_json(path, cache_dir)) for path in files]

    paths: list[Path] = []
    fig, ax = plt.subplots(figsize=(10.5, 6.75))
    paper_grid(ax)
    ax.semilogx(losses, throughput, color=GOLD, linewidth=2, marker="o")
    ax.set_ylabel("Throughput [Gbps]")
    ax.set_xlabel("Loss rate [%]")
    ax.set_ylim(-0.05, 1.1)
    paths.extend(save_figure(fig, out_dir, "bbr3_paper_throughput_loss", formats))

    fig, ax = plt.subplots(figsize=(10.5, 6.75))
    paper_grid(ax)
    ax.loglog(losses, retransmits, color=GOLD, linewidth=2, marker="o")
    ax.set_ylabel("Retransmissions [Packets]")
    ax.set_xlabel("Loss rate [%]")
    ax.set_ylim(50, 1.5e5)
    paths.extend(save_figure(fig, out_dir, "bbr3_paper_retrans_loss", formats))
    return paths


def plot_rtt_unfairness(cache_dir: Path, out_dir: Path, formats: list[str]) -> list[Path]:
    """Reproduce RTT unfairness plots with and without FQ-CoDel."""

    configure_style()
    bdps = [
        0.2,
        0.3,
        0.4,
        0.5,
        0.6,
        0.7,
        0.8,
        0.9,
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        20,
        30,
        40,
        50,
        60,
        70,
        80,
        90,
        100,
    ]
    scenarios = [
        ("RTT_Unfairness/RTT_Unfairness_1G_20_100", "bbr3_paper_rtt_unfairness", "Drop-tail"),
        ("RTT_Unfairness/RTT_Unfairness_1G_20_100_FQ_Codel", "bbr3_paper_rtt_unfairness_fq_codel", "FQ-CoDel"),
    ]

    paths: list[Path] = []
    for upstream_dir, stem, title in scenarios:
        flow_20_ms = []
        flow_100_ms = []
        for bdp in bdps:
            flow_20_ms.append(summary_gbps(load_json(f"{upstream_dir}/h1_bbr_{bdp}BDP_out.json", cache_dir)))
            flow_100_ms.append(summary_gbps(load_json(f"{upstream_dir}/h2_bbr_{bdp}BDP_out.json", cache_dir)))
        fairness = [jain_percent([a, b]) for a, b in zip(flow_20_ms, flow_100_ms)]

        fig, axes = plt.subplots(2, 1, sharex=True, figsize=(10, 8))
        fig.subplots_adjust(hspace=0.1)
        for ax in axes:
            paper_grid(ax)
        axes[0].semilogx(bdps, fairness, color=GOLD, linewidth=2, marker="o", label="Fairness")
        axes[1].semilogx(bdps, flow_20_ms, color=BLUE, linewidth=2, marker="o", label="20 ms")
        axes[1].semilogx(bdps, flow_100_ms, color=GARNET, linewidth=2, marker="o", label="100 ms")
        axes[0].set_ylabel("Fairness [%]")
        axes[1].set_ylabel("Throughput [Gbps]")
        axes[1].set_xlabel("Buffer size [BDP]")
        axes[0].set_ylim(50, 105)
        axes[1].set_ylim(0, 1.2)
        axes[0].legend(loc="lower right", fontsize=14)
        axes[1].legend(loc="upper right", ncol=2, fontsize=14)
        fig.suptitle(title, fontsize=18)
        paths.extend(save_figure(fig, out_dir, stem, formats))
    return paths


def plot_fairness_time(cache_dir: Path, out_dir: Path, formats: list[str]) -> list[Path]:
    """Reproduce the time-varying coexistence fairness plot."""

    configure_style()
    duration = 480
    starts = [0, 60, 120, 180, 240, 300]
    flows = [
        ("h1_cubic_out", "CUBIC flow", BLUE),
        ("h2_bbr_out", "BBRv3 flow 1", LIGHT_BLUE),
        ("h3_bbr_out", "BBRv3 flow 2", GARNET),
        ("h4_bbr_out", "BBRv3 flow 3", ORANGE),
        ("h5_bbr_out", "BBRv3 flow 4", GREEN),
        ("h6_bbr_out", "BBRv3 flow 5", VIOLET),
    ]
    runs = range(1, 11)
    throughput = np.zeros((len(flows), duration))

    for flow_index, (prefix, _label, _color) in enumerate(flows):
        start = starts[flow_index]
        for run in runs:
            data = load_json(f"fairness_time/json_files/{prefix}_{run}.json", cache_dir)
            values = interval_gbps(data)
            usable = min(duration - start, len(values))
            if usable > 0:
                throughput[flow_index, start : start + usable] += np.array(values[:usable]) / len(runs)

    fairness = []
    for time_index in range(duration):
        active_values = [throughput[i, time_index] for i, start in enumerate(starts) if time_index >= start]
        fairness.append(jain_percent(active_values))

    fig, axes = plt.subplots(2, 1, sharex=True, figsize=(10, 11))
    fig.subplots_adjust(hspace=0.1)
    for ax in axes:
        paper_grid(ax)
    time_axis = range(duration)
    axes[0].plot(time_axis, fairness, color=GOLD, linewidth=2, label="Fairness")
    for flow_index, (_prefix, label, color) in enumerate(flows):
        axes[1].plot(time_axis, throughput[flow_index], color=color, linewidth=2, label=label)
    axes[0].set_ylabel("Fairness [%]")
    axes[1].set_ylabel("Throughput [Gbps]")
    axes[1].set_xlabel("Time [seconds]")
    axes[0].set_ylim(50, 105)
    axes[1].set_ylim(0, 1.25)
    axes[1].set_xlim(-1, duration + 1)
    axes[1].legend(loc="upper right", ncol=2, fontsize=13)
    return save_figure(fig, out_dir, "bbr3_paper_fairness_time", formats)


def plot_queue_occupancy(cache_dir: Path, out_dir: Path, formats: list[str]) -> list[Path]:
    """Reproduce the queue occupancy plot from upstream DAT files."""

    configure_style()
    duration = 480
    cubic = load_dat_mbps("q_occupancy/cubic.dat", cache_dir)
    bbr3 = load_dat_mbps("q_occupancy/bbr.dat", cache_dir)
    cubic = pad_or_trim(cubic, duration)
    bbr3 = pad_or_trim(bbr3, duration)

    step = 60
    bdp_steps = [0.1, 0.2, 0.5, 0.5, 0.2, 0.1]
    queue = np.concatenate([np.full(step, value) for value in bdp_steps])
    queue = pad_or_trim(queue, duration)

    fig, ax = plt.subplots(figsize=(10.5, 6.75))
    paper_grid(ax)
    time_axis = range(duration)
    ax.plot(time_axis, queue, color=GOLD, linewidth=2, label="Buffer Size")
    ax.plot(time_axis, cubic, color=BLUE, linewidth=2, label="CUBIC")
    ax.plot(time_axis, bbr3, color=GARNET, linewidth=2, label="BBRv3")
    ax.set_ylabel("Buffer Size [BDP]")
    ax.set_xlabel("Time [seconds]")
    ax.legend(loc="upper right", fontsize=14)
    return save_figure(fig, out_dir, "bbr3_paper_queue_occupancy", formats)


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.size": 16,
            "axes.labelsize": 18,
            "xtick.labelsize": 15,
            "ytick.labelsize": 15,
            "legend.fontsize": 14,
            "figure.titlesize": 18,
        }
    )


def paper_grid(ax: plt.Axes) -> None:
    ax.grid(True, which="both", linewidth=0.3, linestyle=(0, (1, 10)), color="black")


def save_figure(fig: plt.Figure, out_dir: Path, stem: str, formats: list[str]) -> list[Path]:
    paths = []
    for fmt in formats:
        path = out_dir / f"{stem}.{fmt}"
        kwargs = {"bbox_inches": "tight"}
        if fmt == "png":
            kwargs["dpi"] = 160
        fig.savefig(path, **kwargs)
        paths.append(path)
    plt.close(fig)
    return paths


def load_json(relative_path: str, cache_dir: Path) -> dict:
    return json.loads(fetch_bytes(relative_path, cache_dir).decode("utf-8"))


def load_dat_mbps(relative_path: str, cache_dir: Path) -> np.ndarray:
    text = fetch_bytes(relative_path, cache_dir).decode("utf-8")
    values = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            values.append(float(line) / 1e6)
        except ValueError:
            continue
    return np.array(values, dtype=float)


def fetch_bytes(relative_path: str, cache_dir: Path) -> bytes:
    cache_path = cache_dir / relative_path
    if cache_path.exists():
        return cache_path.read_bytes()

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"{BASE_RAW_URL}/{urllib.parse.quote(relative_path, safe='/._-')}"
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
    except urllib.error.URLError as exc:
        print(f"Failed to download {url}: {exc}", file=sys.stderr)
        raise
    cache_path.write_bytes(data)
    return data


def mean_from_json(paths: list[str], cache_dir: Path, metric: Callable[[dict], float]) -> float:
    values = [metric(load_json(path, cache_dir)) for path in paths]
    return float(np.mean(values))


def summary_gbps(data: dict) -> float:
    return float(data["end"]["sum_sent"]["bits_per_second"]) / 1e9


def summary_retransmits(data: dict) -> float:
    return float(data["end"]["sum_sent"].get("retransmits", 0))


def interval_gbps(data: dict) -> list[float]:
    values = []
    for interval in data.get("intervals", []):
        interval_sum = interval.get("sum")
        if interval_sum and "bits_per_second" in interval_sum:
            values.append(float(interval_sum["bits_per_second"]) / 1e9)
    return values


def jain_percent(values: list[float]) -> float:
    numeric = [float(value) for value in values if not math.isnan(float(value))]
    if not numeric:
        return float("nan")
    total = sum(numeric)
    sum_squares = sum(value * value for value in numeric)
    if sum_squares == 0:
        return 100.0
    return 100.0 * total * total / (len(numeric) * sum_squares)


def pad_or_trim(values: np.ndarray, length: int) -> np.ndarray:
    if len(values) >= length:
        return values[:length]
    return np.pad(values, (0, length - len(values)), constant_values=np.nan)


if __name__ == "__main__":
    main()
