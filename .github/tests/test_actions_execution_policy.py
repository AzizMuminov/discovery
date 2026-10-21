"""Contracts for the narrowly scoped pull_request_target policy exception."""

import json
from pathlib import Path
import re

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / ".github" / "policy" / "actions-execution.json"
WORKFLOWS = {
    ".github/workflows/auto-merge-on-approval.yml",
    ".github/workflows/check-agent-removal-impact.yml",
    ".github/workflows/pr-review.yml",
}


def load_workflow(path: str) -> dict:
    return yaml.load((ROOT / path).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_policy_is_an_explicit_active_event_exception():
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    assert set(policy) == {"name", "enforcement", "conditions", "rules"}
    assert policy["name"] == "Reviewed pull request automation"
    assert policy["enforcement"] == "active"
    assert set(policy["conditions"]) == {"workflow_path"}
    targeting = policy["conditions"]["workflow_path"]
    assert set(targeting) == {"include", "exclude"}
    assert len(targeting["include"]) == len(WORKFLOWS)
    assert set(targeting["include"]) == WORKFLOWS
    assert targeting["exclude"] == []
    assert policy["rules"] == [{
        "type": "restrict_action_events",
        "parameters": {
            "allowed_events": ["pull_request_target", "pull_request_review"],
        },
    }]


def test_every_target_workflow_is_reviewed_and_covered():
    target_workflows = set()
    for path in (ROOT / ".github" / "workflows").iterdir():
        if path.suffix not in {".yml", ".yaml"}:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if "pull_request_target" in load_workflow(relative)["on"]:
            target_workflows.add(relative)

    assert target_workflows == WORKFLOWS


def test_policy_preserves_all_configured_events_without_extra_events():
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    configured_events = set()
    allowed_events = set(policy["rules"][0]["parameters"]["allowed_events"])
    for path in WORKFLOWS:
        events = set(load_workflow(path)["on"])
        assert events <= allowed_events, path
        configured_events.update(events)

    assert allowed_events == configured_events


@pytest.mark.parametrize("path", sorted(WORKFLOWS))
def test_target_workflows_use_pinned_actions_and_ephemeral_runners(path):
    workflow = load_workflow(path)
    assert "write-all" not in workflow.get("permissions", {})
    for job in workflow["jobs"].values():
        assert job["runs-on"] in {"ubuntu-latest", "ubuntu-slim"}
        assert 0 < int(job["timeout-minutes"]) <= 20
        assert "write-all" not in job.get("permissions", {})
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", step["uses"])


@pytest.mark.parametrize("path", [
    ".github/workflows/check-agent-removal-impact.yml",
    ".github/workflows/pr-review.yml",
])
def test_data_checkouts_are_isolated_from_trusted_code_and_credentials(path):
    workflow = load_workflow(path)
    checkouts = [
        step["with"]
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/checkout@")
    ]
    assert len(checkouts) == 2
    trusted = next(checkout for checkout in checkouts if checkout["path"] == "trusted")
    untrusted = next(checkout for checkout in checkouts if checkout["path"] == "pr")

    assert all(checkout["persist-credentials"] == "false" for checkout in checkouts)
    assert trusted["ref"] == "${{ github.event.pull_request.base.sha }}"
    assert "allow-unsafe-pr-checkout" not in trusted
    assert untrusted["repository"] == (
        "${{ github.event.pull_request.head.repo.full_name }}"
    )
    assert untrusted["ref"] == "${{ github.event.pull_request.head.sha }}"
    assert untrusted["allow-unsafe-pr-checkout"] == "true"


def test_auto_merge_never_checks_out_or_runs_pr_code():
    workflow = load_workflow(".github/workflows/auto-merge-on-approval.yml")
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            assert not step.get("uses", "").startswith("actions/checkout@")
            assert "gh pr checkout" not in step.get("run", "")
            assert "git fetch" not in step.get("run", "")


def test_required_checks_are_not_filtered_out_by_changed_paths():
    for path in (
        ".github/workflows/check-agent-removal-impact.yml",
        ".github/workflows/pr-review.yml",
    ):
        event = load_workflow(path)["on"]["pull_request_target"] or {}
        assert "paths" not in event
        assert "paths-ignore" not in event
