from __future__ import annotations

from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from detect_ci_changes import CiPlan, classify_ci_changes  # noqa: E402


def test_frontend_only_pr_runs_only_frontend():
    plan = classify_ci_changes(
        ["frontend/src/components/layout/AuthenticatedWorkspace.tsx"],
        event_name="pull_request",
    )
    assert plan == CiPlan(
        contracts=False,
        control_plane=False,
        stream_edge=False,
        frontend=True,
    )


def test_control_plane_only_pr_runs_only_control_plane():
    plan = classify_ci_changes(
        ["services/control-plane/apps/base/services/byok.py"],
        event_name="pull_request",
    )
    assert plan == CiPlan(
        contracts=False,
        control_plane=True,
        stream_edge=False,
        frontend=False,
    )


def test_contracts_change_fans_out_to_all_python_services():
    plan = classify_ci_changes(
        ["packages/contracts/src/vektryn_contracts/gemini_policy.py"],
        event_name="pull_request",
    )
    assert plan == CiPlan(
        contracts=True,
        control_plane=True,
        stream_edge=True,
        frontend=False,
    )


def test_ci_workflow_or_scripts_change_runs_all_jobs():
    for path in (
        ".github/workflows/ci.yml",
        ".github/scripts/detect_ci_changes.py",
    ):
        plan = classify_ci_changes([path], event_name="pull_request")
        assert plan == CiPlan(
            contracts=True,
            control_plane=True,
            stream_edge=True,
            frontend=True,
        )


def test_push_to_main_and_unknown_diff_always_run_all_jobs():
    assert classify_ci_changes(["frontend/src/App.tsx"], event_name="push") == CiPlan(
        contracts=True,
        control_plane=True,
        stream_edge=True,
        frontend=True,
    )
    assert classify_ci_changes(None, event_name="pull_request") == CiPlan(
        contracts=True,
        control_plane=True,
        stream_edge=True,
        frontend=True,
    )


def test_docs_only_pr_skips_all_service_jobs():
    plan = classify_ci_changes(
        ["README.md", "infra/terraform/modules/iam/main.tf"],
        event_name="pull_request",
    )
    assert plan == CiPlan(
        contracts=False,
        control_plane=False,
        stream_edge=False,
        frontend=False,
    )
