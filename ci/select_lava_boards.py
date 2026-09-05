#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import argparse
import json
import re
import sys
from pathlib import Path

BOARD_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]*")
DEVICE_TYPE_PATTERN = re.compile(
    r"^device_type:\s*['\"]?([a-z0-9][a-z0-9-]*)['\"]?\s*$",
    re.MULTILINE,
)


def load_boards(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError(f"unsupported boards schema in {path}")
    boards = data.get("boards")
    if not isinstance(boards, dict) or not boards:
        raise ValueError(f"no boards configured in {path}")

    device_types = set()
    for board_id, board in boards.items():
        if BOARD_ID_PATTERN.fullmatch(board_id) is None:
            raise ValueError(f"invalid board ID in {path}: {board_id}")
        if not isinstance(board.get("display_name"), str) or not board["display_name"]:
            raise ValueError(f"board {board_id} has no display name")
        if BOARD_ID_PATTERN.fullmatch(board.get("image_source", "")) is None:
            raise ValueError(f"board {board_id} has an invalid image source")
        configured_types = board.get("device_types")
        if not isinstance(configured_types, list) or not configured_types:
            raise ValueError(f"board {board_id} has no LAVA device types")
        for device_type in configured_types:
            if (
                not isinstance(device_type, str)
                or BOARD_ID_PATTERN.fullmatch(device_type) is None
            ):
                raise ValueError(
                    f"board {board_id} has an invalid LAVA device type"
                )
            if device_type in device_types:
                raise ValueError(f"duplicate LAVA device type: {device_type}")
            device_types.add(device_type)
    return boards


def validate_templates(boards, lava_dir):
    template_boards = {}
    for template in sorted(lava_dir.glob("*/*.yaml")):
        board_id = template.parent.name
        matches = DEVICE_TYPE_PATTERN.findall(
            template.read_text(encoding="utf-8")
        )
        if len(matches) != 1:
            raise ValueError(
                f"{template} must declare exactly one LAVA device_type"
            )
        template_boards.setdefault(board_id, set()).add(matches[0])

    missing = sorted(set(boards) - set(template_boards))
    unknown = sorted(set(template_boards) - set(boards))
    if missing:
        raise ValueError(f"boards have no LAVA template: {', '.join(missing)}")
    if unknown:
        raise ValueError(
            f"LAVA templates have no board metadata: {', '.join(unknown)}"
        )

    for board_id, template_types in template_boards.items():
        configured_types = set(boards[board_id]["device_types"])
        unexpected = sorted(template_types - configured_types)
        if unexpected:
            raise ValueError(
                f"board {board_id} templates use unconfigured device types: "
                f"{', '.join(unexpected)}"
            )


def parse_include(value):
    if not value:
        return []
    try:
        include = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("boards_include must be valid JSON") from error
    if not isinstance(include, list) or not all(
        isinstance(board_id, str) for board_id in include
    ):
        raise ValueError("boards_include must be a JSON array of board IDs")
    if len(include) != len(set(include)):
        raise ValueError("boards_include must not contain duplicate board IDs")
    return include


def select_boards(boards, image_source, include):
    requested = parse_include(include)
    if not requested:
        requested = [
            board_id
            for board_id, board in boards.items()
            if board["image_source"] == image_source
        ]

    unknown = sorted(set(requested) - set(boards))
    if unknown:
        raise ValueError(f"unknown boards requested: {', '.join(unknown)}")

    mismatched = [
        board_id
        for board_id in requested
        if boards[board_id]["image_source"] != image_source
    ]
    if mismatched:
        raise ValueError(
            f"boards do not use the {image_source} image source: "
            f"{', '.join(mismatched)}"
        )
    if not requested:
        raise ValueError(f"no boards use the {image_source} image source")
    return requested


def parse_args():
    parser = argparse.ArgumentParser(
        description="Validate and select LAVA boards for a qcom image source"
    )
    parser.add_argument("--boards", type=Path, required=True)
    parser.add_argument("--lava-dir", type=Path, required=True)
    parser.add_argument("--image-source", required=True)
    parser.add_argument("--include", default="")
    parser.add_argument("--github-output", type=Path)
    return parser.parse_args()


def main():
    args = parse_args()
    boards = load_boards(args.boards)
    validate_templates(boards, args.lava_dir)
    selected = select_boards(boards, args.image_source, args.include)
    encoded = json.dumps(selected, separators=(",", ":"))
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"boards={encoded}\n")
    else:
        print(encoded)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(f"::error::{error}", file=sys.stderr)
        raise SystemExit(1)
