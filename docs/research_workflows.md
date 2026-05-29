# Research Workflow Examples

This page shows how to use `iperf3_plotter` as a configurable plotting tool
for research-style TCP experiments. The goal is not to hard-code one paper's
figures. The goal is to make the paper's figure types easy to express with:

1. iperf3 JSON files
2. a manifest that describes each JSON file
3. a YAML plot spec that says what to plot

The examples use the BBRv3 evaluation repository and paper as inspiration:

- BBRv3 experiment repository: <https://github.com/gomezgaona/bbr3/tree/main>
- BBRv3 paper PDF: <https://par.nsf.gov/servlets/purl/10545111>

Use the same pattern for CUBIC, Reno, BBRv1, BBRv2, BBRv3, parallel streams,
staggered starts, loss sweeps, buffer sweeps, AQM comparisons, RTT unfairness,
or flow-completion-time experiments.

## The Workflow

Generate one iperf3 JSON file per client transfer:

```bash
iperf3 -c SERVER_IP -J -i 1 -t 60 > runs/cubic_rtt20_trial1.json
iperf3 -c SERVER_IP -J -i 1 -t 60 -P 4 > runs/bbrv3_parallel_trial1.json
iperf3 -c SERVER_IP -J -i 1 -n 10M > runs/bbrv3_shortflow_trial1.json
```

Create a manifest. The manifest maps each JSON file to the experiment metadata
that is not inside iperf's JSON:

```csv
file,flow_id,flow_label,scenario,cc_algo,trial,start_offset_s,rtt_ms,buffer_bdp,loss_percent,bottleneck_mbps,aqm
runs/cubic_rtt20_trial1.json,cubic_rtt20_t1,CUBIC 20 ms,rtt_sweep,cubic,1,0,20,1,0.025,1000,taildrop
runs/bbrv3_rtt20_trial1.json,bbrv3_rtt20_t1,BBRv3 20 ms,rtt_sweep,bbrv3,1,0,20,1,0.025,1000,taildrop
```

Create a plot spec:

```yaml
plots:
  - name: throughput_vs_rtt
    kind: line
    source: flow_summary
    filters:
      scenario: rtt_sweep
    x: rtt_config_ms
    y: avg_throughput_mbps
    group_by: cc_algo
    aggregate: mean
    marker: o
    title: Throughput as a function of RTT
    x_label: Configured RTT (ms)
    y_label: Average throughput (Mbps)
```

Run the tool:

```bash
iperfplot all runs/*.json \
  --manifest manifest.csv \
  --plot-spec plots.yaml \
  --time-mode offset \
  --out results
```

The full BBRv3-style template files are:

- `examples/bbr3_showcase_manifest.example.csv`
- `examples/bbr3_showcase_plots.yaml`

Replace the placeholder file paths in the manifest with your own JSON paths.

## Manifest Rules

The most important rule is:

```text
one manifest row -> one iperf3 JSON file -> one flow_id
```

If one iperf3 client uses `-P 4`, that is still one transfer and should usually
be one `flow_id`. The tool keeps both views:

- `intervals`: one row per stream per interval
- `flow_intervals`: parallel streams aggregated per transfer per interval
- `stream_summary`: one row per stream
- `flow_summary`: one row per transfer

Use `stream_*` sources when you want to inspect parallel streams. Use
`flow_*` sources when you want the transfer-level plot that papers usually
show.

Common manifest columns:

| Column | Purpose |
| --- | --- |
| `file` | Path to the iperf3 JSON file |
| `flow_id` | Stable ID for one transfer |
| `flow_label` | Human-readable legend label |
| `scenario` | Experiment family, such as `rtt_sweep` or `loss_sweep` |
| `cc_algo` | Congestion control, such as `cubic` or `bbrv3` |
| `trial` | Repetition number |
| `start_offset_s` | Intended flow start time for staggered experiments |
| `rtt_ms` | Configured RTT; appears in tables as `rtt_config_ms` |
| `buffer_bdp` | Buffer size normalized by BDP |
| `loss_percent` | Configured random loss rate |
| `bottleneck_mbps` | Bottleneck bandwidth, used for utilization |
| `aqm` | Queue policy, such as `taildrop` or `fq_codel` |
| `cc_mix` | Coexistence label, such as `cubic_vs_bbrv3` |
| `num_flows` | Number of competing flows |

Any extra manifest column is preserved and can be used in a plot spec as
`x`, `y`, `group_by`, `facet_by`, `filters`, or heatmap dimensions.

## Plot Sources

The plot spec chooses a `source`. Think of the source as the table the plot
reads from.

