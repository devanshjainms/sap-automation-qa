#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Validate skills against Agent Skills spec and Azure SRE Agent best practices.

Checks:
  - agentskills.io/specification (name, description, frontmatter, line count)
  - agentskills.io/skill-creation/best-practices (progressive disclosure, gotchas)
  - agentskills.io/skill-creation/optimizing-descriptions (imperative phrasing)
  - learn.microsoft.com/azure/sre-agent/skills (tool attachment, max 5 active)
"""

from __future__ import annotations
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Install it with: pip install pyyaml")
    sys.exit(1)

# ── Spec limits ──────────────────────────────────────────────────
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_COMPATIBILITY_LENGTH = 500
MAX_SKILL_LINES = 500
MAX_RECOMMENDED_TOKENS = 5000
CHARS_PER_TOKEN = 4

NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
CONSECUTIVE_HYPHENS = re.compile(r"--")
REFERENCE_PATTERN = re.compile(
    r"\((?:scripts|references|assets|templates)/[^)]+\)"
)

# ── Best-practice patterns ───────────────────────────────────────
IMPERATIVE_PATTERNS = [
    re.compile(r"use\s+(this\s+)?when", re.IGNORECASE),
    re.compile(r"activate\s+when", re.IGNORECASE),
    re.compile(r"triggered\s+by", re.IGNORECASE),
    re.compile(r"use\s+this\s+skill", re.IGNORECASE),
]

VALID_FRONTMATTER_KEYS = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}


@dataclass
class Finding:
    """A single validation finding."""

    skill: str
    level: str  # error | warning | pass
    message: str


@dataclass
class ValidationResult:
    """Aggregated validation results."""

    findings: list[Finding] = field(default_factory=list)
    skills_checked: int = 0

    def error(self, skill: str, message: str) -> None:
        self.findings.append(Finding(skill, "error", message))

    def warn(self, skill: str, message: str) -> None:
        self.findings.append(Finding(skill, "warning", message))

    def ok(self, skill: str, message: str) -> None:
        self.findings.append(Finding(skill, "pass", message))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0


def parse_frontmatter(skill_md: Path) -> tuple[dict | None, str, str]:
    """Parse YAML frontmatter and body from a SKILL.md file.

    :returns: (frontmatter dict or None, error message, body text).
    """
    text = skill_md.read_text(encoding="utf-8")
    lines = text.split("\n")

    if not lines or lines[0].strip() != "---":
        return None, "SKILL.md does not start with YAML frontmatter (---)", ""

    end_index = -1
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = i
            break

    if end_index == -1:
        return None, "YAML frontmatter not closed (missing second ---)", ""

    frontmatter_text = "\n".join(lines[1:end_index])
    body = "\n".join(lines[end_index + 1 :])
    try:
        data = yaml.safe_load(frontmatter_text)
        if not isinstance(data, dict):
            return None, "Frontmatter is not a YAML mapping", ""
        return data, "", body
    except yaml.YAMLError as exc:
        return None, f"Invalid YAML in frontmatter: {exc}", ""


def validate_frontmatter_keys(
    frontmatter: dict, result: ValidationResult, skill: str,
) -> None:
    """Warn on unknown frontmatter keys."""
    unknown = set(frontmatter.keys()) - VALID_FRONTMATTER_KEYS
    if unknown:
        result.warn(
            skill,
            f"Unknown frontmatter keys: {sorted(unknown)} "
            f"(valid: {sorted(VALID_FRONTMATTER_KEYS)})",
        )


def validate_name(
    name: str | None, dir_name: str, result: ValidationResult, skill: str,
) -> None:
    """Validate the 'name' frontmatter field per spec."""
    if not name:
        result.error(skill, "Missing required 'name' field in frontmatter")
        return

    if name != dir_name:
        result.error(skill, f"name '{name}' != directory '{dir_name}'")
        return

    if len(name) > MAX_NAME_LENGTH:
        result.error(skill, f"name exceeds {MAX_NAME_LENGTH} chars ({len(name)})")
        return

    if not NAME_PATTERN.match(name):
        result.error(
            skill,
            f"name '{name}' invalid (lowercase a-z, 0-9, hyphens only, "
            f"no leading/trailing hyphens)",
        )
        return

    if CONSECUTIVE_HYPHENS.search(name):
        result.error(skill, f"name '{name}' contains consecutive hyphens")
        return

    result.ok(skill, f"name valid ({name})")


def validate_description(
    description: str | None, result: ValidationResult, skill: str,
) -> None:
    """Validate description field per spec + best practices."""
    if not description:
        result.error(skill, "Missing required 'description' field")
        return

    desc_len = len(description)
    if desc_len > MAX_DESCRIPTION_LENGTH:
        result.error(
            skill,
            f"description exceeds {MAX_DESCRIPTION_LENGTH} chars ({desc_len})",
        )
    else:
        result.ok(skill, f"description length OK ({desc_len} chars)")

    has_imperative = any(p.search(description) for p in IMPERATIVE_PATTERNS)
    if not has_imperative:
        result.warn(
            skill,
            "description lacks imperative phrasing "
            "(recommended: 'Use when...', 'Triggered by...', 'Activate when...')",
        )
    else:
        result.ok(skill, "description has imperative trigger phrasing")


def validate_compatibility(
    frontmatter: dict, result: ValidationResult, skill: str,
) -> None:
    """Validate optional compatibility field."""
    compat = frontmatter.get("compatibility")
    if not compat:
        result.warn(skill, "No 'compatibility' field (recommended for env requirements)")
        return

    if len(compat) > MAX_COMPATIBILITY_LENGTH:
        result.error(
            skill,
            f"compatibility exceeds {MAX_COMPATIBILITY_LENGTH} chars ({len(compat)})",
        )
    else:
        result.ok(skill, "compatibility field present")


def validate_line_count(
    skill_md: Path, result: ValidationResult, skill: str,
) -> None:
    """Check SKILL.md line count and estimated token count."""
    text = skill_md.read_text(encoding="utf-8")
    lines = text.splitlines()
    line_count = len(lines)
    est_tokens = len(text) // CHARS_PER_TOKEN

    if line_count > MAX_SKILL_LINES:
        result.warn(
            skill,
            f"SKILL.md has {line_count} lines (spec: <{MAX_SKILL_LINES}). "
            f"Move detail to references/",
        )
    else:
        result.ok(skill, f"line count OK ({line_count})")

    if est_tokens > MAX_RECOMMENDED_TOKENS:
        result.warn(
            skill,
            f"Estimated ~{est_tokens} tokens (recommended: <{MAX_RECOMMENDED_TOKENS}). "
            f"Consider splitting content.",
        )


def validate_scripts(
    skill_dir: Path, frontmatter: dict, result: ValidationResult, skill: str,
) -> None:
    """Check scripts are executable and allowed-tools is set."""
    scripts = [
        s
        for s in list(skill_dir.rglob("*.sh")) + list(skill_dir.rglob("*.py"))
        if "__pycache__" not in str(s) and s.name != "__init__.py"
    ]

    for script in scripts:
        if not os.access(script, os.X_OK):
            result.error(skill, f"Script not executable: {script.name}")
        else:
            result.ok(skill, f"Script executable: {script.name}")

    allowed_tools = frontmatter.get("allowed-tools", "")
    if scripts and not allowed_tools:
        result.warn(
            skill,
            "Has scripts but no 'allowed-tools' in frontmatter",
        )


def validate_references(
    skill_md: Path, skill_dir: Path, result: ValidationResult, skill: str,
) -> None:
    """Check that referenced files exist."""
    text = skill_md.read_text(encoding="utf-8")
    refs = REFERENCE_PATTERN.findall(text)

    for ref in refs:
        ref_path = ref.strip("()")
        full_path = skill_dir / ref_path
        if not full_path.exists():
            result.error(
                skill, f"References '{ref_path}' but file not found",
            )
        else:
            result.ok(skill, f"Reference exists: {ref_path}")


def validate_progressive_disclosure(
    skill_dir: Path, body: str, result: ValidationResult, skill: str,
) -> None:
    """Check progressive disclosure best practice.

    If SKILL.md is long, it should reference external files rather
    than inlining everything.
    """
    line_count = len(body.splitlines())
    has_refs_dir = (skill_dir / "references").is_dir()
    has_scripts_dir = (skill_dir / "scripts").is_dir()
    has_assets_dir = (skill_dir / "assets").is_dir()
    has_subdirs = has_refs_dir or has_scripts_dir or has_assets_dir

    if line_count > 300 and not has_subdirs:
        result.warn(
            skill,
            f"SKILL.md body is {line_count} lines with no references/, "
            f"scripts/, or assets/ directory. Consider progressive disclosure.",
        )

    refs_in_body = REFERENCE_PATTERN.findall(body)
    if has_subdirs and not refs_in_body and line_count > 200:
        result.warn(
            skill,
            "Has subdirectories but SKILL.md doesn't reference them. "
            "Link to files with (references/file.md) for progressive disclosure.",
        )


def validate_hardcoded_values(
    body: str, result: ValidationResult, skill: str,
) -> None:
    """Warn if SKILL.md contains large property tables.

    Best practice: properties should come from knowledge base / JSONL
    files, not be hardcoded in skills.
    """
    table_rows = [
        line for line in body.splitlines()
        if line.strip().startswith("|") and "|" in line[1:]
    ]
    if len(table_rows) > 30:
        result.warn(
            skill,
            f"SKILL.md has {len(table_rows)} table rows. "
            f"Consider referencing knowledge base rules instead of "
            f"hardcoding property values.",
        )


def validate_skill(skill_dir: Path, result: ValidationResult) -> None:
    """Validate a single skill directory."""
    dir_name = skill_dir.name
    skill_md = skill_dir / "SKILL.md"

    if not skill_md.exists():
        result.error(dir_name, "Missing SKILL.md")
        return

    result.ok(dir_name, "SKILL.md exists")

    frontmatter, error, body = parse_frontmatter(skill_md)
    if frontmatter is None:
        result.error(dir_name, error)
        return

    result.ok(dir_name, "YAML frontmatter valid")

    validate_frontmatter_keys(frontmatter, result, dir_name)
    validate_name(frontmatter.get("name"), dir_name, result, dir_name)
    validate_description(frontmatter.get("description"), result, dir_name)
    validate_compatibility(frontmatter, result, dir_name)
    validate_line_count(skill_md, result, dir_name)
    validate_scripts(skill_dir, frontmatter, result, dir_name)
    validate_references(skill_md, skill_dir, result, dir_name)
    validate_progressive_disclosure(skill_dir, body, result, dir_name)
    validate_hardcoded_values(body, result, dir_name)


def validate_skills_directory(skills_dir: Path) -> ValidationResult:
    """Validate all skills in a directory."""
    result = ValidationResult()

    if not skills_dir.is_dir():
        result.error("(root)", f"Skills directory '{skills_dir}' not found")
        return result

    skip_dirs = {"_validation", "__pycache__"}
    skill_dirs = sorted(
        d
        for d in skills_dir.iterdir()
        if d.is_dir() and d.name not in skip_dirs and not d.name.startswith(".")
    )

    if not skill_dirs:
        result.warn("(root)", "No skill directories found")
        return result

    for skill_dir in skill_dirs:
        result.skills_checked += 1
        validate_skill(skill_dir, result)

    if result.skills_checked > 5:
        result.warn(
            "(root)",
            f"Found {result.skills_checked} skills. Azure SRE Agent supports "
            f"max 5 concurrent active skills — consider consolidating.",
        )

    return result


def print_results(result: ValidationResult) -> None:
    """Print validation results to stdout."""
    icons = {"error": "❌", "warning": "⚠️ ", "pass": "✅"}

    current_skill = None
    for finding in result.findings:
        if finding.skill != current_skill:
            current_skill = finding.skill
            print(f"\n--- {current_skill} ---")
        icon = icons[finding.level]
        print(f"  {icon} {finding.message}")

    print(f"\n{'=' * 50}")
    print(f"Skills checked: {result.skills_checked}")
    print(f"Errors:   {len(result.errors)}")
    print(f"Warnings: {len(result.warnings)}")

    if result.passed:
        print("\n✅ ALL SKILLS VALID")
    else:
        print("\n❌ VALIDATION FAILED")
        for err in result.errors:
            print(f"  - [{err.skill}] {err.message}")


def main() -> int:
    """Run skill validation from the command line."""
    skills_dir = (
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".github/skills")
    )
    result = validate_skills_directory(skills_dir)
    print_results(result)
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
