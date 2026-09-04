#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_JUNIT_BYTES = 10 * 1024 * 1024


class UnsafeJUnitError(ValueError):
    pass


def count_aiml_tests(path):
    if path.stat().st_size > MAX_JUNIT_BYTES:
        raise UnsafeJUnitError(
            f"JUnit report exceeds the {MAX_JUNIT_BYTES}-byte size limit"
        )

    document = path.read_text(encoding="utf-8")
    upper_document = document.upper()
    if "<!DOCTYPE" in upper_document or "<!ENTITY" in upper_document:
        raise UnsafeJUnitError("DTD and entity declarations are not allowed")

    # The size and declaration checks above prevent external entities and XML bombs.
    root = ET.fromstring(document)  # nosemgrep
    return sum(
        1
        for suite in root.iter("testsuite")
        if suite.get("name", "").endswith("aiml-container-smoke")
        for test_case in suite.iter("testcase")
        if test_case.get("name", "").startswith("tflite-")
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Verify that a LAVA JUnit report contains AIML tests"
    )
    parser.add_argument("junit", type=Path)
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        count = count_aiml_tests(args.junit)
    except (OSError, UnicodeError, ET.ParseError, UnsafeJUnitError) as error:
        raise SystemExit(f"cannot read LAVA results from {args.junit}: {error}")
    if count == 0:
        raise SystemExit(
            f"AIML tests did not run: no TensorFlow Lite cases in {args.junit}"
        )
    print(f"Found {count} TensorFlow Lite test cases in {args.junit}")


if __name__ == "__main__":
    main()