| Source | Best for |
| --- | --- |
| `intervals` | Per-stream time series, RTT CDFs, retransmit histograms |
| `flow_intervals` | Per-transfer time series after aggregating parallel streams |
| `stream_time_bins` | Per-stream aligned time series across clients |
| `flow_time_bins` | Per-flow aligned time series across clients |
| `stream_summary` | One summary row per stream |
| `flow_summary` | One summary row per transfer |
| `flow_fairness` | Jain fairness over time among active flows |
| `flow_share` | Per-flow bandwidth share over time |
| `experiment_summary` | One row per scenario/trial/condition, with fairness, utilization, and per-CCA shares |

Useful generated metrics include:

| Metric | Source examples |
| --- | --- |
| `throughput_mbps` | `intervals`, `flow_intervals`, `flow_time_bins` |
| `avg_throughput_mbps` | `stream_summary`, `flow_summary` |
| `retransmits` | interval, summary, and experiment tables |
| `rtt_ms`, `mean_rtt_ms`, `p95_rtt_ms` | interval and summary tables |
| `duration_s` | flow completion time for fixed-size transfers |
| `jain_fairness` | `flow_fairness`, `experiment_summary` |
| `link_utilization_percent` | `experiment_summary`, when `bottleneck_mbps` is in the manifest |
| `share_cubic_percent`, `share_bbrv3_percent` | `experiment_summary`, derived from `cc_algo` |

## Paper-Style Recipes

The BBRv3 paper includes several figure families. The sections below show how
to express those families with manifest columns and plot specs.

### Throughput and Retransmissions vs RTT

Use this for paper-style figures where the x-axis is configured RTT or
propagation delay and the series are congestion-control algorithms.

Manifest rows:

```csv
file,flow_id,flow_label,scenario,cc_algo,trial,start_offset_s,rtt_ms,loss_percent,bottleneck_mbps
runs/rtt/cubic_rtt2_t1.json,cubic_rtt2_t1,CUBIC 2 ms,rtt_sweep,cubic,1,0,2,0.025,1000
runs/rtt/bbrv3_rtt2_t1.json,bbrv3_rtt2_t1,BBRv3 2 ms,rtt_sweep,bbrv3,1,0,2,0.025,1000
runs/rtt/cubic_rtt20_t1.json,cubic_rtt20_t1,CUBIC 20 ms,rtt_sweep,cubic,1,0,20,0.025,1000
runs/rtt/bbrv3_rtt20_t1.json,bbrv3_rtt20_t1,BBRv3 20 ms,rtt_sweep,bbrv3,1,0,20,0.025,1000
```

Spec:

```yaml
plots:
  - name: throughput_vs_rtt
    kind: line
    source: flow_summary
    filters: {scenario: rtt_sweep}
    x: rtt_config_ms
    y: avg_throughput_mbps
    group_by: cc_algo
    aggregate: mean
    marker: o
    x_label: Configured RTT (ms)
    y_label: Average throughput (Mbps)

  - name: retransmits_vs_rtt
    kind: line
    source: flow_summary
    filters: {scenario: rtt_sweep}
    x: rtt_config_ms
    y: retransmits
    group_by: cc_algo
    aggregate: mean
    marker: o
    x_label: Configured RTT (ms)
    y_label: Retransmissions (packets)
```

### Throughput and Retransmissions vs Loss

Use this for loss-resilience plots.

Manifest rows:

```csv
file,flow_id,scenario,cc_algo,trial,start_offset_s,rtt_ms,buffer_bdp,loss_percent,bottleneck_mbps
runs/loss/bbrv3_loss001_t1.json,bbrv3_loss001_t1,loss_sweep,bbrv3,1,0,20,1,0.01,1000
runs/loss/bbrv3_loss01_t1.json,bbrv3_loss01_t1,loss_sweep,bbrv3,1,0,20,1,0.1,1000
runs/loss/bbrv3_loss1_t1.json,bbrv3_loss1_t1,loss_sweep,bbrv3,1,0,20,1,1,1000
```

Spec:

```yaml
plots:
  - name: throughput_vs_loss
    kind: line
    source: flow_summary
    filters: {scenario: loss_sweep}
    x: loss_percent
    y: avg_throughput_mbps
    group_by: cc_algo
    aggregate: mean
    marker: o
    log_x: true
    x_label: Random packet loss (%)
    y_label: Average throughput (Mbps)

  - name: retransmits_vs_loss
    kind: line
    source: flow_summary
    filters: {scenario: loss_sweep}
    x: loss_percent
    y: retransmits
    group_by: cc_algo
    aggregate: mean
    marker: o
    log_x: true
    log_y: true
    x_label: Random packet loss (%)
    y_label: Retransmissions (packets)
```

