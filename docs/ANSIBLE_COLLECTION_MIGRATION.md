# Ansible Collection Migration Plan (Option C)

> Restructure into a proper Ansible Galaxy collection (`azure.sap_automation_qa`) while keeping the Python application (FastAPI/core) as a separate component.

## Target Structure

```
├── galaxy.yml                          # Collection metadata
├── meta/
│   └── runtime.yml                     # requires_ansible, plugin routing
├── changelogs/
│   └── changelog.yaml                  # antsibull-changelog format
├── plugins/
│   ├── modules/                        # ← from src/modules/
│   ├── module_utils/                   # ← from src/module_utils/
│   └── filter/                         # (future: custom Jinja2 filters)
├── roles/
│   ├── ha_db_hana/                     # ← from src/roles/ha_db_hana/
│   │   ├── tasks/
│   │   ├── defaults/main.yml          # NEW
│   │   ├── meta/main.yml             # NEW
│   │   └── README.md                  # NEW
│   ├── ha_scs/                         # (same additions)
│   ├── configuration_checks/
│   ├── backup_db_hana/
│   └── misc/
├── playbooks/                          # ← from src/playbook_*.yml
├── templates/                          # ← from src/templates/
├── vars/                               # ← from src/vars/
├── ansible.cfg
├── app/                                # ← from src/api/ + src/core/
│   ├── api/
│   ├── core/
│   └── __init__.py
├── scripts/                            # unchanged
├── tests/                              # updated paths
├── deploy/                             # updated COPY paths
└── WORKSPACES/                         # unchanged
```

## Changes Required

### 1. Move Ansible Content Out of `src/`

| From | To |
|---|---|
| `src/modules/` | `plugins/modules/` |
| `src/module_utils/` | `plugins/module_utils/` |
| `src/roles/` | `roles/` |
| `src/playbook_*.yml` | `playbooks/` |
| `src/templates/` | `templates/` |
| `src/vars/` | `vars/` |
| `src/ansible.cfg` | `ansible.cfg` (repo root) |

### 2. Move Python Application Code

| From | To |
|---|---|
| `src/api/` | `app/api/` |
| `src/core/` | `app/core/` |
| `src/__init__.py` | `app/__init__.py` |

### 3. Add New Collection Files

**`galaxy.yml`** (repo root):
```yaml
namespace: azure
name: sap_automation_qa
version: <from VERSION file>
description: SAP Testing Automation Framework for Azure
authors: ["Microsoft Corporation"]
license: ["MIT"]
repository: https://github.com/Azure/sap-automation-qa
dependencies: {}
build_ignore:
  - app
  - tests
  - deploy
  - scripts
  - WORKSPACES
  - docs
  - client
  - .github
  - .venv
  - "*.pyc"
```

**`meta/runtime.yml`**:
```yaml
requires_ansible: ">=2.17.0"
```

**Per-role `defaults/main.yml`** — extract all variables used by each role with sensible defaults.

**Per-role `meta/main.yml`**:
```yaml
galaxy_info:
  author: Microsoft Corporation
  description: <role purpose>
  license: MIT
  min_ansible_version: "2.17"
  platforms:
    - name: EL
      versions: ["8", "9", "10"]
    - name: SLES
      versions: ["15"]
dependencies: []
```

**Per-role `README.md`** — role purpose, required variables, example usage.

### 4. Rewrite Module Imports (15 files in `plugins/modules/`)

```python
# Before (dual-fallback):
try:
    from ansible.module_utils.sap_automation_qa import SapAutomationQA
except ImportError:
    from src.module_utils.sap_automation_qa import SapAutomationQA

# After (collection-aware):
from ansible_collections.azure.sap_automation_qa.plugins.module_utils.sap_automation_qa import (
    SapAutomationQA,
)
```

All 15 module files need this change. The `src.module_utils` fallback path is removed.

### 5. Use FQCNs in All Task Files (~50 files)

```yaml
# Before:
- name: "Get cluster status"
  get_cluster_status_db:
    param: value

# After:
- name: "Get cluster status"
  azure.sap_automation_qa.get_cluster_status_db:
    param: value
```

Affects every task file that references a custom module.

### 6. Fix `include_tasks` Relative Paths

```yaml
# Before (relative to src/):
ansible.builtin.include_tasks: "roles/misc/tasks/test-case-setup.yml"

# After (relative to playbooks/):
ansible.builtin.include_tasks: "{{ playbook_dir }}/../roles/misc/tasks/test-case-setup.yml"
```

