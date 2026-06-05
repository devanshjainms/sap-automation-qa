#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
#
# validate.sh — End-to-end STAF skills, agents, and plugin-manifest validator.
#
# Usage:
#   bash .github/skills/staf-validate/scripts/validate.sh [--target DIR] [--no-coverage]
#
# Arguments:
#   --target DIR     Root of the repository to validate (default: .)
#   --no-coverage    Skip the pytest coverage gate

set -uo pipefail

# ── Defaults ────────────────────────────────────────────────────────────────
TARGET="."
NO_COVERAGE=false

# ── Argument parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)
            TARGET="$2"
            shift 2
            ;;
        --target=*)
            TARGET="${1#--target=}"
            shift
            ;;
        --no-coverage)
            NO_COVERAGE=true
            shift
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

cd "$TARGET"

echo "=== STAF Validation (target: $(pwd)) ==="
echo ""

ERRORS=0

# ── 1. SKILL.md validation ───────────────────────────────────────────────────
echo "[SKILL.md] Running validate_skills.py..."
if python3 .github/skills/_validation/validate_skills.py .github/skills; then
    echo "  ✅ All SKILL.md files valid"
else
    echo "  ❌ SKILL.md validation failed"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# ── 2. agents: field check ───────────────────────────────────────────────────
echo "[SKILL.md] Checking agents: frontmatter field..."
python3 - <<'PYEOF'
import sys
import glob

try:
    import yaml
except ImportError:
    print("  ❌ PyYAML not installed")
    sys.exit(1)

skills_dir = ".github/skills"
skill_files = sorted(glob.glob(f"{skills_dir}/*/SKILL.md"))
required_agents = {"copilot", "claude", "gemini"}
errors = []

for path in skill_files:
    skill_name = path.split("/")[-2]
    if skill_name.startswith("_"):
        continue
    text = open(path).read()
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        errors.append(f"{skill_name}: no YAML frontmatter")
        continue
    end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), -1)
    if end == -1:
        errors.append(f"{skill_name}: frontmatter not closed")
        continue
    try:
        fm = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        errors.append(f"{skill_name}: invalid YAML: {exc}")
        continue
    agents = set(fm.get("agents") or [])
    missing = required_agents - agents
    if missing:
        errors.append(f"{skill_name}: agents field missing {sorted(missing)}")
    else:
        print(f"  ✅ {skill_name}: agents OK")

if errors:
    for e in errors:
        print(f"  ❌ {e}")
    sys.exit(1)
PYEOF

if [[ $? -ne 0 ]]; then
    ERRORS=$((ERRORS + 1))
fi
echo ""

# ── 3. Agent definition files ────────────────────────────────────────────────
echo "[AGENTS] Validating .github/agents/*.agent.md..."
python3 - <<'PYEOF'
import sys
import glob

try:
    import yaml
except ImportError:
    print("  ❌ PyYAML not installed")
    sys.exit(1)

agent_files = sorted(glob.glob(".github/agents/*.agent.md"))

if not agent_files:
    print("  ❌ No agent definition files found in .github/agents/")
    sys.exit(1)

required_fields = {"name", "runtime", "skills"}
errors = []

for path in agent_files:
    fname = path.split("/")[-1]
    text = open(path).read()
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        errors.append(f"{fname}: no YAML frontmatter")
        continue
    end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), -1)
    if end == -1:
        errors.append(f"{fname}: frontmatter not closed")
        continue
    try:
        fm = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        errors.append(f"{fname}: invalid YAML: {exc}")
        continue
    if not isinstance(fm, dict):
        errors.append(f"{fname}: frontmatter is not a mapping")
        continue
    missing = required_fields - set(fm.keys())
    if missing:
        errors.append(f"{fname}: missing fields {sorted(missing)}")
    elif not fm.get("skills"):
        errors.append(f"{fname}: skills list is empty")
    else:
        print(f"  ✅ {fname}: OK (runtime={fm['runtime']}, skills={len(fm['skills'])})")

if errors:
    for e in errors:
        print(f"  ❌ {e}")
    sys.exit(1)

print(f"  Checked: {len(agent_files)} agent files")
PYEOF

