# STAF Copilot Skills

This directory contains the five **SAP Testing Automation Framework (STAF)** skills for the
GitHub Copilot CLI. Each skill is a self-contained prompt that activates a specific guided
workflow when invoked.

## Skills Inventory

| Skill | Trigger Keywords | Description |
|---|---|---|
| `setup-guide` | "setup environment", "install staf", "container start", "docker deployment" | Guide for setting up the STAF environment, including Docker deployment, `setup.sh`, and `vars.yaml` configuration. |
| `test-runner` | "run test", "execute ha test", "start test", "run configuration check" | Execute STAF tests using `sap_automation_qa.sh`. Supports direct Ansible execution and API mode. |
| `test-result-analyzer` | "analyze results", "why did test fail", "test output", "check test status" | Analyze STAF test results and identify root causes from test logs and reports. |
| `workspace-creator` | "set up workspace", "onboard system", "create workspace" | Create new SAP workspace configurations for STAF testing. |
| `workspace-validator` | "validate workspace", "check config", "troubleshoot workspace" | Validate SAP workspace configurations before running tests. |

## Cross-Agent Discovery

SKILL.md is the **single source of truth** for each skill. Thin wrapper files in three
ecosystems all delegate to the same SKILL.md — no content is duplicated.

### GitHub Copilot CLI

Skills are discovered automatically from this directory. The `name` field in each
`SKILL.md` frontmatter matches the directory name and the slash command (e.g., `/setup-guide`).

```
.github/skills/<name>/SKILL.md   ← canonical prompt + metadata
```

### Claude Code

Claude Code discovers slash commands from `.claude/commands/<name>.md`. Each wrapper
includes the corresponding SKILL.md using Claude's `@<path>` file-include syntax, then
appends `$ARGUMENTS` so any text typed after the command is forwarded.

```
.claude/commands/<name>.md        ← wraps @.github/skills/<name>/SKILL.md
```

**Usage**: In Claude Code, type `/<name>` (e.g., `/setup-guide`) to activate the skill.

### Gemini CLI

Gemini CLI discovers slash commands from `.gemini/commands/<name>.toml`. Each TOML file
has a `description` (shown in `/help`) and a `prompt` that references the SKILL.md path
so the LLM reads it at invocation time. `{{args}}` is replaced by any text typed after
the command.

```
.gemini/commands/<name>.toml      ← references .github/skills/<name>/SKILL.md in prompt
```

**Usage**: In Gemini CLI, type `/<name>` (e.g., `/setup-guide`) to activate the skill.

## Design Rationale

> SKILL.md is the canonical definition of each skill. Wrapper files for Claude and
> Gemini delegate to it — they never duplicate the instruction text. This means a
> change to a SKILL.md is automatically reflected across all three ecosystems without
> touching any wrapper.

- **No drift**: Instruction text lives in exactly one place per skill.
- **Easy updates**: Edit only SKILL.md to change a skill's behavior.
- **Consistent experience**: All three CLIs receive the same guidance.

## Adding a New Skill

When adding a new skill across all three ecosystems, follow this checklist:

1. **Create** `.github/skills/<name>/SKILL.md` with required frontmatter
   (`name`, `description`) and full prompt content.
2. **Create** `.claude/commands/<name>.md` with:
   ```
   You are activating the STAF <name> skill. Read and follow the instructions below.

   @.github/skills/<name>/SKILL.md

   $ARGUMENTS
   ```
3. **Create** `.gemini/commands/<name>.toml` with:
   ```toml
   description = "<one-line description>"
   prompt = "You are activating the STAF <name> skill. Read and follow the instructions in .github/skills/<name>/SKILL.md as your authoritative guide. {{args}}"
   ```
4. **Run the validator** to confirm all three ecosystems pass (see below).
5. **Update this README** — add a row to the Skills Inventory table.

## Running the Skills Validator Locally

The validator checks all five skills for correct SKILL.md structure, Claude command
wiring, and Gemini command wiring.

```bash
# From the repo root:
python .github/skills/_validation/validate_skills.py .github/skills
```

A clean run prints `✅ ALL SKILLS VALID` and exits 0. Errors are prefixed `❌`; warnings
are prefixed `⚠️`.

The validator is also run automatically in CI via `.github/workflows/validate-skills.yml`
on every push and pull request.
