---
applyTo: "tests/**,**/test_cases/**,**/*test*.py,**/*.cib.xml"
---
# STAF testing conventions (HA scenarios, offline CIB, evidence)

Apply when adding or changing STAF test cases, fixtures, or test scenarios in `Azure/sap-automation-qa`.

## Scenario catalog (select the minimal set for a change)
- `hana-scaleup-hsr` — HANA scale-up HSR failover.
- `hana-scaleout-hsr` — HANA scale-out HSR failover.
- `ascs-ers-pacemaker` — ASCS/ERS Pacemaker failover.
Map the diff to the affected scenario(s) by path (e.g. `**/hana*/**`, `**/scaleout/**`, `**/ascs/**`,
`**/ers/**`, `**/pacemaker/**`); do not run everything by default.

## Two offline tiers must stay live-SSH-free
- **Framework tier** (hosted): `pytest --cov` (coverage gate enforced), `ansible-lint`,
  `ansible-playbook --syntax-check`, pre-commit. These gate every change.
- **Offline HA validation** (hosted): exercise the scenario engine against captured **CIB XML fixtures**
  with **no live cluster**. New HA-analysis logic must be reachable from an offline CIB fixture so it is
  testable without Azure. Add the fixture alongside the test (`tests/.../<scenario>.cib.xml`).

## Test-case definitions
- Test cases are data (`**/test_cases/**`, YAML). Extend the existing schema; reference cases by
  `test_case_details_from_test_case`. Keep one concern per case; make expected outcomes explicit
  (e.g. "2-node cluster list", specific failover_outcome), not implied.

## Determinism + evidence
- Tests must be deterministic and isolated (no ordering dependence, no shared mutable global state, no real
  network in offline tiers). A live tier (self-hosted, Environment-gated) is the ONLY place real failover
  runs — never simulate failover in an offline test and never gate a PR on a live run inside the inner loop.
- A passing scenario must yield the profile `evidence_schema` fields: `failover_outcome`, `rto_seconds`,
  `rpo_seconds`, `cluster_state_after`, `logs_artifact`. Offline tiers assert config/analysis correctness;
  the live tier produces the failover evidence.
