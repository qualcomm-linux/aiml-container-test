#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import argparse
import json
import re
import sys
from pathlib import Path

from select_lava_boards import load_boards, parse_include, select_boards


IMAGE_SOURCES = ("generic", "arduino")


def route_inputs(boards, image_source, run_id, include):
    if image_source not in (*IMAGE_SOURCES, "all"):
        raise ValueError(f"unsupported image_source: {image_source}")
    if run_id and re.fullmatch(r"[1-9][0-9]*", run_id) is None:
        raise ValueError("qcom_build_run_id must be a positive decimal run ID")
    if image_source == "all" and run_id:
        raise ValueError(
            "qcom_build_run_id cannot be used with image_source=all; "
            "each image family has an independent producer run"
        )

    requested = parse_include(include)
    unknown = sorted(set(requested) - set(boards))
    if unknown:
        raise ValueError(f"unknown boards requested: {', '.join(unknown)}")

    if image_source == "all":
        selected = requested or list(boards)
    else:
        selected = select_boards(boards, image_source, include)

    unroutable = [
        board_id
        for board_id in selected
        if boards[board_id]["image_source"] not in IMAGE_SOURCES
    ]
    if unroutable:
        raise ValueError(
            "boards use an unsupported image source: "
            f"{', '.join(unroutable)}"
        )

    routed = {
        source: [
            board_id
            for board_id in selected
            if boards[board_id]["image_source"] == source
        ]
        for source in IMAGE_SOURCES
    }
    return {
        **{
            f"{source}_boards": json.dumps(
                routed[source], separators=(",", ":")
            )
            for source in IMAGE_SOURCES
        },
        **{
            f"{source}_enabled": str(bool(routed[source])).lower()
            for source in IMAGE_SOURCES
        },
        **{
            f"{source}_run_id": run_id if image_source == source else ""
            for source in IMAGE_SOURCES
        },
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Validate and partition Daily Build inputs by image family"
    )
    parser.add_argument("--boards", type=Path, required=True)
    parser.add_argument("--image-source", required=True)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--include", default="")
    parser.add_argument("--github-output", type=Path)
    return parser.parse_args()


def main():
    args = parse_args()
    outputs = route_inputs(
        load_boards(args.boards),
        args.image_source,
        args.run_id,
        args.include,
    )
    rendered = "".join(f"{key}={value}\n" for key, value in outputs.items())
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(f"::error::{error}", file=sys.stderr)
        raise SystemExit(1)
