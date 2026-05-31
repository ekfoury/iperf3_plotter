# iperf3_plotter

[![CI](https://github.com/ekfoury/iperf3_plotter/actions/workflows/ci.yml/badge.svg)](https://github.com/ekfoury/iperf3_plotter/actions/workflows/ci.yml)

`iperf3_plotter` analyzes iperf3 JSON output and produces normalized CSV files,
publication-style plots, and an HTML report.

It handles one file, many clients, parallel streams from `iperf3 -P`, staggered
flow starts, flow-level aggregation, stream-level diagnostics, Jain fairness,
bandwidth share, RTT, cwnd, retransmits, PMTU, and customizable research plots.

The maintained implementation is Python-based. The original shell/gnuplot
scripts are kept in `legacy/` for reference.

## Platform Support

The plotter is OS-independent Python and is tested on Ubuntu with Python 3.10,
3.11, and 3.12. It should also run on macOS and Windows-like Python
environments. `iperf3` is only needed to collect new data; existing JSON files
can be analyzed without it.

The optional Mininet/`tc` lab requires Linux kernel networking features. On
macOS, run it through Docker Desktop.

## Install

Use a virtual environment. This avoids distro or Homebrew
`externally-managed-environment` errors:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install "git+https://github.com/ekfoury/iperf3_plotter.git"
iperfplot --help
```

From a local clone:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
iperfplot --help
```

For development without installing:

```bash
PYTHONPATH=src python3 -m iperf3_plotter --help
```

## Generate iperf3 JSON

Start a server:

```bash
iperf3 -s
```

Run a client and save JSON:

```bash
iperf3 -c SERVER_IP -J -i 1 -t 30 > run1.json
```

Run parallel streams:

```bash
iperf3 -c SERVER_IP -J -i 1 -t 30 -P 4 > run1.json
```

## Quick Start

Run the complete pipeline:

```bash
iperfplot all run1.json --out results
```

Try the included sample:

```bash
iperfplot all sample/my_test.json --out results
```

Open:

```text
results/report.html
```

## Multiple Clients

Pass one JSON file per client:

```bash
iperfplot all client1.json client2.json client3.json --out comparison
```

By default, each file starts at X=0. If the iperf3 client clocks are
synchronized, align all files on one experiment timeline:

```bash
iperfplot all client1.json client2.json client3.json --time-mode global --out comparison
```

If the clocks are not reliable, use an experiment file with `start_offset_s`
and `time_mode: offset`.

## Experiment Files

For serious experiments, put everything in one YAML file: inputs, metadata,
time alignment, and plots.

```bash
iperfplot experiment experiment.yaml --out results
```

Minimal example:

```yaml
name: staggered_clients
time_mode: offset

inputs:
  runs:
    - file: client1.json
      flow_id: client1
      flow_label: CUBIC client
      cc_algo: cubic
      start_offset_s: 0
    - file: client2.json
      flow_id: client2
      flow_label: BBRv3 client
      cc_algo: bbrv3
      start_offset_s: 5

plots:
  - name: throughput_by_flow
    type: time_series
    data:
      source: flow_time_bins
      x: time_bin_start_s
      y: throughput_mbps
      group_by: flow_label
    display:
      x_label: Experiment time (s)
      y_label: Throughput (Mbps)
      palette: tab10
```

Validate before running:

```bash
iperfplot validate experiment.yaml
```

Run the checked-in example:

```bash
PYTHONPATH=src python3 -m iperf3_plotter experiment examples/experiment.yaml --out results/example
```

No naming convention is required when you list files under `inputs.runs`. For
large sweeps, you can optionally use `inputs.files` plus
`infer.filename_pattern` to extract metadata from filenames:

```yaml
inputs:
  files: runs/rtt_sweep_*.json

defaults:
  scenario: rtt_sweep

infer:
  filename_pattern: "rtt_sweep_{cc_algo}_rtt{rtt_ms}.json"
```

Placeholder names become metadata columns. For example,
`rtt_sweep_bbrv3_rtt80.json` sets `cc_algo: bbrv3` and `rtt_ms: 80`.

## Output Files

`iperfplot all` and `iperfplot experiment` create:

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
- `experiment_summary.csv`: one row per experiment condition for sweep plots
- `flow_fairness.csv`: Jain fairness over time among active transfers
- `stream_fairness.csv`: Jain fairness over time among active streams
- `flow_share.csv` and `stream_share.csv`: bandwidth share over time
- `stream_similarity.csv`: bounded pairwise checks for similar stream series

Use `flow_*` tables for transfer-level plots that aggregate parallel streams.
Use `stream_*` tables when you want to inspect individual `-P` streams.

## Commands

```bash
iperfplot all *.json --out results
iperfplot experiment experiment.yaml --out results
iperfplot validate experiment.yaml
iperfplot parse *.json --out data
iperfplot plot *.json --out plots --format png --format pdf
iperfplot report *.json --out report.html
iperfplot fairness *.json --level flow
iperfplot diagnose run1.json
```

## Advanced Features

For a detailed guide with experiment YAML snippets, BBRv3-style scenarios, and
figures generated by the tool, see
[docs/experiment_files.md](docs/experiment_files.md).

Experiment-file plots support:

- `line`, `time_series`, `scatter`, `bar`, `box`, `histogram`, `cdf`, `ccdf`, and `heatmap`
- reusable `data` fields: `source`, `filter`, `x`, `y`, `value`, `group_by`, `facet_by`, `aggregate`, `annotations`
- reusable `display` fields: `title`, `x_label`, `y_label`, `value_label`, `legend`, `size`, `width`, `height`, `colors`, `color`, `palette`, `cmap`, `dpi`, `marker`, `line_width`, `xlim`, `ylim`, `log_x`, and `log_y`

Example plot gallery:

| RTT CDF | Throughput Time Series |
| --- | --- |
| ![RTT CDF by flow](docs/images/rtt_cdf_by_flow.png) | ![Throughput by flow](docs/images/throughput_by_flow.png) |

| RTT Box Plot | Retransmit Histogram |
| --- | --- |
| ![RTT box plot by flow](docs/images/flow_rtt_boxplot.png) | ![Retransmit histogram](docs/images/retransmit_histogram.png) |

Regenerate the gallery:

```bash
PYTHONPATH=src python3 -m iperf3_plotter custom \
  sample/my_test.json \
  --plot-spec examples/custom_plots.yaml \
  --out docs/images \
  --format png
```

The low-level `custom --plot-spec` and `--manifest` options are still available
for compatibility, but new research workflows should prefer a single
`experiment.yaml`.

## Optional Test Lab

The `lab/` directory contains a Docker-based Mininet/iperf3 testbed. It runs
Mininet and `tc` inside Linux, generates iperf3 JSON files, and runs the
plotter.

```bash
make lab
make lab-overlap
```

The lab writes output under `lab-results/`.

## Development

Run tests:

```bash
make test
```

Remove generated outputs:

```bash
make clean
```