### RTT Unfairness and AQM

Use this when two or more flows have different configured RTTs, and you want to
compare Tail Drop, FQ-CoDel, CAKE, ECN, or another queue policy.

Manifest rows:

```csv
file,flow_id,flow_label,scenario,cc_algo,aqm,trial,start_offset_s,rtt_ms,buffer_bdp,bottleneck_mbps
runs/rtt_unfair/h1_20ms_bdp1_taildrop.json,bbrv3_20ms_td,20 ms,rtt_unfairness,bbrv3,taildrop,1,0,20,1,1000
runs/rtt_unfair/h2_100ms_bdp1_taildrop.json,bbrv3_100ms_td,100 ms,rtt_unfairness,bbrv3,taildrop,1,0,100,1,1000
runs/rtt_unfair/h1_20ms_bdp1_fq.json,bbrv3_20ms_fq,20 ms,rtt_unfairness,bbrv3,fq_codel,1,0,20,1,1000
runs/rtt_unfair/h2_100ms_bdp1_fq.json,bbrv3_100ms_fq,100 ms,rtt_unfairness,bbrv3,fq_codel,1,0,100,1,1000
```

Spec:

```yaml
plots:
  - name: rtt_unfairness_throughput_vs_buffer
    kind: line
    source: flow_summary
    filters: {scenario: rtt_unfairness}
    x: buffer_bdp
    y: avg_throughput_mbps
    group_by: rtt_config_ms
    facet_by: aqm
    aggregate: mean
    marker: o
    log_x: true
    x_label: Buffer size (BDP)
    y_label: Average throughput (Mbps)

  - name: rtt_unfairness_fairness_vs_buffer
    kind: line
    source: experiment_summary
    filters: {scenario: rtt_unfairness}
    x: buffer_bdp
    y: jain_fairness
    group_by: aqm
    aggregate: mean
    marker: o
    log_x: true
    ylim: [0, 1.05]
    x_label: Buffer size (BDP)
    y_label: Jain fairness
```

### Staggered Flow Starts

Use this for figures where flows start at different times and overlap. Put the
intended start time in `start_offset_s`, then run with `--time-mode offset`.

Manifest rows:

```csv
file,flow_id,flow_label,scenario,cc_algo,trial,start_offset_s,rtt_ms,buffer_bdp,bottleneck_mbps
runs/staggered/h1_cubic.json,cubic_long,CUBIC flow,staggered_coexistence,cubic,1,0,20,1,1000
runs/staggered/h2_bbrv3.json,bbrv3_1,BBRv3 flow 1,staggered_coexistence,bbrv3,1,60,20,1,1000
runs/staggered/h3_bbrv3.json,bbrv3_2,BBRv3 flow 2,staggered_coexistence,bbrv3,1,120,20,1,1000
```

Spec:

```yaml
plots:
  - name: staggered_flow_throughput
    kind: time_series
    source: flow_time_bins
    filters: {scenario: staggered_coexistence}
    x: time_bin_start_s
    y: throughput_mbps
    group_by: flow_label
    aggregate: mean
    x_label: Experiment time (s)
    y_label: Throughput (Mbps)

  - name: staggered_flow_fairness
    kind: line
    source: flow_fairness
    filters: {scenario: staggered_coexistence}
    x: time_bin_start_s
    y: jain_fairness
    aggregate: mean
    ylim: [0, 1.05]
    x_label: Experiment time (s)
    y_label: Jain fairness
```

Command:

```bash
iperfplot all runs/staggered/*.json \
  --manifest staggered_manifest.csv \
  --plot-spec examples/bbr3_showcase_plots.yaml \
  --time-mode offset \
  --out results/staggered
```

### Flow Completion Time CDF

Use fixed-size transfers with `iperf3 -n SIZE`. The transfer duration becomes
`flow_summary.duration_s`, which can be plotted as FCT.

Manifest rows:

```csv
file,flow_id,scenario,cc_algo,trial,start_offset_s,transfer_size_mb,buffer_bdp,bottleneck_mbps
runs/fct/cubic_10mb_t1.json,cubic_fct_t1,fct,cubic,1,0,10,1,1000
runs/fct/bbrv3_10mb_t1.json,bbrv3_fct_t1,fct,bbrv3,1,0,10,1,1000
```

Spec:

```yaml
plots:
  - name: fct_cdf_by_cc
    kind: cdf
    source: flow_summary
    filters: {scenario: fct}
    metric: duration_s
    group_by: cc_algo
    x_label: Flow completion time (s)
```

