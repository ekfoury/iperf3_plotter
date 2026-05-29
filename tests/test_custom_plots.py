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


if __name__ == "__main__":
    unittest.main()
