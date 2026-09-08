#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import argparse
import json
from pathlib import Path

from report_lava_results import reports_are_semantically_compatible


def parse_args():
    parser = argparse.ArgumentParser(
        description="Check whether a previous LAVA performance report is compatible"
    )
    parser.add_argument("--current-results", type=Path, required=True)
    parser.add_argument("--candidate-results", type=Path, required=True)
    return parser.parse_args()


def load_report(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    args = parse_args()
    current = load_report(args.current_results)
    candidate = load_report(args.candidate_results)
    if not reports_are_semantically_compatible(current, candidate):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
