#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Technologies, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

import argparse
import json
from pathlib import Path

PAYLOAD_NAME = "lava-execution-status.json"


class StatusArtifactValidationError(ValueError):
    pass


def expected_statuses(scope_spec):
    if not isinstance(scope_spec, dict):
        raise StatusArtifactValidationError("scope matrix entry must be an object")

    scope = scope_spec.get("scope")
    boards = scope_spec.get("boards")
    statuses = scope_spec.get("expected_statuses")
    if not isinstance(scope, str) or not scope:
        raise StatusArtifactValidationError("scope matrix entry has an invalid scope")
    if not isinstance(boards, list) or not all(
        isinstance(board, str) and board for board in boards
    ):
        raise StatusArtifactValidationError(
            f"scope matrix {scope!r} has invalid selected boards"
        )
    if len(set(boards)) != len(boards):
        raise StatusArtifactValidationError(
            f"scope matrix {scope!r} has duplicate selected boards"
        )
    if not isinstance(statuses, list):
        raise StatusArtifactValidationError(
            f"scope matrix {scope!r} has no expected statuses"
        )

    by_slug = {}
    by_board = {}
    for entry in statuses:
        if not isinstance(entry, dict):
            raise StatusArtifactValidationError(
                f"scope matrix {scope!r} has a non-object expected status"
            )
        board = entry.get("board")
        slug = entry.get("slug")
        if not isinstance(board, str) or not board:
            raise StatusArtifactValidationError(
                f"scope matrix {scope!r} has an expected status with no board"
            )
        if not isinstance(slug, str) or not slug:
            raise StatusArtifactValidationError(
                f"scope matrix {scope!r} has an expected status with no slug"
            )
        if board in by_board:
            raise StatusArtifactValidationError(
                f"scope matrix {scope!r} maps board {board!r} more than once"
            )
        if slug in by_slug:
            raise StatusArtifactValidationError(
                f"scope matrix {scope!r} maps slug {slug!r} more than once"
            )
        by_slug[slug] = {"board": board, "slug": slug}
        by_board[board] = slug

    if set(by_board) != set(boards):
        raise StatusArtifactValidationError(
            f"scope matrix {scope!r} status mappings do not match selected boards"
        )
    return scope, by_slug


def _payload_fields(payload, display_path, diagnostics):
    if not isinstance(payload, dict):
        diagnostics.append(f"{display_path}: payload is not a JSON object")
        return None

    fields = {}
    for field in ("scope", "board", "slug", "status"):
        value = payload.get(field)
        if not isinstance(value, str) or not value:
            diagnostics.append(
                f"{display_path}: payload has an invalid {field!r} field"
            )
            return None
        fields[field] = value
    return fields


def validate_status_artifacts(artifacts_dir, suite, scope_spec):
    if not isinstance(suite, str) or not suite:
        raise StatusArtifactValidationError("suite must be a non-empty string")

    scope, expected_by_slug = expected_statuses(scope_spec)
    artifacts_dir = Path(artifacts_dir)
    artifact_prefix = f"lava-execution-status-{suite}-{scope}-"
    diagnostics = []
    seen = {}

    if not artifacts_dir.is_dir():
        diagnostics.append(
            f"status artifact directory does not exist: {artifacts_dir}"
        )
    else:
        for payload_path in sorted(artifacts_dir.rglob(PAYLOAD_NAME)):
            artifact_name = payload_path.parent.name
            if not artifact_name.startswith(artifact_prefix):
                continue

            display_path = str(payload_path.relative_to(artifacts_dir))
            artifact_slug = artifact_name.removeprefix(artifact_prefix)
            if not artifact_slug:
                diagnostics.append(
                    f"{display_path}: status artifact directory has no slug"
                )
                continue
            expected_from_artifact = expected_by_slug.get(artifact_slug)
            if expected_from_artifact is None:
                diagnostics.append(
                    f"{display_path}: unexpected status artifact slug "
                    f"{artifact_slug!r}"
                )

            try:
                payload = json.loads(payload_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                diagnostics.append(
                    f"{display_path}: cannot read JSON payload: {error}"
                )
                continue

            fields = _payload_fields(payload, display_path, diagnostics)
            if fields is None:
                continue

            valid_mapping = expected_from_artifact is not None
            if fields["scope"] != scope:
                diagnostics.append(
                    f"{display_path}: wrong scope {fields['scope']!r}; "
                    f"expected {scope!r}"
                )
                valid_mapping = False
            if fields["slug"] != artifact_slug:
                diagnostics.append(
                    f"{display_path}: wrong slug {fields['slug']!r}; "
                    f"artifact declares {artifact_slug!r}"
                )
                valid_mapping = False

            expected = expected_by_slug.get(fields["slug"])
            if expected is None:
                diagnostics.append(
                    f"{display_path}: unexpected payload slug "
                    f"{fields['slug']!r}"
                )
                valid_mapping = False
            elif fields["board"] != expected["board"]:
                diagnostics.append(
                    f"{display_path}: wrong board {fields['board']!r} for "
                    f"slug {fields['slug']!r}; expected {expected['board']!r}"
                )
                valid_mapping = False

            if valid_mapping:
                key = (fields["board"], fields["slug"])
                if key in seen:
                    diagnostics.append(
                        f"{display_path}: duplicate status mapping for board "
                        f"{fields['board']!r} and slug {fields['slug']!r}; "
                        f"already found at {seen[key]}"
                    )
                else:
                    seen[key] = display_path

            if fields["status"] != "success":
                diagnostics.append(
                    f"{display_path}: board {fields['board']!r} reported "
                    f"status {fields['status']!r}"
                )

    for expected in expected_by_slug.values():
        key = (expected["board"], expected["slug"])
        if key not in seen:
            diagnostics.append(
                f"missing execution status for board {expected['board']!r} "
                f"and slug {expected['slug']!r}"
            )

    return {
        "complete": not diagnostics,
        "diagnostics": diagnostics,
        "expected_status_count": len(expected_by_slug),
        "status_count": len(seen),
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Validate downloaded LAVA execution status artifacts"
    )
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--suite", required=True)
    parser.add_argument(
        "--scope-spec",
        required=True,
        help="JSON scope entry from the LAVA scope matrix",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        scope_spec = json.loads(args.scope_spec)
        result = validate_status_artifacts(
            args.artifacts_dir, args.suite, scope_spec
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        StatusArtifactValidationError,
    ) as error:
        raise SystemExit(f"cannot validate LAVA execution statuses: {error}")


if __name__ == "__main__":
    main()
