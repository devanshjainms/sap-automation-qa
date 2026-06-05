---
applyTo: "**/roles/**,**/playbooks/**,**/tasks/**/*.yml,**/tasks/**/*.yaml"
---
# STAF Ansible conventions (SAP Testing Automation Framework)

Apply when editing Ansible roles/playbooks/tasks in `Azure/sap-automation-qa` (STAF). Defer to the target
repo's own `.github/copilot-instructions.md` where it is more specific.

## Roles + tasks
- HA logic is organized by role: e.g. `ha_db_hana` (HANA database HA) and `ha_scs` (ASCS/ERS central
  services). New scenario steps extend the matching role's `tasks/` (e.g.
  `src/roles/ha_db_hana/tasks/ha-config.yml`, `.../sbd-fencing.yml`) — mirror the existing task layout.
- A task that gathers cluster facts for a module should **run the command, then pass its stdout into the
  relevant `src/modules/` module** (e.g. `fence_azure_arm -o list --msi` → into `get_pcmk_properties_*`),
  so the verdict is computed in the module and returned as one `test_result`.

## Idempotency + determinism (BLOCKING review criteria)
- Tasks must be **idempotent**: use the right modules with proper `creates`/`changed_when`/`failed_when`;
  avoid bare `command`/`shell` where a module exists; never depend on previous-run state.
- No sleeps as synchronization — use `wait_for`/retries with explicit `until`. Failover assertions must be
  deterministic (poll cluster state, don't guess timings).
- Pin behavior to variables, never to a specific host/SID/site. Use existing vars
  (`secondary_site_nodes`, `fence_azure_arm`, `test_case_details_from_test_case`).

## Safety
- `--syntax-check` and `ansible-lint` must pass. No secrets in plays/vars committed to the repo; secrets
  come from the secure environment at run time. Never edit `**/WORKSPACES/**` or `vars.yaml` env files.
- Tag tasks so scenario selection (hana-scaleup-hsr, hana-scaleout-hsr, ascs-ers-pacemaker) can target them.

## Evidence
- A live HA failover task set must produce the profile `evidence_schema` outputs (failover_outcome,
  rto_seconds, rpo_seconds, cluster_state_after, logs_artifact) — leave logs as a collectible artifact.
