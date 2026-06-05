---
name: staf-validate
description: >
  Validate STAF skills, agent definitions, and marketplace plugin manifests. Use when
  asked to validate skill files, check agent definitions, or verify plugin catalog integrity.
  Triggered by "validate skills", "check skill manifest", "validate agents", or "verify catalog".
allowed-tools: shell
agents:
  - copilot
  - claude
  - gemini
---

# STAF Validate

Validates STAF skill manifests, agent definition files, and marketplace plugin manifests.
Ensures all skills conform to the Agent Skills specification and that the plugin catalog
is consistent with the published skill directories.

> **⚠️ This skill is guidance only. Do NOT modify any source code, scripts, or framework files.**

## When to Use

| Trigger | Action |
|---------|--------|
| `validate skills` / `check skill manifest` | Run full skill validation |
| `validate agents` / `check agent files` | Validate agent definition files |
| `verify catalog` / `check plugin catalog` | Validate plugin.json and catalog.json |
| `run staf-validate` | Run end-to-end validation with coverage |

## Running Validation

```bash
# Validate skills and agents only (no coverage check)
bash .github/skills/staf-validate/scripts/validate.sh --target . --no-coverage

# Full validation including pytest coverage gate
bash .github/skills/staf-validate/scripts/validate.sh --target .
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `--target DIR` | Root directory to validate (default: `.`) |
| `--no-coverage` | Skip pytest coverage gate |

**Exit codes:**
- `0` — All checks passed
- `1` — One or more checks failed

## What Gets Validated

### SKILL.md Checks

| Check | Level |
|-------|-------|
| SKILL.md exists | Error |
| Valid YAML frontmatter | Error |
| `name` matches directory name | Error |
| `description` present | Error |
| `agents` list includes copilot, claude, gemini | Error |
| Scripts executable | Error |
| File references exist | Warning |
| `## Compatibility` section present | Warning |
| Line count ≤ 500 | Warning |

### Agent File Checks (`.github/agents/*.agent.md`)

| Check | Level |
|-------|-------|
| Valid YAML frontmatter | Error |
| `name` field present | Error |
| `runtime` field present | Error |
| `skills` list non-empty | Error |

### Plugin Manifest Checks (`plugin.json`)

| Check | Level |
|-------|-------|
| `plugin.json` exists in each skill directory | Error |
| Required fields present (`name`, `description`, `schema_version`, `supported_agents`, `entry_point`) | Error |
| `supported_agents` contains copilot, claude, gemini | Error |
| `entry_point` file exists | Error |

### Catalog Check (`.github/skills/catalog.json`)

| Check | Level |
|-------|-------|
| `catalog.json` exists | Error |
| Valid JSON | Error |
| All skill plugin.json files referenced | Error |

## Output Format

```
=== STAF Validation ===

[SKILL] setup-guide
  ✅ SKILL.md valid
  ✅ agents: copilot, claude, gemini
  ✅ plugin.json valid

[AGENT] claude-sap-test-strategist
  ✅ Frontmatter valid
  ✅ runtime: claude

[CATALOG]
  ✅ catalog.json valid (6 plugins)

====================================
Skills checked: 6
Agents checked: 6
Errors: 0
Warnings: 0

✅ ALL CHECKS PASSED
```

## Compatibility

| Agent Runtime | Supported |
|---------------|-----------|
| GitHub Copilot CLI | ✅ |
| Claude | ✅ |
| Gemini | ✅ |

## Related Skills

| Need to... | Use skill |
|------------|-----------|
| Fix workspace config | `workspace-validator` |
| Set up environment | `setup-guide` |
| Run tests | `test-runner` |
