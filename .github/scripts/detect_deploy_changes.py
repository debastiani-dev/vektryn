#!/usr/bin/env python3
"""Classify repository diffs and workflow_dispatch overrides for deploy-gcp.yml.

Uses only the Python standard library so the GitHub Actions `changes` job
requires zero package installations.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ZERO_SHA = "0" * 40
FRONTEND_TEST_RE = re.compile(r"^frontend/src/.*\.test\.tsx?$")
TEST_ONLY_PREFIXES = (
    "packages/contracts/tests/",
    "services/control-plane/tests/",
    "services/stream-edge/tests/",
)
CONTRACTS_RUNTIME_FILES = frozenset(
    {
        "packages/contracts/pyproject.toml",
        "packages/contracts/poetry.lock",
    }
)


@dataclass(frozen=True)
class DeployPlan:
    control_plane: bool
    stream_edge: bool
    frontend: bool
    contracts: bool
    migrations: bool
    terraform: bool
    worker_refresh: bool

    @property
    def build_matrix(self) -> list[dict[str, str]]:
        matrix: list[dict[str, str]] = []
        if self.control_plane:
            matrix.append(
                {
                    "service": "control-plane",
                    "context": ".",
                    "dockerfile": "services/control-plane/Dockerfile",
                }
            )
        if self.stream_edge:
            matrix.append(
                {
                    "service": "stream-edge",
                    "context": ".",
                    "dockerfile": "services/stream-edge/Dockerfile",
                }
            )
        if self.frontend:
            matrix.append(
                {
                    "service": "frontend",
                    "context": "frontend",
                    "dockerfile": "frontend/Dockerfile",
                }
            )
        return matrix

    @property
    def has_builds(self) -> bool:
        return bool(self.build_matrix)

    @property
    def has_deploy_work(self) -> bool:
        return (
            self.has_builds or self.terraform or self.migrations or self.worker_refresh
        )

    def to_github_outputs(self, started_at: int) -> dict[str, str]:
        matrix = self.build_matrix
        built_services = ",".join(item["service"] for item in matrix)
        return {
            "control_plane": _bool_str(self.control_plane),
            "stream_edge": _bool_str(self.stream_edge),
            "frontend": _bool_str(self.frontend),
            "contracts": _bool_str(self.contracts),
            "migrations": _bool_str(self.migrations),
            "terraform": _bool_str(self.terraform),
            "worker_refresh": _bool_str(self.worker_refresh),
            "has_builds": _bool_str(self.has_builds),
            "has_deploy_work": _bool_str(self.has_deploy_work),
            "build_matrix": json.dumps(matrix, separators=(",", ":")),
            "built_services": built_services or "none",
            "started_at": str(started_at),
        }


def _bool_str(value: bool) -> str:
    return "true" if value else "false"


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _is_ignored_test_path(path: str) -> bool:
    return path.startswith(TEST_ONLY_PREFIXES) or bool(FRONTEND_TEST_RE.match(path))


def _is_contracts_runtime_path(path: str) -> bool:
    return path.startswith("packages/contracts/src/") or path in CONTRACTS_RUNTIME_FILES


def _is_migration_path(path: str) -> bool:
    return path.startswith("services/control-plane/") and "/migrations/" in path


def _apply_changed_path(flags: dict[str, bool], raw_path: str) -> None:
    path = raw_path.strip().lstrip("./")
    if not path or _is_ignored_test_path(path):
        return
    if _is_contracts_runtime_path(path):
        flags["contracts"] = True
        flags["control_plane"] = True
        flags["stream_edge"] = True
        flags["worker_refresh"] = True
        return
    if path.startswith("services/control-plane/"):
        flags["control_plane"] = True
        if _is_migration_path(path):
            flags["migrations"] = True
        return
    if path.startswith("services/stream-edge/"):
        flags["stream_edge"] = True
        flags["worker_refresh"] = True
        return
    if path.startswith("frontend/"):
        flags["frontend"] = True
        return
    if path.startswith("infra/terraform/"):
        flags["terraform"] = True


def classify_changes(
    changed_files: list[str],
    *,
    event_name: str,
    force_build_all: bool = False,
    force_terraform: bool = False,
    force_migrate: bool = False,
    force_worker_refresh: bool = False,
    fallback_all: bool = False,
) -> DeployPlan:
    flags = {
        "control_plane": False,
        "stream_edge": False,
        "frontend": False,
        "contracts": False,
        "migrations": False,
        "terraform": False,
        "worker_refresh": False,
    }

    if event_name != "workflow_dispatch":
        if fallback_all:
            flags["control_plane"] = True
            flags["stream_edge"] = True
            flags["frontend"] = True
            flags["worker_refresh"] = True
        else:
            for raw_path in changed_files:
                _apply_changed_path(flags, raw_path)

    if force_build_all:
        flags["control_plane"] = True
        flags["stream_edge"] = True
        flags["frontend"] = True
    if force_terraform:
        flags["terraform"] = True
    if force_migrate:
        flags["migrations"] = True
    if force_worker_refresh:
        flags["worker_refresh"] = True

    return DeployPlan(**flags)


def _commit_exists(sha: str) -> bool:
    if not sha or sha == ZERO_SHA:
        return False
    res = subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return res.returncode == 0


def resolve_git_diff_files(before_sha: str, after_sha: str) -> tuple[list[str], bool]:
    """Return (changed_files, fallback_all) for a push event."""
    if not _commit_exists(before_sha) or not _commit_exists(after_sha):
        return [], True
    res = subprocess.run(
        ["git", "diff", "--name-only", before_sha, after_sha],
        check=True,
        capture_output=True,
        text=True,
    )
    files = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    return files, False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect incremental deploy targets.")
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--before", default="")
    parser.add_argument("--after", default="HEAD")
    parser.add_argument("--force-build-all", default="false")
    parser.add_argument("--force-terraform", default="false")
    parser.add_argument("--force-migrate", default="false")
    parser.add_argument("--force-worker-refresh", default="false")
    args = parser.parse_args(argv)

    changed_files: list[str] = []
    fallback_all = False
    if args.event_name != "workflow_dispatch":
        changed_files, fallback_all = resolve_git_diff_files(args.before, args.after)

    plan = classify_changes(
        changed_files,
        event_name=args.event_name,
        force_build_all=_parse_bool(args.force_build_all),
        force_terraform=_parse_bool(args.force_terraform),
        force_migrate=_parse_bool(args.force_migrate),
        force_worker_refresh=_parse_bool(args.force_worker_refresh),
        fallback_all=fallback_all,
    )

    outputs = plan.to_github_outputs(started_at=int(time.time()))
    github_output = os.environ.get("GITHUB_OUTPUT", "").strip()
    lines = [f"{key}={value}" for key, value in outputs.items()]

    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))

    return 0


if __name__ == "__main__":
    sys.exit(main())
