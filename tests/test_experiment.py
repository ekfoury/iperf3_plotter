from pathlib import Path
import shutil
import tempfile
import unittest

from iperf3_plotter.experiment import resolve_experiment, run_experiment, validate_experiment


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample" / "my_test.json"


class ExperimentWorkflowTest(unittest.TestCase):
    def test_experiment_file_infers_metadata_and_renders_heatmap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runs_dir = temp_path / "runs"
            runs_dir.mkdir()
            for cc_algo in ["cubic", "bbrv3"]:
                shutil.copyfile(SAMPLE, runs_dir / f"{cc_algo}_rtt20_bdp1_trial1_flow{cc_algo}.json")

            config = temp_path / "experiment.yaml"
            config.write_text(
                """
name: buffer_rtt_test
time_mode: relative
default_plots: false
defaults:
  scenario: buffer_rtt_sweep
  bottleneck_mbps: 1000
inputs:
  files: runs/*.json
infer:
  filename_pattern: "{cc_algo}_rtt{rtt_ms}_bdp{buffer_bdp}_trial{trial}_flow{flow_id}.json"
plots:
  - name: throughput_heatmap
    type: heatmap
    data:
      source: flow_summary
      x: rtt_ms
      y: buffer_bdp
      value: avg_throughput_mbps
      aggregate: mean
    display:
      title: Average throughput
      x_label: RTT (ms)
      y_label: Buffer (BDP)
      legend: false
""",
                encoding="utf-8",
            )

            plan = resolve_experiment(config)
            self.assertEqual(len(plan.files), 2)
            self.assertEqual(plan.plot_specs[0]["x"], "rtt_config_ms")
            self.assertEqual(plan.metadata[plan.files[0].name]["scenario"], "buffer_rtt_sweep")

            warnings = validate_experiment(config)
            self.assertEqual(warnings, [])

            result = run_experiment(config, temp_path / "results", formats=["png"])
            self.assertTrue((result.plots_dir / "throughput_heatmap.png").exists())
            self.assertTrue((result.data_dir / "flow_intervals.csv").exists())
            self.assertTrue(result.report_path.exists())

    def test_example_experiment_validates(self) -> None:
        warnings = validate_experiment(ROOT / "examples" / "experiment.yaml")
        self.assertEqual(warnings, [])

    def test_experiment_file_infers_metadata_from_filename_regex(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runs_dir = temp_path / "runs"
            runs_dir.mkdir()
            shutil.copyfile(SAMPLE, runs_dir / "rtt_sweep_cubic_rtt20.json")
            shutil.copyfile(SAMPLE, runs_dir / "rtt_sweep_bbrv3_rtt100.json")

            config = temp_path / "experiment.yaml"
            config.write_text(
                r"""
name: regex_rtt_sweep
default_plots: false
defaults:
  scenario: rtt_sweep
  bottleneck_mbps: 1000
inputs:
  files: runs/rtt_sweep_*.json
infer:
  filename_regex: '^rtt_sweep_(?P<cc_algo>cubic|bbrv3)_rtt(?P<rtt_ms>\d+)\.json$'
plots:
  - name: throughput_vs_rtt
    type: line
    data:
      source: flow_summary
      filter: {scenario: rtt_sweep}
      x: rtt_ms
      y: avg_throughput_mbps
      group_by: cc_algo
      aggregate: mean
""",
                encoding="utf-8",
            )

            plan = resolve_experiment(config)
            self.assertEqual(len(plan.files), 2)
            metadata = plan.metadata["rtt_sweep_bbrv3_rtt100.json"]
            self.assertEqual(metadata["cc_algo"], "bbrv3")
            self.assertEqual(metadata["rtt_ms"], 100)
            self.assertEqual(plan.plot_specs[0]["x"], "rtt_config_ms")
            self.assertEqual(validate_experiment(config), [])

    def test_experiment_infer_pattern_requires_all_files_to_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runs_dir = temp_path / "runs"
            runs_dir.mkdir()
            shutil.copyfile(SAMPLE, runs_dir / "unexpected.json")

            config = temp_path / "experiment.yaml"
            config.write_text(
                """
name: bad_pattern
inputs:
  files: runs/*.json
infer:
  filename_pattern: "rtt_sweep_{cc_algo}_rtt{rtt_ms}.json"
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "did not match"):
                resolve_experiment(config)

    def test_explicit_runs_do_not_need_to_match_filename_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runs_dir = temp_path / "runs"
            runs_dir.mkdir()
            shutil.copyfile(SAMPLE, runs_dir / "rtt_sweep_cubic_rtt20.json")
            shutil.copyfile(SAMPLE, runs_dir / "weird-name.json")

            config = temp_path / "experiment.yaml"
            config.write_text(
                """
name: mixed_inputs
inputs:
  files: runs/rtt_sweep_*.json
  runs:
    - file: runs/weird-name.json
      flow_id: explicit_flow
      cc_algo: bbrv3
      rtt_ms: 80
infer:
  filename_pattern: "rtt_sweep_{cc_algo}_rtt{rtt_ms}.json"
""",
                encoding="utf-8",
            )

            plan = resolve_experiment(config)
            self.assertEqual(len(plan.files), 2)
            self.assertEqual(plan.metadata["rtt_sweep_cubic_rtt20.json"]["rtt_ms"], 20)
            self.assertEqual(plan.metadata["weird-name.json"]["flow_id"], "explicit_flow")


if __name__ == "__main__":
    unittest.main()
