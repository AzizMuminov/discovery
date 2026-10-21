# Actions execution policy: remediation and rollout plan

## Problem and acceptance criteria

GitHub will enforce its default block on `pull_request_target` in affected public
repositories on **November 2, 2026**. This is an execution-policy change, not a
workflow syntax error. SHA-pinning actions, setting token permissions, or adding
`allow-unsafe-pr-checkout` does not exempt a workflow from the event policy.

Discovery still uses this event for the three workflows below. Blocking them
would stop PR feedback, agent-removal checks, and native auto-merge configuration.
Several job names are required branch-protection checks, so blocked runs can
leave PRs waiting indefinitely rather than reporting a failed check.

The remediation is an explicit event-policy exception scoped to these three
reviewed workflow files. Other workflows remain outside this exception. It does
not change branch protection, required checks, approval rules, or token scopes.

**A merged JSON file does not configure GitHub.** Completion requires an
administrator to apply the policy and verify actual policy insights and PR runs.
Do not mark the operational rollout complete based only on passing unit tests.

Acceptance criteria:

- The effective policy allows the three workflows' existing events.
- No wildcard, repository-wide event exception, actor restriction, or new event
  is introduced by this exception.
- Required checks still report for ordinary, catalog, same-repository, and fork
  PRs, including failing validation and agent-removal cases.
- Secrets and write tokens are not introduced into PR-data validation jobs.
- The policy's identity, applied payload, insights, and canary run URLs are
  recorded in the rollout PR or change record.

## Workflow review and decision

| Workflow | Why retain the base-branch event | Trust boundary and residual risk |
| --- | --- | --- |
| [PR Review](../.github/workflows/pr-review.yml) | Runs base-branch validators against PR data; posts labels, reviews, and comments for fork PRs. | Classification and validation default to read-only tokens. Only the separate reporting job gets PR/issue write access. The base checkout supplies scripts and dependency constraints; PR files are isolated in a second checkout and must never be executed. Parsing untrusted files and network-backed checks remains a risk requiring maintained dependencies and ephemeral runners. |
| [Check Agent Removal Impact](../.github/workflows/check-agent-removal-impact.yml) | Runs the trusted removal gate and posts PR diagnostics; preserves the existing required check. | Both checkout credentials are disabled, code comes from the base SHA, and the PR SHA is scanned as data. This job still has PR write permission to post diagnostics while parsing PR data; separating reporting is a possible future hardening, not a prerequisite for the event-policy exception. |
| [Enable Native Auto-merge](../.github/workflows/auto-merge-on-approval.yml) | Enables native auto-merge and provides the existing narrow, Microsoft-member release-manifest approval exception. | No checkout or PR code execution. A short-lived App token supplies the manifest approval; GitHub's required checks and review rules remain authoritative. Preserve `pull_request_review` as well as `pull_request_target`. |

Do not mechanically replace `pull_request_target` with `pull_request`:
fork PR tokens would lose write access and secrets, and validation workflow code
would come from a different trust context. A migration to read-only validation
plus privileged `workflow_run` reporting is possible, but needs a separate design
for source-run provenance, head-SHA freshness, hostile artifacts, and required
check attribution. It is not necessary to resolve this policy deadline.

The current `allow-unsafe-pr-checkout: true` inputs are explicit checkout
exceptions, **not** policy exceptions. Keep them confined to the data checkout,
with immutable head SHAs and `persist-credentials: false`. Never install from a
PR requirements file, invoke a PR script, restore a PR-controlled executable
cache, or expose an App token to a parsing job.

## Phase 1: inventory and preflight

An administrator should review **Settings > Actions > Policy insights** and
**Settings > Actions > Policies**, including inherited organization and enterprise
policies. The repository policy cannot override an explicit inherited denial.
Resolve such a denial with the policy owner rather than relaxing other rules.

Use an authenticated GitHub CLI with repository administration permission.
These commands use PowerShell from the repository root; API paths use GitHub's
URL syntax.

```powershell
gh auth status --hostname github.com
gh api -H "X-GitHub-Api-Version: 2026-03-10" `
  "repos/microsoft/discovery/actions/policies?has_parents=true&per_page=100" `
  --paginate --slurp
gh api repos/microsoft/discovery/branches/main/protection/required_status_checks
```

At initial investigation on October 19, 2026, the repository was public, all
three workflows were active, and the policies API returned no configured
policies, even with `has_parents=true`. That response is **not proof that the
built-in default protection is absent**; verify it in Policy insights.

If the named policy already exists, read and save its current payload before
updating it. Do not blindly POST another copy or modify an inherited policy.
Preserve unrelated actor, event, action-pinning, and lockfile protections.

## Phase 2: review and apply the narrow exception

The reviewed API payload is
[actions-execution.json](../.github/policy/actions-execution.json). It targets
three literal workflow paths and permits only the union of their existing
events: `pull_request_target` and `pull_request_review`. The latter is used only
by auto-merge today; an event policy permits events but does not add triggers.
No actor allowlist is added: restricting actors to maintainers would prevent
external contributors from triggering the required PR checks.

After review, an administrator can create the policy:

```powershell
gh api --method POST -H "X-GitHub-Api-Version: 2026-03-10" `
  repos/microsoft/discovery/actions/policies `
  --input .github\policy\actions-execution.json
```

