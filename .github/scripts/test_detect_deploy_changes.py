from __future__ import annotations

import json
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from detect_deploy_changes import (  # noqa: E402
    ZERO_SHA,
    classify_changes,
    resolve_git_diff_files,
)


def test_frontend_only_push_builds_only_frontend():
    plan = classify_changes(
        ["frontend/src/components/radar/JobRadarView.tsx"],
        event_name="push",
    )
    assert plan.frontend is True
    assert plan.control_plane is False
    assert plan.stream_edge is False
    assert plan.contracts is False
    assert plan.migrations is False
    assert plan.terraform is False
    assert plan.worker_refresh is False
    assert plan.has_builds is True
    assert plan.has_deploy_work is True
    assert plan.build_matrix == [
        {
            "service": "frontend",
            "context": "frontend",
            "dockerfile": "frontend/Dockerfile",
        }
    ]


def test_contracts_change_fans_out_to_backend_and_workers():
    plan = classify_changes(
        ["packages/contracts/src/vektryn_contracts/enums.py"],
        event_name="push",
    )
    assert plan.contracts is True
    assert plan.control_plane is True
    assert plan.stream_edge is True
    assert plan.worker_refresh is True
    assert plan.frontend is False
    assert plan.migrations is False
    assert plan.terraform is False
    assert [item["service"] for item in plan.build_matrix] == [
        "control-plane",
        "stream-edge",
    ]


def test_migration_change_enables_control_plane_and_migrations():
    plan = classify_changes(
        ["services/control-plane/apps/jobs/migrations/0005_savedfilter.py"],
        event_name="push",
    )
    assert plan.control_plane is True
    assert plan.migrations is True
    assert plan.stream_edge is False
    assert plan.worker_refresh is False
    assert plan.terraform is False


def test_stream_edge_change_triggers_worker_refresh():
    plan = classify_changes(
        ["services/stream-edge/src/stream_edge/workers/matcher.py"],
        event_name="push",
    )
    assert plan.stream_edge is True
    assert plan.worker_refresh is True
    assert plan.control_plane is False
    assert plan.frontend is False
    assert plan.migrations is False


def test_terraform_only_change_skips_builds():
    plan = classify_changes(
        ["infra/terraform/modules/cloud_run/main.tf"],
        event_name="push",
    )
    assert plan.terraform is True
    assert plan.has_builds is False
    assert plan.has_deploy_work is True
    assert plan.build_matrix == []


def test_test_only_and_docs_push_short_circuits_as_noop():
    plan = classify_changes(
        [
            "README.md",
            "packages/contracts/tests/test_events.py",
            "services/control-plane/tests/test_api_and_serializers.py",
            "services/stream-edge/tests/test_workers_and_config.py",
            "frontend/src/utils/fitSummary.test.ts",
            "frontend/src/components/radar/JobRadarView.test.tsx",
        ],
        event_name="push",
    )
    assert plan.has_builds is False
    assert plan.has_deploy_work is False
    assert plan.worker_refresh is False
    assert plan.terraform is False
    assert plan.migrations is False


def test_zero_sha_push_falls_back_to_building_all_services():
    files, fallback = resolve_git_diff_files(ZERO_SHA, "HEAD")
    assert files == []
    assert fallback is True

    plan = classify_changes(files, event_name="push", fallback_all=fallback)
    assert plan.control_plane is True
    assert plan.stream_edge is True
    assert plan.frontend is True
    assert plan.worker_refresh is True
    assert plan.terraform is False
    assert plan.migrations is False


def test_workflow_dispatch_isolated_force_worker_refresh_does_not_build():
    plan = classify_changes(
        ["frontend/src/App.tsx"],
        event_name="workflow_dispatch",
        force_worker_refresh=True,
        fallback_all=True,
    )
    assert plan.worker_refresh is True
    assert plan.has_builds is False
    assert plan.has_deploy_work is True
    assert plan.control_plane is False
    assert plan.stream_edge is False
    assert plan.frontend is False
    assert plan.terraform is False
    assert plan.migrations is False


def test_workflow_dispatch_force_build_all_and_outputs_format():
    plan = classify_changes(
        [],
        event_name="workflow_dispatch",
        force_build_all=True,
        force_migrate=True,
    )
    outputs = plan.to_github_outputs(started_at=1700000000)
    assert outputs["has_builds"] == "true"
    assert outputs["has_deploy_work"] == "true"
    assert outputs["migrations"] == "true"
    assert outputs["terraform"] == "false"
    assert outputs["worker_refresh"] == "false"
    assert outputs["built_services"] == "control-plane,stream-edge,frontend"
    assert outputs["started_at"] == "1700000000"
    parsed_matrix = json.loads(outputs["build_matrix"])
    assert [entry["service"] for entry in parsed_matrix] == [
        "control-plane",
        "stream-edge",
        "frontend",
    ]