Or restructure roles to use `tasks/main.yml` entry points and `include_role` instead.

### 7. Update `vars_files` in Playbooks

```yaml
# Before:
vars_files: "./vars/input-api.yaml"

# After:
vars_files: "{{ playbook_dir }}/../vars/input-api.yaml"
```

### 8. Update `ansible.cfg`

```ini
# Before:
library=modules
module_utils=module_utils

# After (collection auto-discovers plugins, but keep for non-collection runs):
collections_paths = ./
```

### 9. Update CLI Script (`scripts/sap_automation_qa.sh`)

```bash
# Before:
export ANSIBLE_CONFIG="${cmd_dir}/../src/ansible.cfg"
ansible-playbook ${cmd_dir}/../src/$playbook_name.yml ...

# After:
export ANSIBLE_CONFIG="${cmd_dir}/../ansible.cfg"
ansible-playbook ${cmd_dir}/../playbooks/$playbook_name.yml ...
```

Also update `ANSIBLE_MODULE_UTILS` and `ANSIBLE_COLLECTIONS_PATH` exports.

### 10. Update API Executor (`app/core/execution/executor.py`)

```python
# Before:
playbook_dir: Path = "src"
ansible_cfg: self.playbook_dir / "ansible.cfg"

# After:
playbook_dir: Path = "playbooks"
ansible_cfg: Path("ansible.cfg")
```

### 11. Update Dockerfile

```dockerfile
# Before:
COPY src/ ./src/
ENV PYTHONPATH=/app

# After:
COPY app/ ./app/
COPY plugins/ ./plugins/
COPY roles/ ./roles/
COPY playbooks/ ./playbooks/
COPY templates/ ./templates/
COPY vars/ ./vars/
COPY ansible.cfg galaxy.yml meta/ ./
ENV PYTHONPATH=/app
```

Update CMD: `uvicorn app.api.app:app ...`

### 12. Update Test Infrastructure

- `tests/` imports change from `src.module_utils.*` / `src.modules.*` → `plugins.module_utils.*` / `plugins.modules.*`
- `RolesTestingBase` temp dir structure must mirror collection layout
- `conftest.py` in `tests/api/` and `tests/core/` update app imports

### 13. Update CI Workflows

- `pytest --cov=app --cov=plugins` (was `--cov=src`)
- `black --check app/ plugins/ tests/`
- `pylint app/ plugins/`
- Add `ansible-test sanity` step
- Add `ansible-galaxy collection build` step

### 14. Add Module Documentation Strings

Every module in `plugins/modules/` must have:
```python
DOCUMENTATION = r"""
module: get_cluster_status_db
short_description: Validates HANA cluster status
description: ...
options:
  param_name:
    description: ...
    required: true
    type: str
"""

EXAMPLES = r"""
- name: Check HANA cluster status
  azure.sap_automation_qa.get_cluster_status_db:
    sap_sid: HN1
"""

RETURN = r"""
status:
  description: Cluster status result
  returned: always
  type: dict
"""
```

Required for `ansible-doc` and `ansible-test sanity`.

## Execution Order

1. Create `galaxy.yml`, `meta/runtime.yml` — establishes collection identity
2. Move `src/modules/` → `plugins/modules/`, `src/module_utils/` → `plugins/module_utils/` — rewrite imports
3. Move `src/roles/` → `roles/` — add `defaults/`, `meta/`, README per role
4. Move playbooks, templates, vars, ansible.cfg — fix relative paths
5. Move `src/api/` + `src/core/` → `app/` — update Python imports
6. Update CLI script, executor, Dockerfile, docker-compose
7. Update all task files with FQCNs and corrected include paths
8. Update tests — paths, imports, base class
9. Update CI — coverage paths, add `ansible-test sanity`, collection build
10. Add `DOCUMENTATION`/`EXAMPLES`/`RETURN` to all modules
11. Run full test suite, `ansible-test sanity`, `ansible-galaxy collection build`

## Files Affected (Estimate)

| Category | File Count |
|---|---|
| Module import rewrites | ~15 |
| Task FQCN + path fixes | ~50 |
| Playbook vars_files fixes | 5 |
| Python app import updates | ~30 |
| Test import/path updates | ~40 |
| Config/CI/Docker updates | ~8 |
| New files (galaxy, meta, defaults, READMEs) | ~15 |
| **Total** | **~163** |
