---
applyTo: "src/**/*.py,tests/**/*.py,**/module_utils/**/*.py,**/modules/**/*.py"
---
# STAF Python conventions (SAP Testing Automation Framework)

These rules apply when editing Python in `Azure/sap-automation-qa` (STAF). They are materialized into the
target workspace at job start (they are NOT the SAP repo's own files). Treat the target repo's own
`.github/copilot-instructions.md` as additionally authoritative; where it conflicts, prefer the target repo.

## Module structure
- Ansible-facing logic lives in **`src/modules/`** (e.g. `get_pcmk_properties_db.py`,
  `get_pcmk_properties_scs.py`); shared helpers in **`src/module_utils/`**; role tasks call these modules.
- A new check that informs an Ansible task belongs **inside the relevant `src/modules/` module**, returning
  its result through the module's structured result dict — not as a free-standing script.
- Keep `module_utils` import-safe (no side effects at import time); modules use
  `ansible.module_utils.basic.AnsibleModule` and exit via `module.exit_json` / `module.fail_json`.

## Result + evidence shape
- Modules return a single structured `test_result` (status + details) so a scenario's outcome is contained
  in one object, not scattered across tasks. Map pass/fail explicitly; never rely on truthiness of strings.
- Surface the fields STAF evidence expects where relevant: `failover_outcome`, `rto_seconds`, `rpo_seconds`,
  `cluster_state_after` (see the framework profile `evidence_schema`).

## Style + safety
- Follow the repo's existing lint gates: `pytest --cov` (coverage gate is enforced), `ansible-lint`,
  pre-commit. Match the surrounding file's formatting; do not reformat unrelated code.
- Use explicit typing on new public functions; prefer pure functions for parsing (e.g. CIB XML) so they are
  unit-testable offline without a live cluster.
- Never hardcode hostnames, SIDs, SPNs, MSI client-ids, or credentials. Read them from passed-in params /
  Ansible vars (`secondary_site_nodes`, `fence_azure_arm`, `test_case_details_from_test_case`, etc.).
- No `shell=True`, no unbounded `subprocess` on untrusted input; quote arguments.

## Tests
- Every new module/behavior gets a unit test under `tests/` mirroring the source path
  (e.g. `tests/roles/ha_db_hana/...`). Offline tests must run with **no live SSH** — drive them from
  captured **CIB XML fixtures**, not a real cluster.