Record the returned policy ID and response. For an existing repository-owned
policy, use `--method PUT` with
`repos/microsoft/discovery/actions/policies/POLICY_ID` only after comparing its
saved payload with the reviewed replacement. The payload is a complete
replacement for the named policy, not a merge with additional rules.

The checked-in payload uses `active` intentionally. Evaluate mode can help
inspect restrictions, but is not an acceptance test for an enforced exception.
If trialling in evaluate mode, follow with an approved active policy and repeat
the checks below. GitHub applies all applicable restrictions together; a second
policy cannot loosen an existing explicit event denial.

Read the policy back and compare its name, enforcement, literal paths, and
allowed events with the file. Reopen Policy insights and confirm the built-in
default no longer blocks these workflows. Do not disable protections globally.

## Phase 3: validation and critical review

Run the policy contracts together with the existing workflow, schema, removal,
and release regression tests:

```powershell
python -m pytest .github\tests\test_actions_execution_policy.py `
  .github\tests\test_pr_review_workflow_security.py `
  .github\tests\test_check_agent_removal_impact.py `
  .github\tests\test_security_automation.py `
  .github\tests\test_schema_security.py `
  .github\tests\test_release_fastlane.py -q
python -m pytest .github\tests\ -q -ra -n auto --dist worksteal
python .github\scripts\validate_starter_kits.py --repo-root .
git --no-pager diff --check
```

On Windows, use a UTF-8 Python console (`$env:PYTHONUTF8 = "1"`) and put Git's
`usr\bin` directory on PATH so the content-sniffing tests can find `file.exe`.
Linux CI remains authoritative for embedded Bash workflow execution.
Use [Validate Everything](validation-workflow-testing.md) for full-catalog and
Linux unit-test runs against the candidate branch.

The policy tests reject added or renamed target workflows without a matching
reviewed policy update, broad workflow targeting, lost review-event coverage,
mutable action refs, credential persistence, and changed-path filters that
would strand required checks. They inspect configuration; they do not prove
that arbitrary PR content cannot exploit a parser or that GitHub settings have
been applied. Review those boundaries separately.

Before activating the exception, a maintainer should critically review:

1. Every command and action that can run after the PR data checkout. Confirm
   executable code, imports, requirements, configuration, and working directories
   remain trusted, not merely that checkout credentials are disabled.
2. Every write token and secret. Confirm PR parsing jobs cannot obtain approval
   App credentials; auto-merge must not fetch or execute PR code.
3. Failure paths. Missing validation results must not become a passing label;
   a failed removal or secret scan must still block its required check.
4. Scope drift. A newly added privileged workflow needs its own review, not an
   expansion to a wildcard or all actors/events.
5. Effective organization and enterprise rules. A repository exception is not
   evidence that those rules permit the run.

## Phase 4: live canaries and completion evidence

After applying the policy, use controlled test PRs and record their URLs and
head SHAs. Do not weaken branch protection or approve an intentionally bad PR.

| Canary | Expected result |
| --- | --- |
| Ordinary documentation PR, same repository and fork | Required checks report even when catalog work is skipped; labels/comments can be posted. |
| Valid catalog change from a fork | Trusted validators scan the exact fork head; schema and removal checks report successfully. |
| Invalid catalog manifest | Validate PR fails and diagnostics identify the failure; no passing label is applied. |
| Removal of an agent still required by an active kit | Removal gate fails unless the existing allowed resolution is satisfied. |
| Synchronize/reopen a controlled PR | Existing event filters still trigger; obsolete runs do not replace current-head evidence. |
| Non-draft PR and submitted review | Native auto-merge configuration still runs; no new broad auto-approval exception appears. |
| Unrelated workflow | It has not acquired a `pull_request_target` exception from this policy. |

Do not manufacture real credentials to test the secret scanner. Retain its
existing regression tests and use only approved safe scanner fixtures.
Manual workflow dispatches alone cannot validate the target-event allowlist.
After the November 2 enforcement date, recheck Policy insights and a new PR run.

## Rollback and ongoing ownership

If a canary exposes unexpected permissions, scope, or execution, stop rollout.
For a newly created policy, an administrator can delete only the recorded ID:

```powershell
gh api --method DELETE -H "X-GitHub-Api-Version: 2026-03-10" `
  repos/microsoft/discovery/actions/policies/POLICY_ID
```

For an updated policy, restore the saved original payload instead. Reverting a
Git commit does not roll back live settings. Removing the exception can cause
the default policy to block these workflows again; temporarily pause merges
rather than removing required checks. Coordinate any inherited-policy rollback
with its owner.

Reviewers of workflow changes must update the policy and its contracts together
when a privileged workflow is added, renamed, retired, or changes events.
Periodically inspect Policy insights, required checks, token scopes, action
pins, and dependency updates.

## References

- [GitHub announcement and November 2 deadline](https://github.blog/changelog/2026-09-17-workflow-execution-protections-in-github-actions-generally-available/)
- [Governing workflow execution and policy insights](https://docs.github.com/en/actions/how-tos/administer/control-workflow-execution)
- [Securely using pull_request_target](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)
- [Actions policies REST API](https://docs.github.com/en/rest/actions/policies)
