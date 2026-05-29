from pathlib import Path
import shutil
import tempfile
import unittest

from iperf3_plotter.custom import build_plot_sources, generate_custom_plots
from iperf3_plotter.parser import parse_files


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample" / "my_test.json"


class CustomPlotsTest(unittest.TestCase):
    def test_custom_cdf_and_heatmap_specs_render(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            flow1 = temp_path / "flow1.json"
            flow2 = temp_path / "flow2.json"
            shutil.copyfile(SAMPLE, flow1)
            shutil.copyfile(SAMPLE, flow2)
            metadata = {
                flow1.name: {
                    "flow_id": "cubic-flow",
                    "cc_algo": "cubic",
                    "bottleneck_mbps": 100,
                    "buffer_bdp": 1,
                    "propagation_delay_ms": 20,
                    "loss_percent": 0,
                    "num_flows": 2,
                    "trial": 1,
                },
                flow2.name: {
                    "flow_id": "bbrv2-flow",
                    "cc_algo": "bbrv2",
                    "bottleneck_mbps": 100,
                    "buffer_bdp": 1,
                    "propagation_delay_ms": 20,
                    "loss_percent": 0,
                    "num_flows": 2,
                    "trial": 1,
                },
            }
            intervals, summaries, runs = parse_files([flow1, flow2], metadata)
            spec = temp_path / "plots.yaml"
            spec.write_text(
                """
plots:
  - name: rtt_cdf_by_flow
    kind: cdf
    source: flow_intervals
    metric: rtt_ms
    group_by: flow_id
    legend: false
    figsize: [6.5, 4.0]
    dpi: 120
    colors:
      cubic-flow: "#1f77b4"
      bbrv2-flow: "#2ca02c"
    linewidth: 2.1
  - name: fairness_heatmap
    kind: heatmap
    source: experiment_summary
    x: propagation_delay_ms
    y: bottleneck_mbps
    value: jain_fairness
    annotations:
      - link_utilization_percent
      - share_cubic_percent
      - share_bbrv2_percent
    cmap: YlGnBu
    annotation_color: black
    annotation_fontsize: 7
""",
                encoding="utf-8",
            )

            artifacts = generate_custom_plots(intervals, summaries, runs, temp_path / "plots", spec_path=spec, formats=["png"])

            names = {artifact.name for artifact in artifacts}
            self.assertIn("rtt_cdf_by_flow", names)
            self.assertIn("fairness_heatmap", names)
            self.assertTrue((temp_path / "plots" / "rtt_cdf_by_flow.png").exists())
            self.assertTrue((temp_path / "plots" / "fairness_heatmap.png").exists())

    def test_manifest_metadata_reaches_experiment_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            flow1 = temp_path / "flow1.json"
            flow2 = temp_path / "flow2.json"
            shutil.copyfile(SAMPLE, flow1)
            shutil.copyfile(SAMPLE, flow2)
            metadata = {
                flow1.name: {
                    "flow_id": "cubic-flow",
                    "cc_algo": "cubic",
                    "bottleneck_mbps": 50,
                    "buffer_bdp": 0.5,
                    "propagation_delay_ms": 40,
                    "loss_percent": 1,
                },
                flow2.name: {
                    "flow_id": "bbrv2-flow",
                    "cc_algo": "bbrv2",
                    "bottleneck_mbps": 50,
                    "buffer_bdp": 0.5,
                    "propagation_delay_ms": 40,
                    "loss_percent": 1,
                },
            }

            intervals, summaries, runs = parse_files([flow1, flow2], metadata)
            sources = build_plot_sources(intervals, summaries, runs)
            experiment = sources["experiment_summary"]

            self.assertIn("propagation_delay_ms", sources["flow_summary"].columns)
            self.assertIn("loss_percent", experiment.columns)
            self.assertIn("share_cubic_percent", experiment.columns)
            self.assertIn("share_bbrv2_percent", experiment.columns)
            self.assertEqual(experiment.iloc[0]["propagation_delay_ms"], 40)

    def test_experiment_summary_does_not_split_rtt_unfairness_flows_by_rtt_class(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            flow1 = temp_path / "flow1.json"
            flow2 = temp_path / "flow2.json"
            shutil.copyfile(SAMPLE, flow1)
            shutil.copyfile(SAMPLE, flow2)
            metadata = {
                flow1.name: {
                    "flow_id": "bbrv3-20ms",
                    "cc_algo": "bbrv3",
                    "scenario": "rtt_unfairness",
                    "aqm": "taildrop",
                    "buffer_bdp": 1,
                    "rtt_ms": 20,
                    "bottleneck_mbps": 1000,
                },
                flow2.name: {
                    "flow_id": "bbrv3-100ms",
                    "cc_algo": "bbrv3",
                    "scenario": "rtt_unfairness",
                    "aqm": "taildrop",
                    "buffer_bdp": 1,
                    "rtt_ms": 100,
                    "bottleneck_mbps": 1000,
                },
            }

            intervals, summaries, runs = parse_files([flow1, flow2], metadata)
            experiment = build_plot_sources(intervals, summaries, runs)["experiment_summary"]

            self.assertEqual(len(experiment), 1)
            self.assertEqual(experiment.iloc[0]["flows"], 2)

    def test_bbr3_showcase_spec_renders_from_manifest_style_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            rows = [
                ("rtt_cubic_2", {"scenario": "rtt_sweep", "cc_algo": "cubic", "rtt_ms": 2, "propagation_delay_ms": 2}),
                ("rtt_bbrv3_2", {"scenario": "rtt_sweep", "cc_algo": "bbrv3", "rtt_ms": 2, "propagation_delay_ms": 2}),
                ("rtt_cubic_20", {"scenario": "rtt_sweep", "cc_algo": "cubic", "rtt_ms": 20, "propagation_delay_ms": 20}),
                ("rtt_bbrv3_20", {"scenario": "rtt_sweep", "cc_algo": "bbrv3", "rtt_ms": 20, "propagation_delay_ms": 20}),
                ("loss_bbrv3_001", {"scenario": "loss_sweep", "cc_algo": "bbrv3", "loss_percent": 0.01}),
                ("loss_bbrv3_1", {"scenario": "loss_sweep", "cc_algo": "bbrv3", "loss_percent": 1}),
                ("unfair_20_taildrop", {"scenario": "rtt_unfairness", "cc_algo": "bbrv3", "rtt_ms": 20, "aqm": "taildrop"}),
                ("unfair_100_taildrop", {"scenario": "rtt_unfairness", "cc_algo": "bbrv3", "rtt_ms": 100, "aqm": "taildrop"}),
                ("unfair_20_fq", {"scenario": "rtt_unfairness", "cc_algo": "bbrv3", "rtt_ms": 20, "aqm": "fq_codel"}),
                ("unfair_100_fq", {"scenario": "rtt_unfairness", "cc_algo": "bbrv3", "rtt_ms": 100, "aqm": "fq_codel"}),
                ("stagger_cubic", {"scenario": "staggered_coexistence", "cc_algo": "cubic", "flow_label": "CUBIC", "start_offset_s": 0}),
                ("stagger_bbrv3", {"scenario": "staggered_coexistence", "cc_algo": "bbrv3", "flow_label": "BBRv3", "start_offset_s": 5}),
                ("fct_cubic", {"scenario": "fct", "cc_algo": "cubic"}),
                ("fct_bbrv3", {"scenario": "fct", "cc_algo": "bbrv3"}),
                ("bdp_cubic_100_20", {"scenario": "bdp_sweep", "cc_algo": "cubic", "propagation_delay_ms": 20, "bottleneck_mbps": 100}),
                ("bdp_bbrv3_100_20", {"scenario": "bdp_sweep", "cc_algo": "bbrv3", "propagation_delay_ms": 20, "bottleneck_mbps": 100}),
                ("bdp_cubic_1000_80", {"scenario": "bdp_sweep", "cc_algo": "cubic", "propagation_delay_ms": 80, "bottleneck_mbps": 1000}),
                ("bdp_bbrv3_1000_80", {"scenario": "bdp_sweep", "cc_algo": "bbrv3", "propagation_delay_ms": 80, "bottleneck_mbps": 1000}),
            ]
            paths = []
            metadata = {}
            for index, (name, row_metadata) in enumerate(rows, start=1):
                path = temp_path / f"{name}.json"
                shutil.copyfile(SAMPLE, path)
                paths.append(path)
                metadata[path.name] = {
                    "flow_id": name,
                    "trial": 1,
                    "buffer_bdp": row_metadata.get("buffer_bdp", 1),
                    "loss_percent": row_metadata.get("loss_percent", 0),
                    "bottleneck_mbps": row_metadata.get("bottleneck_mbps", 1000),
                    "propagation_delay_ms": row_metadata.get("propagation_delay_ms", 20),
                    **row_metadata,
                }

            intervals, summaries, runs = parse_files(paths, metadata)
            artifacts = generate_custom_plots(
                intervals,
                summaries,
                runs,
                temp_path / "plots",
                spec_path=ROOT / "examples" / "bbr3_showcase_plots.yaml",
                formats=["png"],
                time_mode="offset",
            )
            names = {artifact.name for artifact in artifacts}

            self.assertIn("throughput_vs_rtt", names)
            self.assertIn("staggered_flow_fairness", names)
            self.assertIn("fct_cdf_by_cc", names)
            self.assertIn("fairness_heatmap_bandwidth_delay", names)


if __name__ == "__main__":
    unittest.main()
