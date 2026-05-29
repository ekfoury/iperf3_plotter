import json
from pathlib import Path
import shutil
import tempfile
import unittest

from iperf3_plotter.metrics import choose_time_column
from iperf3_plotter.metrics import (
    fairness_over_time,
    flow_aggregates,
    interval_summary,
    jain_fairness,
    resample_time_bins,
    series_similarity,
)
from iperf3_plotter.parser import parse_files


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample" / "my_test.json"


class ParserMetricsTest(unittest.TestCase):
    def test_parse_sample_intervals(self) -> None:
        intervals, summaries, runs = parse_files([SAMPLE])

        self.assertEqual(len(intervals), 240)
        self.assertEqual(intervals["stream_id"].nunique(), 4)
        self.assertEqual(intervals["flow_id"].nunique(), 1)
        self.assertEqual(runs.iloc[0]["protocol"], "TCP")
        self.assertFalse(summaries.empty)

    def test_flow_aggregate_sums_parallel_streams(self) -> None:
        intervals, _summaries, _runs = parse_files([SAMPLE])
        flows = flow_aggregates(intervals)
        first_interval = intervals[intervals["interval_index"] == 0]

        self.assertEqual(len(flows), 60)
        self.assertAlmostEqual(
            flows.iloc[0]["throughput_mbps"],
            first_interval["throughput_mbps"].sum(),
            places=6,
        )
        self.assertAlmostEqual(flows.iloc[0]["rtt_ms"], first_interval["rtt_ms"].mean(), places=6)
        self.assertAlmostEqual(flows.iloc[0]["cwnd_kib"], first_interval["cwnd_kib"].max(), places=6)
        self.assertAlmostEqual(flows.iloc[0]["retransmits"], first_interval["retransmits"].sum(), places=6)

    def test_jain_fairness(self) -> None:
        self.assertAlmostEqual(jain_fairness([10, 10, 10]), 1.0)
        self.assertAlmostEqual(jain_fairness([1, 3]), 0.8)

    def test_interval_summary(self) -> None:
        intervals, _summaries, _runs = parse_files([SAMPLE])
        summary = interval_summary(intervals, "stream_id")

        self.assertEqual(len(summary), 4)
        self.assertTrue((summary["avg_throughput_mbps"] > 0).all())

    def test_manifest_metadata_and_start_offset(self) -> None:
        metadata = {
            SAMPLE.name: {
                "flow_id": "cubic-flow",
                "label": "CUBIC baseline",
                "cc_algo": "cubic",
                "start_offset_s": 10,
                "rtt_ms": 40,
            }
        }
        intervals, _summaries, runs = parse_files([SAMPLE], metadata)

        self.assertEqual(intervals.iloc[0]["flow_id"], "cubic-flow")
        self.assertEqual(intervals.iloc[0]["cc_algo"], "cubic")
        self.assertEqual(intervals.iloc[0]["offset_start_s"], 10)
        self.assertEqual(runs.iloc[0]["flow_label"], "CUBIC baseline")
        self.assertEqual(runs.iloc[0]["rtt_config_ms"], 40)

    def test_series_similarity_detects_exact_overlap(self) -> None:
        intervals, _summaries, _runs = parse_files([SAMPLE])
        similarity = series_similarity(intervals)

        pmtu = similarity[similarity["metric"].eq("pmtu_bytes")]
        self.assertTrue(pmtu["exact_equal"].all())
        cwnd = similarity[
            similarity["metric"].eq("cwnd_kib")
            & similarity["left"].str.endswith("stream-3")
            & similarity["right"].str.endswith("stream-4")
        ]
        self.assertTrue(cwnd.iloc[0]["exact_equal"])

    def test_global_time_aligns_multiple_client_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            flow1 = Path(temp_dir) / "flow1.json"
            flow2 = Path(temp_dir) / "flow2.json"
            shutil.copyfile(SAMPLE, flow1)
            shutil.copyfile(SAMPLE, flow2)
            metadata = {
                flow1.name: {"flow_id": "flow1", "start_offset_s": 0},
                flow2.name: {"flow_id": "flow2", "start_offset_s": 5},
            }

            intervals, _summaries, _runs = parse_files([flow1, flow2], metadata)
            # The sample JSON files have identical embedded timestamps, so global
            # mode uses timestamps first; offset mode keeps the manual 5 s gap.
            self.assertEqual(choose_time_column(intervals, "offset"), "offset_start_s")
            starts = intervals.groupby("flow_id")["offset_start_s"].min()
            self.assertEqual(starts["flow1"], 0)
            self.assertEqual(starts["flow2"], 5)

    def test_global_time_uses_iperf_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            flow1 = Path(temp_dir) / "flow1.json"
            flow2 = Path(temp_dir) / "flow2.json"
            data = SAMPLE.read_text(encoding="utf-8")
            flow1.write_text(data, encoding="utf-8")
            flow2_data = json.loads(data)
            flow2_data["start"]["timestamp"]["timesecs"] += 5
            flow2.write_text(json.dumps(flow2_data), encoding="utf-8")

            intervals, _summaries, _runs = parse_files([flow1, flow2])
            self.assertEqual(choose_time_column(intervals, "global"), "global_start_s")
            starts = intervals.groupby("flow_id")["global_start_s"].min()
            self.assertEqual(starts["flow1"], 0)
            self.assertEqual(starts["flow2"], 5)

    def test_resampled_fairness_counts_overlapping_offset_flows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            flow1 = Path(temp_dir) / "flow1.json"
            flow2 = Path(temp_dir) / "flow2.json"
            shutil.copyfile(SAMPLE, flow1)
            shutil.copyfile(SAMPLE, flow2)
            metadata = {
                flow1.name: {"flow_id": "flow1", "start_offset_s": 0},
                flow2.name: {"flow_id": "flow2", "start_offset_s": 5},
            }

            intervals, _summaries, _runs = parse_files([flow1, flow2], metadata)
            flow_bins = resample_time_bins(flow_aggregates(intervals), entity_col="flow_id", time_mode="offset")
            fairness = fairness_over_time(flow_bins, "flow_id", "time_bin_start_s")
            overlap = fairness[fairness["time_bin_start_s"].eq(5.0)]

            self.assertEqual(overlap.iloc[0]["active_entities"], 2)
            self.assertGreater(overlap.iloc[0]["total_throughput_mbps"], 0)


if __name__ == "__main__":
    unittest.main()
