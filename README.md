# iperf3_plotter

[![CI](https://github.com/ekfoury/iperf3_plotter/actions/workflows/ci.yml/badge.svg)](https://github.com/ekfoury/iperf3_plotter/actions/workflows/ci.yml)

`iperf3_plotter` analyzes iperf3 JSON output and produces normalized CSV files,
plots, and an HTML report.

It supports:

- One iperf3 JSON file
- Multiple JSON files from different clients
- Parallel streams created with `iperf3 -P`
- Unified experiment time for staggered or overlapping transfers
- Transfer-level plots that aggregate parallel streams
- Stream-level plots for detailed TCP behavior
- Jain fairness, bandwidth share, RTT, cwnd, retransmits, PMTU, and throughput-delay plots

The current implementation is Python-based. The original shell/gnuplot version
is preserved in `legacy/` for reference only.

## Platform Support

The plotter itself is OS-independent Python and should run on Linux, macOS, and
Windows-like Python environments. It only reads iperf3 JSON files, so `iperf3`
is required to collect data but not to analyze existing JSON.

Linux compatibility is checked with GitHub Actions on Ubuntu for Python 3.10,
3.11, and 3.12. The optional Mininet/`tc` lab needs Linux kernel features; on
macOS it runs through Docker Desktop's Linux VM.

## Requirements

- Python 3.10 or newer
- `pandas`
- `matplotlib`
- `typer`
- `iperf3` only if you need to generate new JSON files

## Install

Use a virtual environment. This works on Linux and macOS and avoids
`externally-managed-environment` errors from distro-managed Python installs:

Install directly from GitHub:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install "git+https://github.com/ekfoury/iperf3_plotter.git"
iperfplot --help
```

Or install from a local clone:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
iperfplot --help
```

You can also use the Makefile:

```bash
make install
source .venv/bin/activate
```

If dependencies are already available in your current Python environment and
you do not want pip to resolve them, you can skip dependency installation:

```bash
python -m pip install --no-deps .
```

The Makefile version creates a venv with access to system/site packages first:

```bash
make install-offline
source .venv/bin/activate
```

For development without installing:

```bash
PYTHONPATH=src python3 -m iperf3_plotter --help
```

## Generate iperf3 JSON

Run an iperf3 server:

```bash
iperf3 -s
```

Run a client and save JSON:

```bash
iperf3 -c SERVER_IP -J -i 1 -t 30 > run1.json
```

For parallel streams:

```bash
iperf3 -c SERVER_IP -J -i 1 -t 30 -P 4 > run1.json
```

## Quick Start

Generate CSV files, plots, and an HTML report:

```bash
iperfplot all run1.json --out results
```

Open:

```text
results/report.html
```

The included sample file can be used immediately:

```bash
iperfplot all sample/my_test.json --out results
```

## Multiple Clients

If you have one JSON file per iperf3 client, pass them together:

```bash
iperfplot all client1.json client2.json client3.json --out comparison
```

By default, each file is plotted from its own time zero. To place all files on
one experiment timeline using iperf3 timestamps:

```bash
iperfplot all client1.json client2.json client3.json --time-mode global --out comparison
```

`--time-mode global` sets the earliest observed transfer to X=0. If `client2`
started 5 seconds after `client1`, `client2` appears at X=5.

## Manual Start Offsets

If JSON timestamps are missing or unreliable, use a manifest.

Create `experiment.json`:

```json
{
  "runs": [
    {
      "file": "client1.json",
      "flow_id": "client1",
      "label": "CUBIC client 1",
      "cc_algo": "cubic",
      "start_offset_s": 0
    },
    {
      "file": "client2.json",
      "flow_id": "client2",
      "label": "RENO client 2",
      "cc_algo": "reno",
      "start_offset_s": 5
    }
  ]
}
```

Run:

```bash
iperfplot all client1.json client2.json \
  --manifest experiment.json \
  --time-mode offset \
  --out comparison
```

This puts `client1` at X=0 and `client2` at X=5.

Useful manifest fields:

- `flow_id`: transfer identifier
- `label`: display label
- `cc_algo`: congestion-control algorithm
- `start_offset_s`: manual start time
- `rtt_ms`: configured RTT
- `bottleneck_mbps`: bottleneck rate
- `buffer_bdp`: buffer size in BDP units
- `scenario`: experiment name

## Commands

Run the complete pipeline:

```bash
iperfplot all *.json --out results
```

Only normalize data:

```bash
iperfplot parse *.json --out data
```

Only generate plots:

```bash
iperfplot plot *.json --out plots --format png --format pdf
```

Only generate an HTML report:

```bash
iperfplot report *.json --out report.html
```

Compute Jain fairness:

```bash
iperfplot fairness *.json --level flow
iperfplot fairness run1.json --level stream
```

Diagnose overlapping stream lines:

```bash
iperfplot diagnose run1.json
```

## Output Files

`iperfplot all` creates:

```text
results/
  data/
  plots/
  report.html
```

Important CSV files:

- `intervals.csv`: one row per stream per iperf interval
- `flow_intervals.csv`: one row per transfer per interval, with parallel streams aggregated
- `stream_time_bins.csv`: streams resampled onto common time bins
- `flow_time_bins.csv`: transfers resampled onto common time bins
- `stream_summary.csv`: throughput, RTT, and retransmit summary per stream
- `flow_summary.csv`: throughput, RTT, and retransmit summary per transfer
- `flow_fairness.csv`: Jain fairness over time among active transfers
- `stream_fairness.csv`: Jain fairness over time among active streams
- `stream_similarity.csv`: pairwise checks for nearly identical stream time series

## Plot Types

Transfer-level plots aggregate parallel streams belonging to the same JSON file
or manifest `flow_id`:

- Aggregate throughput
- RTT and RTT variation
- Congestion window
- Retransmits and cumulative retransmits
- Cumulative transferred data
- PMTU
- Bandwidth share
- Jain fairness

Stream-level plots show each iperf3 stream separately:

- Per-stream throughput
- Throughput deviation from the interval mean
- RTT and RTT variation
- Congestion window
- Retransmits and cumulative retransmits
- Cumulative transferred data
- PMTU
- Parallel-stream fairness

Experiment-level plots include:

- Total aggregate throughput
- Throughput-delay scatter plot
- Average throughput by stream

## Time Modes

- `relative`: each JSON file starts at X=0
- `global`: align files by iperf3 timestamps and normalize the earliest start to X=0
- `offset`: use `start_offset_s` values from a manifest
- `wall`: use raw Unix time from iperf3 timestamps

If you pass multiple JSON files and do not set `--time-mode`, `iperfplot`
warns before using the default `relative` mode. For staggered clients, use
`--time-mode global` when client clocks are synchronized, or use a manifest
with `--time-mode offset` when you know the intended start offsets.

Examples:

```bash
iperfplot all *.json --time-mode relative --out results
iperfplot all *.json --time-mode global --out results
iperfplot all *.json --manifest experiment.json --time-mode offset --out results
```

## Compatibility Wrappers

These wrappers are kept for users of the old script names:

```bash
./plot_iperf.sh run1.json --out results
./preprocessor.sh run1.json data
./fairness.sh run1.json --level flow
```

The maintained interface is `iperfplot`.

## Optional Test Lab

The `lab/` directory contains a Docker-based Mininet/iperf3 testbed. It runs
Mininet and `tc` inside Linux, generates iperf3 JSON files, writes a manifest,
and runs the plotter.

On Linux, start Docker. On macOS, start Docker Desktop. Then run:

```bash
make lab
```

To test overlapping transfers with parallel streams:

```bash
make lab-overlap
```

The lab writes:

```text
lab-results/raw/*.json
lab-results/experiment.json
lab-results/analysis/report.html
```

Docker Desktop may not expose every TCP congestion-control algorithm. If a
requested algorithm is unavailable, the lab falls back to `cubic` or `reno` and
records both the requested and actual algorithms in the manifest.

## Development

Run tests:

```bash
make test
```

Remove generated outputs:

```bash
make clean
```
