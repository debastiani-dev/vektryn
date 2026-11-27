#!/usr/bin/env python3
"""Classify repository diffs for .github/workflows/ci.yml.

Uses only the Python standard library so the GitHub Actions `changes` job
requires zero package installations.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys

ZERO_SHA = "0" * 40


@dataclass(frozen=True)
class CiPlan:
    contracts: bool
    control_plane: bool
    stream_edge: bool
    frontend: bool

    def to_github_outputs(self) -> dict[str, str]:
        return {
            "contracts": _bool_str(self.contracts),
            "control_plane": _bool_str(self.control_plane),
            "stream_edge": _bool_str(self.stream_edge),
            "frontend": _bool_str(self.frontend),
        }


def _bool_str(value: bool) -> str:
    return "true" if value else "false"


def _all_enabled() -> CiPlan:
    return CiPlan(
        contracts=True,
        control_plane=True,
        stream_edge=True,
        frontend=True,
    )


def _is_ci_infrastructure_path(path: str) -> bool:
    return path == ".github/workflows/ci.yml" or path.startswith(".github/scripts/")


def classify_ci_changes(
    changed_files: list[str] | None,
    *,
    event_name: str,
) -> CiPlan:
    """Determine which CI jobs must run for a given event and list of changed files."""
    if event_name != "pull_request" or changed_files is None:
        return _all_enabled()

    contracts = False
    control_plane = False
    stream_edge = False
    frontend = False

    for raw_path in changed_files:
        path = raw_path.strip()
        if not path:
            continue
        if _is_ci_infrastructure_path(path):
            return _all_enabled()
        if path.startswith("packages/contracts/"):
            contracts = True
            control_plane = True
            stream_edge = True
        elif path.startswith("services/control-plane/"):
            control_plane = True
        elif path.startswith("services/stream-edge/"):
            stream_edge = True
        elif path.startswith("frontend/"):
            frontend = True

    return CiPlan(
        contracts=contracts,
        control_plane=control_plane,
        stream_edge=stream_edge,
        frontend=frontend,
    )


def list_changed_files(base_sha: str, head_sha: str) -> list[str] | None:
    """Return changed paths between base_sha and head_sha, or None on fail-safe."""
    if not base_sha or base_sha == ZERO_SHA or not head_sha:
        return None
    for diff_spec in (f"{base_sha}...{head_sha}", f"{base_sha}..{head_sha}"):
        result = subprocess.run(
            ["git", "diff", "--name-only", diff_spec],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return None


def write_github_outputs(outputs: dict[str, str]) -> None:
    output_file = os.environ.get("GITHUB_OUTPUT", "").strip()
    if not output_file:
        return
    with Path(output_file).open("a", encoding="utf-8") as fh:
        for key, value in outputs.items():
            fh.write(f"{key}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect affected CI jobs")
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--head-sha", default="")
    args = parser.parse_args(argv)

    changed_files: list[str] | None = None
    if args.event_name == "pull_request":
        changed_files = list_changed_files(args.base_sha.strip(), args.head_sha.strip())

    plan = classify_ci_changes(changed_files, event_name=args.event_name)
    outputs = plan.to_github_outputs()
    write_github_outputs(outputs)

    summary = ", ".join(f"{k}={v}" for k, v in outputs.items())
    print(f"CI change detection ({args.event_name}): {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
