---
name: dev-workflow
description: >
  Consolidated reference for the development workflow agent pipeline.
  Contains workflow overview, artifact schemas, templates, conventions,
  and CI commands for all dev-* agents.
metadata:
  examples:
    - Start the dev workflow for issue #42
    - Create a spec for this GitHub issue
    - Review the implementation plan
    - Run validation checks before PR
    - Assess documentation impact
---

# Dev Workflow Skill — Consolidated Reference

> Single source of truth for all `dev-*` workflow agents.
> Read this skill before performing any workflow action.

## References

- [About custom agents — GitHub Docs](https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-custom-agents)
- [Agent profile format — GitHub Docs](https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-custom-agents#agent-profile-format)
- [Running agents as subagents — GitHub Docs](https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-custom-agents#running-agents-as-subagents)
- [black formatter](https://black.readthedocs.io/en/stable/)
- [pylint](https://pylint.readthedocs.io/en/stable/)
- [pytest-cov](https://pytest-cov.readthedocs.io/en/stable/)
- [ansible-lint](https://ansible.readthedocs.io/projects/lint/)

---

## Workflow Overview

```
Work Item (any source)
    │
    ▼
dev-01-conductor ──► Normalize intake ──► 00-intake.json
    │
    ▼
dev-02-spec ──► 01-spec.md (Why + What)
    │
    ▼
dev-03-planner ──► 02-implementation-plan.md (How)
    │
    ▼
dev-04-gate ──► 03-plan-review.md (APPROVED / REJECTED)
    │                                    │
    │ ◄── REJECTED (max 2x) ◄───────────┘
    │
    ▼ APPROVED
dev-05-implementer ──► Code on feature branch
    │
    ▼
dev-06-test-author ──► Tests on feature branch
    │
    ▼
dev-07-validator ──► 04-validation-report.md (PASS / FAIL)
    │                                    │
    │ ◄── FAIL (max 3x) ◄───────────────┘
    │
    ▼ PASS
dev-08-reviewer ──► 05-code-review.md (APPROVED / CHANGES_REQUESTED)
    │                                    │
    │ ◄── CHANGES_REQUESTED ◄────────────┘
    │
    ▼ APPROVED
dev-09-pr-manager ──► Draft PR → Copilot Review → Fix → Ready
    │
    ▼
dev-10-docs-sync ──► 07-docs-assessment.md + optional docs PR
    │
    ▼
workflow:ready ──► User reviews PR
```

---

## Artifact Tracking

All workflow artifacts live in `.copilot-tracking/{work-item-id}/`.

### Work Item ID Format

| Source | ID Format | Example |
|--------|----------|---------|
| GitHub Issue | `gh-{number}` | `gh-42` |
| ADO Work Item | `ado-{id}` | `ado-1234` |
| User Prompt | `prompt-{timestamp}` | `prompt-20260521T1630` |
| Word Document | `doc-{filename-stem}` | `doc-hana-scaleout-spec` |

### Artifact Files

| File | Producer | Description |
|------|----------|-------------|
| `00-intake.json` | dev-01-conductor | Canonical work item (normalized from any source) |
| `state.json` | dev-01-conductor | Workflow state machine |
| `01-spec.md` | dev-02-spec | Specification (Why + What) |
| `02-implementation-plan.md` | dev-03-planner | Implementation plan (How) |
| `03-plan-review.md` | dev-04-gate | Plan review verdict |
| `04-validation-report.md` | dev-07-validator | CI validation results |
| `05-code-review.md` | dev-08-reviewer | Internal code review verdict |
| `06-pr-summary.md` | dev-09-pr-manager | PR creation summary |
| `07-docs-assessment.md` | dev-10-docs-sync | Documentation impact assessment |

### state.json Schema

> **Design rationale**: JSON state (not Markdown) is mandatory because agents
> are less likely to corrupt structured JSON than freeform text.

```json
{
  "work_item_id": "gh-42",
  "branch": "dev/42-add-hana-scaleout-support",
  "base_branch": "development-may-2026",
  "current_stage": "implementing",
  "stages": {
    "intake": { "status": "done", "completed_at": "2026-05-21T16:00:00Z" },
    "spec": { "status": "done", "completed_at": "2026-05-21T16:05:00Z" },
    "planning": { "status": "done", "completed_at": "2026-05-21T16:10:00Z" },
    "gate": { "status": "done", "verdict": "APPROVED", "completed_at": "2026-05-21T16:12:00Z" },
    "implementing": { "status": "in_progress", "started_at": "2026-05-21T16:13:00Z", "retry_count": 0 },
    "testing": { "status": "pending" },
    "validating": { "status": "pending" },
    "reviewing": { "status": "pending" },
    "pr": { "status": "pending" },
    "docs": { "status": "pending" }
  },
  "tracking_issue": 42,
  "pr_number": null,
  "docs_pr_number": null,
  "total_retries": 0,
  "progress_log": [
    { "timestamp": "2026-05-21T16:00:00Z", "stage": "intake", "event": "completed", "summary": "Normalized from GitHub issue #42" },
    { "timestamp": "2026-05-21T16:05:00Z", "stage": "spec", "event": "completed", "summary": "10 acceptance criteria, 8 affected files" },
    { "timestamp": "2026-05-21T16:13:00Z", "stage": "implementing", "event": "started", "summary": "Implementing 12 changes from approved plan" }
  ]
}
```

#### state.json Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `work_item_id` | string | yes | Canonical work item identifier |
| `branch` | string | yes | Feature branch name (null until created) |
| `base_branch` | string | yes | Upstream development branch this feature branches from (PR target) |
| `current_stage` | string | yes | **Must be updated after every stage transition** |
| `stages.{name}.status` | string | yes | `pending`, `in_progress`, `done`, `failed`, `skipped` |
| `stages.{name}.started_at` | string | no | ISO 8601 timestamp when stage began |
| `stages.{name}.completed_at` | string | no | ISO 8601 timestamp when stage finished |
| `stages.{name}.verdict` | string | no | For gate/review stages: `APPROVED`, `REJECTED`, `CHANGES_REQUESTED` |
| `stages.{name}.retry_count` | number | no | Number of retry attempts for this stage |
| `stages.{name}.error_context` | string | no | Brief description of why the stage failed (for retry handoff) |
| `tracking_issue` | number | no | GitHub issue number for tracking |
| `pr_number` | number | no | PR number once created |
| `docs_pr_number` | number | no | Docs PR number if applicable |
| `total_retries` | number | yes | Sum of all retries across the pipeline (circuit breaker input) |
| `progress_log` | array | yes | Append-only log of stage transitions with summaries |

#### Stage Status Transitions

```
pending → in_progress → done
                      → failed (may retry → in_progress)
pending → skipped (if stage is not applicable)
```

**Rule**: `current_stage` MUST always reflect the stage that is `in_progress` or
the last stage that completed. Never leave it stale.

---

## Canonical Work Item Format (00-intake.json)

> **Design rationale**: Acceptance criteria use the "feature list" pattern —
> structured JSON with a `passes` field that the validator updates, enabling
> machine-readable pass/fail tracking across retry cycles.

```json
{
  "source_type": "github_issue | ado_work_item | user_prompt | word_document",
  "source_ref": "#42 | ADO:1234 | prompt | path/to/spec.docx",
  "tracking_issue": 42,
  "title": "...",
  "description": "...",
  "acceptance_criteria": [
    { "id": "AC-1", "description": "All task labels follow consistent naming convention", "passes": null },
    { "id": "AC-2", "description": "Dynamic labeling replaces hardcoded values", "passes": null },
    { "id": "AC-3", "description": "All CI checks pass (black, pylint ≥9.0, pytest ≥85%)", "passes": null }
  ],
  "labels": ["...", "..."],
  "linked_items": ["...", "..."]
}
```

### Acceptance Criteria Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Stable identifier (AC-1, AC-2, ...) — never renumbered |
| `description` | string | Human-readable criterion |
| `passes` | boolean or null | `null` = not yet evaluated, `true` = met, `false` = not met |

The `passes` field is updated by **dev-07-validator** during each validation cycle.
Other agents MUST NOT modify it. The conductor reads `passes` values to determine
if the pipeline can advance past validation.

**It is unacceptable to remove, rename, or edit acceptance criteria descriptions
after intake.** Only the `passes` field may be changed, and only by dev-07-validator.
This prevents requirements from being silently dropped during retry cycles.

---

## Branch Naming Convention

**Base branch**: Always branch from the upstream development branch (`development-*`).
The conductor discovers it dynamically:
```
BASE_BRANCH=$(git ls-remote --heads upstream 'development-*' \
  | awk '{print $2}' | sed 's|refs/heads/||' | sort -V | tail -1)
```
PRs always target this branch (e.g., `development-may-2026`).

Format: `dev/{issue-number}-{kebab-case-title}`

Examples:
- `dev/42-add-hana-scaleout-support`
- `dev/105-fix-telemetry-batch-timeout`

## Worktree Convention

Each issue gets its own **git worktree** for isolated, parallel work.

| Environment | Worktree Base | Example Path |
|-------------|--------------|--------------|
| CLI (local) | `$HOME/SDAF/worktrees/` | `$HOME/SDAF/worktrees/42-add-hana-scaleout/` |
| Cloud agent | N/A (branch-only fallback) | Current checkout directory |

The conductor creates worktrees automatically. The slug matches the branch name
without the `dev/` prefix. Multiple issues can run in parallel without conflicts.

---

## Commit Message Convention

Follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `ci`, `chore`

---

## CI Validation Commands

These commands are the source of truth for dev-07-validator:

```bash
# 1. Format check
black --check src/ tests/

# 2. Lint check
pylint src/ --fail-under=9

# 3. Tests + coverage
pytest tests/ --cov=src --cov-fail-under=85 -v

# 4. Ansible lint (if Ansible files changed)
ansible-lint src/

# 5. Type check (if pyright available)
pyright src/
```

All must pass before PR creation.

---

## Spec Artifact Template (01-spec.md)

```markdown
# Specification: {title}

## Source
- **Type**: {github_issue | ado_work_item | user_prompt | word_document}
- **Reference**: {source_ref}
- **Tracking Issue**: #{tracking_issue}

## Why (Motivation)
{Why does this work need to be done? What problem does it solve?}

## What (Scope)

### In Scope
- {item 1}
- {item 2}

### Out of Scope
- {item 1}

## Affected Areas
| Area | Files | Impact |
|------|-------|--------|

## Acceptance Criteria
1. {criterion from issue}
2. {derived criterion}

## Dependencies
- {dependency 1}

## Risks
- {risk 1}

## References
- {doc URL 1}
```

---

## Implementation Plan Template (02-implementation-plan.md)

```markdown
# Implementation Plan: {title}

## Spec Reference
01-spec.md

## Approach
{High-level approach with doc references for patterns used}

## Change Set (ordered by dependency)

| # | File | Action | Description | Reference |
|---|------|--------|-------------|-----------|
| 1 | src/module_utils/foo.py | CREATE | New utility class | {doc URL} |
| 2 | src/modules/bar.py | MODIFY | Add new parameter | {doc URL} |

## Test Plan

| # | Test File | What it tests | Coverage target |
|---|-----------|---------------|-----------------|

## Implementation Order
1. {step 1 — why this order}
2. {step 2}

## Risk Mitigations
- {risk}: {mitigation}
```

---

## Plan Review Template (03-plan-review.md)

```markdown
# Plan Review: {title}

## Verdict: APPROVED | REJECTED

## Checklist
- [ ] Plan covers all acceptance criteria from spec
- [ ] File paths are valid (existing files exist, new file paths are reasonable)
- [ ] Patterns follow copilot-instructions.md conventions
- [ ] Test plan covers happy path + failure paths
- [ ] No unsubstantiated claims (all decisions cite docs)
- [ ] Both SUSE and RHEL code paths considered (if applicable)
- [ ] Implementation order respects dependencies

## Findings
### {finding 1}
{description}

## Rejection Reasons (if REJECTED)
1. {reason}
```

---

## Validation Report Template (04-validation-report.md)

```markdown
# Validation Report: {title}

## Overall: PASS | FAIL

## Results

| Check | Command | Status | Output |
|-------|---------|--------|--------|
| Format | `black --check src/ tests/` | PASS/FAIL | {summary} |
| Lint | `pylint src/ --fail-under=9` | PASS/FAIL | {score} |
| Tests | `pytest --cov=src --cov-fail-under=85` | PASS/FAIL | {pass/fail/skip counts} |
| Coverage | (from pytest-cov) | PASS/FAIL | {percentage}% |
| Ansible | `ansible-lint src/` | PASS/FAIL/SKIP | {summary} |

## Acceptance Criteria Mapping

| # | Criterion | Met? | Evidence |
|---|-----------|------|----------|

## Failures (if any)
### {failure 1}
{exact error output}
```

---

## GitHub Issue Labels

```
workflow:intake
workflow:spec
workflow:planning
workflow:gate
workflow:implementing
workflow:testing
workflow:validating
workflow:reviewing
workflow:pr
workflow:docs
workflow:ready
workflow:blocked
```

---

## Evidence-Based Development

Every decision in this workflow must cite official documentation.

**Acceptable sources** (priority order):
1. GitHub Docs — https://docs.github.com
2. Microsoft Learn — https://learn.microsoft.com
3. Ansible Docs — https://docs.ansible.com
4. Python Docs — https://docs.python.org
5. SAP Help — https://help.sap.com
6. SUSE/Red Hat — https://documentation.suse.com, https://docs.redhat.com

**Cross-repo docs target**: `devanshjainms/azure-docs-pr` (fork of `MicrosoftDocs/azure-docs-pr`)
