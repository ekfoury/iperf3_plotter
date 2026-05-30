#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

from mininet.clean import cleanup
from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import OVSBridge, Switch
from mininet.topo import Topo


class LinuxBridge(Switch):
    """Simple learning bridge that avoids the Open vSwitch daemon dependency."""

    def start(self, controllers) -> None:
        self.cmd("ip link add name", self.name, "type bridge")
        self.cmd("ip link set dev", self.name, "up")
        for intf in self.intfList():
            if intf.name != "lo":
                self.cmd("ip link set dev", intf.name, "master", self.name)
                self.cmd("ip link set dev", intf.name, "up")

    def stop(self, deleteIntfs: bool = True) -> None:
        self.cmd("ip link set dev", self.name, "down")
        self.cmd("ip link del", self.name, "type bridge")
        super().stop(deleteIntfs)


class BottleneckTopo(Topo):
    def build(self, clients: int, bw: float, delay: str, loss: float, queue: int) -> None:
        switch = self.addSwitch("s1")
        server = self.addHost("server")
        self.addLink(
            server,
            switch,
            cls=TCLink,
            bw=bw,
            delay=delay,
            loss=loss,
            max_queue_size=queue,
            use_htb=True,
        )
        for index in range(1, clients + 1):
            client = self.addHost(f"c{index}")
            self.addLink(client, switch, cls=TCLink, bw=1000, delay="1ms", loss=0, use_htb=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate staggered iperf3 client flows in Mininet.")
    parser.add_argument("--out", default="/work/lab-results/raw", help="Directory for iperf3 JSON files.")
    parser.add_argument("--clients", type=int, default=2, help="Number of iperf3 clients.")
    parser.add_argument("--duration", type=int, default=20, help="iperf3 duration per client in seconds.")
    parser.add_argument("--stagger", type=float, default=5.0, help="Seconds between client start times.")
    parser.add_argument("--parallel", type=int, default=1, help="iperf3 parallel streams per client.")
    parser.add_argument("--interval", type=float, default=1.0, help="iperf3 reporting interval.")
    parser.add_argument("--bw", type=float, default=100.0, help="Shared bottleneck bandwidth in Mbps.")
    parser.add_argument("--delay", default="20ms", help="Delay on bottleneck server link.")
    parser.add_argument("--loss", type=float, default=0.0, help="Loss percentage on bottleneck server link.")
    parser.add_argument("--queue", type=int, default=100, help="Bottleneck queue size in packets.")
    parser.add_argument("--cc", default="cubic", help="Comma-separated congestion controls, cycled per client.")
    parser.add_argument("--title", default="mininet-staggered-iperf3", help="Scenario name for the experiment file.")
    parser.add_argument("--switch", choices=["linuxbridge", "ovs"], default="linuxbridge", help="Switch backend.")
    parser.add_argument("--strict-cc", action="store_true", help="Fail if a requested congestion control is unavailable.")
    args = parser.parse_args()

    if args.clients < 1:
        parser.error("--clients must be at least 1")
    if args.parallel < 1:
        parser.error("--parallel must be at least 1")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old_file in out_dir.glob("*"):
        if old_file.is_file():
            old_file.unlink()
    experiment_path = out_dir.parent / "experiment.json"
    cc_algos = [item.strip() for item in args.cc.split(",") if item.strip()] or ["cubic"]
    available_cc = _available_congestion_controls()

    setLogLevel("info")
    cleanup()
    topo = BottleneckTopo(args.clients, args.bw, args.delay, args.loss, args.queue)
    switch_cls = LinuxBridge if args.switch == "linuxbridge" else OVSBridge
    net = Mininet(topo=topo, switch=switch_cls, controller=None, link=TCLink, autoSetMacs=True)
    server_processes: list[subprocess.Popen] = []
    client_processes: list[tuple[str, subprocess.Popen]] = []

    try:
        net.start()
        server = net.get("server")
        server_ip = server.IP()

        for index in range(1, args.clients + 1):
            port = 5200 + index
            server_processes.append(server.popen(["iperf3", "-s", "-p", str(port)]))
        time.sleep(1)

        runs = []
        for index in range(1, args.clients + 1):
            client = net.get(f"c{index}")
            port = 5200 + index
            offset = (index - 1) * args.stagger
            requested_cc_algo = cc_algos[(index - 1) % len(cc_algos)]
            cc_algo = _choose_congestion_control(requested_cc_algo, available_cc, args.strict_cc)
            cc_fallback = cc_algo != requested_cc_algo
            if cc_fallback:
                print(
                    f"Requested congestion control '{requested_cc_algo}' is unavailable; "
                    f"using '{cc_algo}' for client {index}. Available: {', '.join(available_cc)}",
                    file=sys.stderr,
                )
            flow_id = f"flow{index}-{cc_algo}"
            json_path = out_dir / f"{flow_id}.json"
            stderr_path = out_dir / f"{flow_id}.stderr"
            command = [
                "bash",
                "-lc",
                (
                    f"sleep {offset}; "
                    f"iperf3 -c {server_ip} -p {port} -J -i {args.interval} "
                    f"-t {args.duration} -P {args.parallel} -C {cc_algo} "
                    f"> {json_path} 2> {stderr_path}"
                ),
            ]
            client_processes.append((flow_id, client.popen(command)))
            runs.append(
                {
                    "file": f"raw/{json_path.name}",
                    "run_id": flow_id,
                    "flow_id": flow_id,
                    "flow_label": f"{cc_algo.upper()} client {index}",
                    "cc_algo": cc_algo,
                    "requested_cc_algo": requested_cc_algo,
                    "cc_fallback": cc_fallback,
                    "available_cc_algos": ",".join(available_cc),
                    "start_offset_s": offset,
                    "bottleneck_mbps": args.bw,
                    "bottleneck_delay": args.delay,
                    "loss_percent": args.loss,
                    "queue_packets": args.queue,
                    "parallel_streams": args.parallel,
                    "scenario": args.title,
                }
            )

        exit_code = 0
        for flow_id, process in client_processes:
            code = process.wait()
            if code != 0:
                print(f"{flow_id} exited with status {code}", file=sys.stderr)
                exit_code = code

        experiment = {
            "name": args.title,
            "description": "Generated by lab/mininet_iperf_lab.py",
            "time_mode": "offset",
            "inputs": {"runs": runs},
        }
        experiment_path.write_text(json.dumps(experiment, indent=2), encoding="utf-8")
        print(f"Wrote experiment file: {experiment_path}")
        return exit_code
    finally:
        for process in server_processes:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
        net.stop()
        cleanup()


def _available_congestion_controls() -> list[str]:
    path = Path("/proc/sys/net/ipv4/tcp_available_congestion_control")
    if not path.exists():
        return ["cubic"]
    controls = path.read_text(encoding="utf-8").strip().split()
    return controls or ["cubic"]


def _choose_congestion_control(requested: str, available: list[str], strict: bool) -> str:
    if requested in available:
        return requested
    if strict:
        raise SystemExit(
            f"Requested congestion control '{requested}' is unavailable. "
            f"Available algorithms: {', '.join(available)}"
        )
    for fallback in ("cubic", "reno"):
        if fallback in available:
            return fallback
    return available[0]


if __name__ == "__main__":
    raise SystemExit(main())
