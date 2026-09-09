#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "compare_performance.py"
SPEC = importlib.util.spec_from_file_location("compare_performance", SCRIPT)
COMPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPARE)


class ComparePerformanceTest(unittest.TestCase):
    def test_combines_scoped_reports_into_svg_and_table(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_dir = root / "input"
            output_dir = root / "output"
            self.write_report(
                input_dir / "generic", "rb1", "RB1", 30.5, 40
            )
            self.write_report(
                input_dir / "rb3gen2", "rb3gen2", "RB3Gen2", 30.5
            )
            self.write_report(
                input_dir / "arduino",
                "ventuno",
                "Arduino VENTUNO Q",
                40,
                10,
            )
            self.write_report(
                input_dir / "uno", "uno", "Arduino UNO Q", 35, 2
            )

            suite, container, boards = COMPARE.load_reports(input_dir)
            output_dir.mkdir()
            COMPARE.write_svg(output_dir / "comparison.svg", boards)
            COMPARE.write_summary(
                output_dir / "summary.md", suite, container, boards
            )

            svg = (output_dir / "comparison.svg").read_text(encoding="utf-8")
            summary = (output_dir / "summary.md").read_text(encoding="utf-8")
            root_element = ET.fromstring(svg)
            elements = list(root_element.iter())
            self.assertIn("TensorFlow Lite latency by board", svg)
            self.assertIn(
                "30.5 \N{PLUS-MINUS SIGN} 40.0 ms", svg
            )
            self.assertIn("Arduino UNO Q", svg)
            self.assertIn("N/A", svg)
            self.assertIn(
                "Bars: trimmed mean; whiskers: \N{PLUS-MINUS SIGN}1\u03c3 "
                "(n=8 after trimming).",
                svg,
            )
            self.assertIn(
                (
                    "| Label image | CPU | 35 ms | 40 ms | "
                    "**30.5 ms** | **30.5 ms** |"
                ),
                summary,
            )
            self.assertIn(
                "**Bold** marks the lowest measured latency in each row.",
                summary,
            )
            self.assertIn("`aabbccddeeff`", summary)

            legend_labels = self.with_role(elements, "legend-label")
            legend_swatches = self.with_role(elements, "legend-swatch")
            legend = self.with_role(elements, "legend")
            expected_names = [
                "Arduino UNO Q",
                "Arduino VENTUNO Q",
                "RB1",
                "RB3Gen2",
            ]
            self.assertEqual(
                [label.text for label in legend_labels], expected_names
            )
            self.assertEqual(len(legend), 1)
            self.assertEqual(root_element.attrib["width"], "988")
            self.assertEqual(root_element.attrib["viewBox"], "0 0 988 880")
            self.assertEqual(legend[0].attrib["x"], "494")
            self.assertEqual(legend[0].attrib["text-anchor"], "middle")
            self.assertEqual(len(legend_swatches), len(expected_names))
            self.assertNotIn("dx", legend_swatches[0].attrib)
            self.assertTrue(
                all(
                    swatch.attrib.get("dx") == "28"
                    for swatch in legend_swatches[1:]
                )
            )
            self.assertTrue(
                all(label.attrib["dx"] == "8" for label in legend_labels)
            )

            bar_labels = self.with_role(elements, "bar-label")
            self.assertEqual(len(bar_labels), len(expected_names) * 6)
            for name in expected_names:
                self.assertEqual(
                    sum(label.text == name for label in bar_labels), 6
                )
            first_panel_centers = [
                float(label.attrib["x"]) for label in bar_labels[:4]
            ]
            self.assertEqual(
                [
                    right - left
                    for left, right in zip(
                        first_panel_centers, first_panel_centers[1:]
                    )
                ],
                [COMPARE.BOARD_CENTER_SPACING] * 3,
            )
            self.assertEqual(COMPARE.BOARD_CENTER_SPACING, 104)
            axes = self.with_role(elements, "axis")
            self.assertEqual(len(axes), 6)
            self.assertGreaterEqual(
                min(float(axis.attrib["x1"]) for axis in axes), 0
            )
            self.assertLessEqual(
                max(float(axis.attrib["x2"]) for axis in axes), 988
            )

            value_labels = self.with_role(elements, "value-label")
            best_labels = [
                label
                for label in value_labels
                if label.attrib.get("font-weight") == "700"
            ]
            self.assertEqual(
                [label.text for label in best_labels],
                [
                    "30.5 \N{PLUS-MINUS SIGN} 40.0 ms",
                    "30.5 ms",
                ],
            )
            self.assertTrue(
                all(
                    label.attrib.get("font-weight") is None
                    for label in value_labels
                    if not label.text.startswith("30.5")
                )
            )
            na_labels = self.with_role(elements, "na-label")
            self.assertEqual(len(na_labels), len(expected_names) * 5)
            self.assertTrue(
                all(
                    label.attrib.get("font-weight") is None
                    for label in na_labels
                )
            )

            whiskers = self.with_role(elements, "error-whisker")
            caps = self.with_role(elements, "error-cap")
            measurement_bars = self.with_role(elements, "measurement-bar")
            self.assertEqual(len(measurement_bars), 4)
            self.assertTrue(
                all(
                    float(bar.attrib["width"])
                    == 2 * COMPARE.ERROR_CAP_HALF_WIDTH
                    for bar in measurement_bars
                )
            )
            self.assertEqual(len(whiskers), 3)
            self.assertEqual(len(caps), 6)
            self.assertTrue(
                all(
                    element.attrib["stroke-width"] == "1"
                    for element in whiskers + caps
                )
            )
            self.assertTrue(
                all(
                    float(cap.attrib["x2"]) - float(cap.attrib["x1"])
                    == float(measurement_bars[0].attrib["width"])
                    for cap in caps
                )
            )
            self.assertEqual(
                {whisker.attrib["data-board"] for whisker in whiskers},
                {"uno", "ventuno", "rb1"},
            )
            ventuno_whisker = next(
                whisker
                for whisker in whiskers
                if whisker.attrib["data-board"] == "ventuno"
            )
            rb1_whisker = next(
                whisker
                for whisker in whiskers
                if whisker.attrib["data-board"] == "rb1"
            )
            limit = COMPARE.graph_limit([37, 50, 70.5, 30.5])
            chart_top = 145 + 36
            chart_bottom = 145 + 200 - 40
            chart_height = chart_bottom - chart_top
            self.assertAlmostEqual(
                float(ventuno_whisker.attrib["y1"]),
                chart_bottom - chart_height * 50 / limit,
                places=2,
            )
            self.assertAlmostEqual(
                float(ventuno_whisker.attrib["y2"]),
                chart_bottom - chart_height * 30 / limit,
                places=2,
            )
            self.assertGreaterEqual(
                float(ventuno_whisker.attrib["y1"]), chart_top
            )
            self.assertAlmostEqual(
                float(rb1_whisker.attrib["y1"]),
                chart_bottom - chart_height * 70.5 / limit,
                places=2,
            )
            self.assertEqual(
                float(rb1_whisker.attrib["y2"]), chart_bottom
            )

    def test_chart_index_ignores_invalid_standard_deviations(self):
        standard_deviations = [2.5, 0, None, -1, "invalid", float("nan")]
        results = []
        for index, standard_deviation in enumerate(standard_deviations):
            result = {
                "workload": f"workload-{index}",
                "accelerator": "cpu",
                "result": "pass",
                "measurement": 10 + index,
                "unit": "ms",
            }
            if standard_deviation is not None:
                result["statistics"] = {
                    "trimmed_stddev": standard_deviation
                }
            results.append(result)

        indexed = COMPARE.chart_result_index({"results": results})

        self.assertEqual(
            indexed[("workload-0", "cpu")]["standard_deviation"], 2.5
        )
        self.assertEqual(
            indexed[("workload-1", "cpu")]["standard_deviation"], 0
        )
        for index in range(2, len(standard_deviations)):
            self.assertIsNone(
                indexed[(f"workload-{index}", "cpu")][
                    "standard_deviation"
                ]
            )
        self.assertEqual(
            COMPARE.result_index({"results": results})[
                ("workload-4", "cpu")
            ],
            14,
        )

    def test_formats_chart_estimates_by_mean_magnitude(self):
        self.assertEqual(
            COMPARE.format_chart_measurement(18.786, 0.65),
            "18.8 \N{PLUS-MINUS SIGN} 0.7 ms",
        )
        self.assertEqual(
            COMPARE.format_chart_measurement(0.810324, 0.034),
            "0.81 \N{PLUS-MINUS SIGN} 0.03 ms",
        )
        self.assertEqual(
            COMPARE.format_chart_measurement(0.810324, 0),
            "0.81 \N{PLUS-MINUS SIGN} 0.00 ms",
        )
        self.assertEqual(
            COMPARE.format_chart_measurement(18.786, None),
            "18.8 ms",
        )

    @staticmethod
    def with_role(elements, role):
        return [
            element
            for element in elements
            if element.attrib.get("data-role") == role
        ]

    def write_report(
        self,
        directory,
        board_id,
        board_name,
        measurement,
        standard_deviation=None,
    ):
        directory.mkdir(parents=True)
        result = {
            "workload": "label_image",
            "accelerator": "cpu",
            "result": "pass",
            "measurement": measurement,
            "unit": "ms",
        }
        if standard_deviation is not None:
            result["statistics"] = {
                "trimmed_stddev": standard_deviation
            }
        report = {
            "schema_version": 2,
            "suite": "trixie",
            "provenance": {
                "aiml_container": {
                    "sha": "aabbccddeeff00112233445566778899aabbccdd",
                    "digest": f"sha256:{'1' * 64}",
                }
            },
            "boards": [
                {
                    "id": board_id,
                    "name": board_name,
                    "results": [result],
                }
            ],
        }
        (directory / "results.json").write_text(
            json.dumps(report), encoding="utf-8"
        )


if __name__ == "__main__":
    unittest.main()
