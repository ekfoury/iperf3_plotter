# Mininet/iperf3 Lab

Mininet and `tc` require Linux kernel features, so this lab runs inside a
privileged Linux container. On Linux, Docker uses the host kernel. On macOS,
Docker Desktop provides the Linux VM.

## Requirements

- Docker running
- Local Python environment that can run `iperf3_plotter`

## Run

From the repo root:

```bash
make lab
```

To verify overlapping flows and parallel streams in one shot:

```bash
make lab-overlap
```

That starts two clients, gives each flow three parallel iperf3 streams, and
starts the second flow 5 seconds after the first. With the default 12-second
duration, both flows are active together from about X=5 to X=12.

Or call the script directly:

```bash
lab/run_docker_lab.sh --clients 2 --duration 20 --stagger 5 --bw 100 --delay 20ms --cc cubic,bbr
```

Docker Desktop's Linux kernel may not expose every TCP congestion-control
algorithm. If a requested algorithm is unavailable, the lab falls back to
`cubic` or `reno` and records both `requested_cc_algo` and `cc_algo` in the
experiment file. Use `--strict-cc` if you want unsupported algorithms to fail
instead.

By default the topology uses a Linux bridge switch inside Mininet because it is
more reliable than Open vSwitch inside Docker Desktop. To test with OVS anyway,
pass `--switch ovs`.

The lab creates:

- `lab-results/raw/*.json`: one iperf3 JSON file per client
- `lab-results/raw/*.stderr`: iperf3 stderr logs
- `lab-results/experiment.json`: experiment file with `start_offset_s`, metadata, and inputs
- `lab-results/analysis/report.html`: plots and summary report

The generated experiment file uses `time_mode: offset`, so if client 1 starts
at 0 seconds and client 2 starts at 5 seconds, client 2 appears at X=5 in the
plots.

## Useful Variants

Three clients, 10 seconds apart:

```bash
lab/run_docker_lab.sh --clients 3 --duration 30 --stagger 10 --bw 50 --delay 40ms
```

Parallel streams per client:

```bash
lab/run_docker_lab.sh --clients 2 --parallel 4 --duration 20 --stagger 5
```

Add loss on the shared bottleneck:

```bash
lab/run_docker_lab.sh --clients 2 --bw 20 --delay 50ms --loss 0.5
```