### Bandwidth-Delay Heatmap

Use this for sweep plots where each cell is an experiment condition. The color
can be fairness, utilization, average throughput, or another metric from
`experiment_summary`.

Manifest rows:

```csv
file,flow_id,scenario,cc_algo,cc_mix,trial,start_offset_s,propagation_delay_ms,bottleneck_mbps,buffer_bdp,loss_percent
runs/heatmap/bw100_d20_cubic.json,cubic_bw100_d20,bdp_sweep,cubic,cubic_vs_bbrv3,1,0,20,100,1,0
runs/heatmap/bw100_d20_bbrv3.json,bbrv3_bw100_d20,bdp_sweep,bbrv3,cubic_vs_bbrv3,1,0,20,100,1,0
runs/heatmap/bw1000_d80_cubic.json,cubic_bw1000_d80,bdp_sweep,cubic,cubic_vs_bbrv3,1,0,80,1000,1,0
runs/heatmap/bw1000_d80_bbrv3.json,bbrv3_bw1000_d80,bdp_sweep,bbrv3,cubic_vs_bbrv3,1,0,80,1000,1,0
```

Spec:

```yaml
plots:
  - name: fairness_heatmap_bandwidth_delay
    kind: heatmap
    source: experiment_summary
    x: propagation_delay_ms
    y: bottleneck_mbps
    value: jain_fairness
    facet_by: [scenario, buffer_bdp, loss_percent]
    annotations:
      - link_utilization_percent
      - share_cubic_percent
      - share_bbrv3_percent
    cmap: YlGnBu
    annotation_color: black
    x_label: Propagation delay (ms)
    y_label: Bottleneck bandwidth (Mbps)
```

## Example Figures Generated by the Tool

These figures are generated from `sample/my_test.json` using
`examples/custom_plots.yaml`. They are small examples that prove the plot-spec
path works; the paper-style specs above use the same mechanism.

| RTT CDF | Throughput Time Series |
| --- | --- |
| ![RTT CDF by flow](images/rtt_cdf_by_flow.png) | ![Throughput by flow](images/throughput_by_flow.png) |

| RTT Box Plot | Retransmit Histogram |
| --- | --- |
| ![RTT box plot by flow](images/flow_rtt_boxplot.png) | ![Retransmit histogram](images/retransmit_histogram.png) |

Regenerate them:

```bash
PYTHONPATH=src python3 -m iperf3_plotter custom \
  sample/my_test.json \
  --plot-spec examples/custom_plots.yaml \
  --out docs/images \
  --format png
```

## What iperf3 JSON Can and Cannot Provide

From iperf3 JSON alone, the tool can plot throughput, transfer size,
retransmissions, TCP RTT samples, RTT variation, congestion window, PMTU, loss
fields when present, stream-level behavior, flow-level aggregates, fairness,
bandwidth shares, utilization, and FCT for fixed-size transfers.

Some paper figures require telemetry that is not in iperf3 JSON. Queue
occupancy, AQM drop/mark counts, switch counters, host CPU, and qdisc backlog
must be collected separately. You can still encode the configured queue policy
in the manifest with `aqm`, but true queue-occupancy time series require an
additional data source.

## Checklist

Before generating paper-style plots:

- Use `iperf3 -J` for every client.
- Put one row per JSON file in the manifest.
- Use `flow_id` for each transfer, not each stream.
- Use `cc_algo` consistently, for example `cubic`, `bbrv2`, `bbrv3`.
- Add the sweep dimensions you want to plot, such as `buffer_bdp`,
  `loss_percent`, `rtt_ms`, `bottleneck_mbps`, `aqm`, and `trial`.
- Use `--time-mode offset` when your manifest has `start_offset_s`.
- Use `--time-mode global` only when iperf client clocks are synchronized.
- Inspect `results/data/flow_summary.csv` and
  `results/data/experiment_summary.csv` when a plot does not look right.

## Common Issues

`missing column(s)`:

The plot spec references a column that is not in the selected source table.
Add the column to the manifest or choose a different source.

All flows start at X=0:

You probably used the default relative time mode. Use `--time-mode global` or
`--time-mode offset`.

Heatmap has no output:

Check that each experiment condition has values for the heatmap `x`, `y`, and
`value` columns. For paper-style heatmaps, inspect
`results/data/experiment_summary.csv`.

Share column is missing:

Per-CCA share columns are generated from `cc_algo`. For example, `cc_algo=bbrv3`
produces `share_bbrv3_percent`.