if [[ $? -ne 0 ]]; then
    ERRORS=$((ERRORS + 1))
fi
echo ""

# ── 4. plugin.json manifests ─────────────────────────────────────────────────
echo "[PLUGIN] Validating plugin.json manifests..."
python3 - <<'PYEOF'
import json
import sys
import glob

skills_dir = ".github/skills"
skill_dirs = sorted(
    d.rstrip("/")
    for d in glob.glob(f"{skills_dir}/*/")
    if not d.split("/")[-2].startswith("_")
)

required_fields = {"name", "description", "schema_version", "supported_agents", "entry_point"}
required_agents = {"copilot", "claude", "gemini"}
errors = []

for skill_dir in skill_dirs:
    skill_name = skill_dir.split("/")[-1]
    plugin_path = f"{skill_dir}/plugin.json"
    try:
        with open(plugin_path) as f:
            data = json.load(f)
    except FileNotFoundError:
        errors.append(f"{skill_name}: plugin.json not found")
        continue
    except json.JSONDecodeError as exc:
        errors.append(f"{skill_name}: invalid JSON in plugin.json: {exc}")
        continue

    missing = required_fields - set(data.keys())
    if missing:
        errors.append(f"{skill_name}: plugin.json missing fields {sorted(missing)}")
        continue

    agents = set(data.get("supported_agents") or [])
    missing_agents = required_agents - agents
    if missing_agents:
        errors.append(f"{skill_name}: supported_agents missing {sorted(missing_agents)}")
        continue

    entry = f"{skill_dir}/{data['entry_point']}"
    import os
    if not os.path.exists(entry):
        errors.append(f"{skill_name}: entry_point '{data['entry_point']}' not found")
        continue

    print(f"  ✅ {skill_name}/plugin.json OK")

if errors:
    for e in errors:
        print(f"  ❌ {e}")
    sys.exit(1)
PYEOF

if [[ $? -ne 0 ]]; then
    ERRORS=$((ERRORS + 1))
fi
echo ""

# ── 5. Skills catalog ────────────────────────────────────────────────────────
echo "[CATALOG] Validating .github/skills/catalog.json..."
python3 - <<'PYEOF'
import json
import sys
import glob
import os

catalog_path = ".github/skills/catalog.json"
try:
    with open(catalog_path) as f:
        catalog = json.load(f)
except FileNotFoundError:
    print(f"  ❌ catalog.json not found at {catalog_path}")
    sys.exit(1)
except json.JSONDecodeError as exc:
    print(f"  ❌ Invalid JSON in catalog.json: {exc}")
    sys.exit(1)

plugins = catalog.get("plugins", [])
if not plugins:
    print("  ❌ catalog.json has no plugins entries")
    sys.exit(1)

# Check every skill directory is in the catalog
skill_dirs = sorted(
    d.rstrip("/").split("/")[-1]
    for d in glob.glob(".github/skills/*/")
    if not d.split("/")[-2].startswith("_")
)
catalog_names = {p.get("name") for p in plugins}
errors = []

for name in skill_dirs:
    if name not in catalog_names:
        errors.append(f"Skill '{name}' not listed in catalog.json")

if errors:
    for e in errors:
        print(f"  ❌ {e}")
    sys.exit(1)

print(f"  ✅ catalog.json valid ({len(plugins)} plugins)")
PYEOF

if [[ $? -ne 0 ]]; then
    ERRORS=$((ERRORS + 1))
fi
echo ""

# ── 6. Coverage gate (optional) ──────────────────────────────────────────────
if [[ "$NO_COVERAGE" == "false" ]]; then
    echo "[COVERAGE] Running pytest with coverage gate..."
    if python3 -m pytest tests/ --cov --cov-fail-under=85 -q; then
        echo "  ✅ Coverage gate passed"
    else
        echo "  ❌ Coverage gate failed"
        ERRORS=$((ERRORS + 1))
    fi
    echo ""
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo "$(printf '=%.0s' {1..40})"
if [[ "$ERRORS" -eq 0 ]]; then
    echo "✅ ALL CHECKS PASSED"
    exit 0
else
    echo "❌ VALIDATION FAILED ($ERRORS check(s) failed)"
    exit 1
fi
