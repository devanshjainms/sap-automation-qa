# SAP Testing Automation Framework - Copilot Instructions

> **Version**: 1.0.2 | **License**: MIT (Microsoft Corporation)
> **Repository**: [Azure/sap-automation-qa](https://github.com/Azure/sap-automation-qa)

## Project Identity

This is the **SAP Testing Automation Framework** -- an open-source orchestration tool
for validating SAP deployments on Microsoft Azure. It provides:

- **HA functional testing** for SAP HANA (Scale-Up, Scale-Out HSR, Scale-Out Standby)
  and SAP Central Services (ENSA1/ENSA2) in Pacemaker clusters.
- **Configuration validation** for HANA, IBM Db2, SCS, and application instances.
- **Offline validation** of HA configurations without live cluster interaction.
- A **FastAPI scheduling service** with async job execution, cron-based scheduling,
  workspace management, and event streaming.
- **Multi-destination telemetry** to Azure Log Analytics and Azure Data Explorer (Kusto).
- A **CLI entrypoint** (`sap_automation_qa.sh`) for both direct Ansible execution
  and API-driven workflows.

---

## Technology Stack

| Layer | Technologies |
|-------|-------------|
| **Language** | Python 3.10+ (Docker uses 3.12) |
| **API** | FastAPI, uvicorn, Pydantic v2 |
| **Automation** | Ansible-core 2.17, ansible-runner 2.4, Jinja2 |
| **Azure** | azure-identity, azure-keyvault-secrets, azure-kusto-data/ingest, azure-mgmt-compute/network/loganalytics, azure-storage-blob/queue |
| **Scheduling** | APScheduler (CronTrigger) |
| **Persistence** | SQLite (WAL mode), file-based log/artifact storage |
| **Frontend** | React (port 3000, in development) |
| **Testing** | pytest, pytest-asyncio (auto mode), pytest-cov, pytest-mock, httpx |
| **Code quality** | black (line-length 100), pylint (>=9.0 score, sphinx docstrings), ansible-lint |
| **CI/CD** | GitHub Actions (code coverage, ansible-lint, Docker build, CodeQL, Trivy, OSSF Scorecard) |
| **Container** | Azure Linux 3.12 base, multi-stage Docker build, non-root user |
| **Target OS** | SUSE (crm commands) and RHEL (pcs commands) -- OS-family dispatched |

---

## Project Structure

```
src/
├── api/                    # FastAPI application (routes, middleware, lifespan)
│   ├── app.py              # Entry point: lifespan wires stores, worker, scheduler
│   └── routes/             # health, jobs, schedules, workspaces
├── core/                   # Framework core (no Ansible dependency)
│   ├── execution/          # AnsibleExecutor, JobWorker, SshCredentialProvider
│   ├── models/             # Job, Schedule, SshCredential, TelemetryConfig, Workspace
│   ├── observability/      # StructuredLogger, ObservabilityMiddleware, telemetry handlers
│   ├── services/           # SchedulerService (async background cron loop)
│   └── storage/            # JobStore, ScheduleStore (SQLite WAL)
├── agents/                 # Agent architecture scaffold (not yet implemented)
├── module_utils/           # Shared Python utilities for Ansible modules
│   ├── sap_automation_qa.py  # ABC base for all modules
│   ├── collector.py          # CommandCollector, AzureDataParser (with command sanitization)
│   ├── filesystem_collector.py  # FileSystemCollector (findmnt, df, LVM, ANF, AFS, IMDS)
│   ├── commands.py           # OS-family command constants, DANGEROUS_COMMANDS blocklist
│   ├── enums.py              # TestStatus, TestSeverity, HanaTopology, HanaSRProvider
│   ├── get_cluster_status.py # BaseClusterStatusChecker (template method pattern)
│   ├── get_pcmk_properties.py  # BaseHAClusterValidator (CIB XML validation)
│   └── filter_tests.py      # TestFilter (test group/case selection, extra-vars generation)
├── modules/                # Custom Ansible modules (AnsibleModule pattern)
│   ├── configuration_check_module.py  # Parallel config checks via ThreadPoolExecutor
│   ├── get_cluster_status_db.py       # HANA cluster status (scale-up + scale-out HSR)
│   ├── get_cluster_status_scs.py      # SCS cluster status
│   ├── get_pcmk_properties_db.py      # DB pacemaker CIB validation
│   ├── get_pcmk_properties_scs.py     # SCS pacemaker CIB validation
│   ├── get_azure_lb.py               # Azure Load Balancer validation (MSI auth)
│   ├── send_telemetry_data.py         # ADX/Log Analytics telemetry sender (batch)
│   ├── log_parser.py                  # /var/log/messages parser with time-range filtering
│   ├── render_html_report.py          # Jinja2 HTML report generation
│   ├── check_indexserver.py           # HANA indexserver config check
│   ├── get_package_list.py            # SAP cluster package facts
│   ├── filesystem_freeze.py           # ANF filesystem freeze/unfreeze
│   └── location_constraints.py        # Pacemaker constraint removal
├── roles/                  # Ansible roles (task YAML files)
│   ├── ha_db_hana/tasks/   # 15 HANA HA scenarios
│   ├── ha_scs/tasks/       # 14 SCS HA scenarios
│   ├── configuration_checks/  # Config validation tasks + vars
│   └── misc/tasks/         # 13 shared tasks (pre/post validation, telemetry, cluster report)
├── playbook_00_*.yml       # Top-level playbooks (config checks, DB HA, SCS HA)
├── playbook_01_*.yml       # Offline HA tests
├── templates/              # Jinja2 templates, Azure pipeline template
└── vars/                   # Framework configuration (input-api.yaml)

tests/                      # pytest test suite (85% coverage enforced)
├── api/                    # FastAPI endpoint tests (httpx AsyncClient)
├── core/                   # Execution, models, storage, observability tests
├── modules/                # All 13 Ansible module tests
├── module_utils/           # Utility class tests
└── roles/                  # Role integration tests (RolesTestingBase + ansible_runner)

scripts/                    # Shell CLI and setup scripts
├── sap_automation_qa.sh    # Main CLI: API subcommands + direct Ansible execution
├── api_utils.sh            # REST API CLI wrapper (CRUD, formatting)
├── setup.sh                # Python venv, pip, Azure CLI installation
├── container_setup.sh      # Docker/compose management
├── utils.sh                # Colored logging, distro detection, package install
└── version_check.sh        # GitHub version check with semver comparison

deploy/                     # Docker deployment
├── Dockerfile              # Multi-stage (Azure Linux 3.12, non-root, healthcheck)
└── docker-compose.yml      # Single service, SQLite volume, WORKSPACES bind mount

client/                     # React frontend (in development, port 3000)
WORKSPACES/                 # System-specific configuration and credentials
docs/                       # Architecture, HA guides, setup, telemetry, changelog
```

---

## HA Test Scenarios

### HANA Database HA (`ha_db_hana`)

| Scenario | Task File |
|----------|-----------|
| HA configuration validation (online/offline) | `ha-config.yml`, `ha-config-offline.yml` |
| Azure Load Balancer validation | `azure-lb.yml` |
| Resource migration | `resource-migration.yml` |
| Primary node crash / kill | `primary-node-crash.yml`, `primary-node-kill.yml` |
| Primary indexserver crash / echo-b | `primary-crash-index.yml`, `primary-echo-b.yml` |
| Secondary node kill / indexserver crash / echo-b | `secondary-node-kill.yml`, `secondary-crash-index.yml`, `secondary-echo-b.yml` |
| Network / HANA-shared isolation | `block-network.yml`, `block-hana-shared.yml` |
| Filesystem freeze (ANF) | `fs-freeze.yml` |
| SBD fencing | `sbd-fencing.yml` |

### SAP Central Services HA (`ha_scs`)

| Scenario | Task File |
|----------|-----------|
| HA configuration validation (online/offline) | `ha-config.yml`, `ha-config-offline.yml` |
| Azure Load Balancer / SAP control validation | `azure-lb.yml`, `sapcontrol-config.yml` |
| ASCS migration / node crash | `ascs-migration.yml`, `ascs-node-crash.yml` |
| Kill message/enqueue/replication server | `kill-message-server.yml`, `kill-enqueue-server.yml`, `kill-enqueue-replication.yml` |
| Kill SAPStartSrv process | `kill-sapstartsrv-process.yml` |
| Manual restart / failover to node | `manual-restart.yml`, `ha-failover-to-node.yml` |
| Network isolation | `block-network.yml` |

### HANA Topologies Supported

- **Scale-Up** -- classic two-node HSR (default)
- **Scale-Out HSR** -- multi-node with system replication
- **Scale-Out Standby** -- multi-node with standby nodes

### HANA SR Providers

- **SAPHanaSR** -- classic provider
- **SAPHanaSR-angi** -- next-generation provider (different resource ID discovery)

---

## Key Design Patterns

Follow these established patterns when contributing:

| Pattern | Implementation | Location |
|---------|---------------|----------|
| **Protocol (structural typing)** | `ExecutorProtocol` for dependency inversion | `core/execution/executor.py` |
| **ABC + Template Method** | `SapAutomationQA`, `BaseClusterStatusChecker.run()` with abstract hooks | `module_utils/` |
| **State Machine** | `Job` model with explicit transitions (`start()`, `complete()`, `fail()`, `cancel()`) | `core/models/job.py` |
| **Repository** | `JobStore`, `ScheduleStore` -- SQLite-backed, clean interface | `core/storage/` |
| **Factory + Singleton** | `LoggerFactory.get_logger()`, `ObservabilityContextManager` | `core/observability/` |
| **Context Manager (scoped)** | `ObservabilityScope`, `ExecutionScope` -- auto context push/pop | `core/observability/context.py` |
| **ContextVar (async-safe)** | `ContextVarProvider` for thread-safe context propagation + correlation IDs | `core/observability/context.py` |
| **Strategy** | `Collector` hierarchy -- `CommandCollector`, `AzureDataParser`, `FileSystemCollector` | `module_utils/collector.py` |
| **Module-level DI** | API routes wired via `set_job_store()` etc. during FastAPI lifespan | `api/routes/` |
| **Async worker + event queue** | `JobWorker` with `asyncio.create_task()` and SSE event streaming | `core/execution/worker.py` |
| **Background batching** | Telemetry handlers use threaded queues for async batch delivery | `core/observability/telemetry_handlers.py` |
| **Workspace locking** | One active job per workspace enforced in `JobWorker.submit_job()` | `core/execution/worker.py` |
| **Immutable value objects** | `ContextData`, `TelemetryConfig` -- frozen dataclasses | `core/models/`, `core/observability/` |
| **Lifespan** | FastAPI `asynccontextmanager` for service initialization/teardown | `api/app.py` |
| **OS-family dispatching** | Commands differ for SUSE (`crm`) vs RHEL (`pcs`) via filtered command maps | `module_utils/commands.py` |
| **Command sanitization** | `DANGEROUS_COMMANDS` blocklist in `CommandCollector` | `module_utils/collector.py` |

---

## API Reference (Quick)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/healthz` | Health check |
| `GET` | `/api/v1/jobs` | List jobs (filter: workspace, status, active) |
| `POST` | `/api/v1/jobs` | Create and submit a job |
| `GET` | `/api/v1/jobs/{id}` | Get job details |
| `POST` | `/api/v1/jobs/{id}/cancel` | Cancel a running job |
| `GET` | `/api/v1/jobs/{id}/events` | SSE event stream |
| `GET` | `/api/v1/jobs/{id}/log` | Plain-text Ansible log (`?tail=N`) |
| `POST` | `/api/v1/schedules` | Create cron schedule |
| `GET` | `/api/v1/schedules` | List schedules |
| `PATCH` | `/api/v1/schedules/{id}` | Update schedule |
| `DELETE` | `/api/v1/schedules/{id}` | Delete schedule |
| `POST` | `/api/v1/schedules/{id}/trigger` | Trigger schedule immediately |
| `GET` | `/api/v1/workspaces` | List available workspaces |

---

## Coding Standards

> **FIRST ACTION RULE — applies before writing any code:**
>
> Before implementing anything, search the codebase for existing code that
> does what you need. Follow this decision tree:
>
> 1. **Does a function/class/method already do this?** → Use it directly.
> 2. **Does something similar exist but isn't reusable?** → Refactor it
>    into a reusable form (extract to base class, utility, or shared module),
>    then use the refactored version.
> 3. **Nothing exists?** → Create it in the most reusable location
>    (base class > utility module > inline), not buried in a specific module.
>
> This is not optional. Every PR review will check: "Did you search for
> existing code before writing new code? If similar code exists elsewhere,
> why wasn't it reused or extracted?"

### Python — Hard Rules

These are not suggestions. Violating any of these will fail CI or code review.

#### 1. Formatting — black, line-length 100

Every Python file MUST pass `black --check` with `line_length = 100`.
Before saving any file, mentally verify lines do not exceed 100 characters.
If a function call or definition is too long, break it:

```python
# WRONG — exceeds 100 chars
result = self.execute_command_subprocess(command, timeout=30, check_return_code=True, capture_output=True)

# RIGHT — break at logical points
result = self.execute_command_subprocess(
    command,
    timeout=30,
    check_return_code=True,
    capture_output=True,
)
```

#### 2. Type annotations — every signature, no exceptions

Every function parameter and return type MUST have a type annotation.
This includes private methods, test functions, and callbacks.

```python
# WRONG
def collect_lvm_volumes(self):
    ...

def process_result(data, callback):
    ...

# RIGHT
def collect_lvm_volumes(self) -> list[dict[str, str]]:
    ...

def process_result(
    data: dict[str, Any],
    callback: Callable[[str], None],
) -> ProcessResult:
    ...
```

**`Any` usage**: Only permitted when the type is genuinely unknown (e.g., Ansible
module params). Add a comment explaining why:

```python
def collect(self, check: str, context: dict[str, Any]) -> Any:
    # Returns Any because collector subclasses return different types
    ...
```

#### 3. Imports — top of file, never inline

All imports at the top of the file. No imports inside functions or methods.

The ONLY exception is the Ansible dual-import fallback pattern:

```python
# This is the ONLY acceptable non-top-level import pattern
try:
    from ansible.module_utils.sap_automation_qa import SapAutomationQA
except ImportError:
    from src.module_utils.sap_automation_qa import SapAutomationQA
```

Anything else inline is a violation:
```python
# WRONG — never do this
def my_function() -> None:
    import json  # ❌ inline import
    from pathlib import Path  # ❌ inline import
```

#### 4. Docstrings — sphinx-style on all public interfaces

Every public class, method, and function MUST have a sphinx-style docstring.
Include `:param:`, `:returns:`, and `:raises:` fields.

```python
def execute_command(
    self,
    cmd: str,
    timeout: int = 30,
) -> CommandResult:
    """Execute a shell command with timeout.

    :param cmd: The shell command to execute.
    :param timeout: Maximum seconds to wait. Defaults to 30.
    :returns: A CommandResult with stdout, stderr, and return code.
    :raises TimeoutError: If the command exceeds the timeout.
    :raises CommandExecutionError: If the command fails to start.
    """
```

Private methods (`_prefixed`) should have a brief docstring but do not
require `:param:` / `:returns:` fields.

#### 5. Function arguments — max 5

No function may accept more than 5 parameters (excluding `self`/`cls`).
If you need more, group related parameters into a dataclass or TypedDict:

```python
# WRONG — 8 args
def _parse_filesystem_data(
    self, mount_point, fs_type, device, size, used, avail, options, source,
) -> FilesystemData:
    ...

# RIGHT — group into a typed container
@dataclass(frozen=True)
class RawFilesystemEntry:
    mount_point: str
    fs_type: str
    device: str
    size: str
    used: str
    avail: str
    options: str
    source: str

def _parse_filesystem_data(self, entry: RawFilesystemEntry) -> FilesystemData:
    ...
```

#### 6. Module size — max 1000 lines

No Python module may exceed 1000 lines. If it does, split it by
responsibility. Use the single-responsibility principle.

#### 7. Nesting — max 3 levels

No code block may be nested more than 3 levels deep. If you find yourself
at 4+ levels, extract a helper method.

```python
# WRONG — 4 levels deep
for node in nodes:
    if node.active:
        for resource in node.resources:
            if resource.status == "started":
                process(resource)  # ❌ level 4

# RIGHT — extract
def _get_active_resources(self, nodes: list[Node]) -> list[Resource]:
    return [
        resource
        for node in nodes if node.active
        for resource in node.resources if resource.status == "started"
    ]
```

#### 8. No print() — use StructuredLogger

Never use `print()` or raw `logging` in production code. Use `StructuredLogger`.
The only exception is CLI entry points (`filter_tests.py main()`).

```python
# WRONG
print(f"Processing node {node_name}")
logging.info("Job completed")

# RIGHT
self.logger.info("Processing node", node_name=node_name)
logger.info(ServiceEvent.JOB_COMPLETED, job_id=job.id)
```

#### 9. Error handling — explicit, typed exceptions

Never catch bare `Exception` without re-raising or wrapping. Use the
project's exception hierarchy:

```python
# WRONG
try:
    result = execute()
except Exception:
    pass  # ❌ swallowed

# RIGHT
try:
    result = execute()
except CommandExecutionError as exc:
    logger.error("Command failed", error=str(exc))
    raise
except TimeoutError as exc:
    raise ExecutionError(f"Timed out: {exc}") from exc
```

#### 10. Constants — no magic strings or numbers

Use enums from `enums.py` or module-level constants. Never embed raw strings
for states, statuses, or configuration keys:

```python
# WRONG
if status == "started":
    ...

# RIGHT
if status == TestStatus.PASSED:
    ...
```

### Ansible — Hard Rules

1. Every task MUST have a descriptive `name:` field.
2. Shell tasks MUST use `set -o pipefail`, `executable: /bin/bash`, `changed_when: false` (read-only).
3. Use `become: true` / `become_user: root` explicitly where required.
4. Use `block/rescue/always` for error handling. Set `failed_when` explicitly.
5. OS dispatching: Use Jinja2 filters on `commands` list with `ansible_os_family | upper`.
6. `ansible-lint` must pass with zero errors.

### Testing — Hard Rules

1. Coverage: 85% minimum enforced (`--cov-fail-under=85`). No exceptions.
2. API tests: `httpx.AsyncClient` with FastAPI test client, `pytest-asyncio` auto mode.
3. Mock external deps: Azure, SSH, subprocess, network. Never call real services.
4. Test failure paths: Every function with error handling needs a test that triggers it.
5. Fixtures: Shared via `conftest.py`. No test-to-test coupling.
6. Assertions: Every test must assert something. No assertion-free tests.

### Shell Scripts — Hard Rules

1. Internal functions: `_prefixed`. Public functions: unprefixed.
2. Check tool availability: `command -v {tool}` before using it.
3. Validate inputs before acting. Provide clear error messages on failure.

---

## Enterprise-Grade Defaults (mandatory)

All code must meet these non-negotiable standards:

### Production Readiness

- Safe defaults, clear failure modes, strict typing, deterministic behavior.
- Typed exception hierarchy (`ExecutionError`, `WorkspaceLockError`, `JobNotFoundError`, etc.).
- Pydantic models for API boundaries; frozen dataclasses for internal value objects.

### Observability

- Structured logging via `StructuredLogger` -- JSON for production, color-coded console for dev.
- Correlation IDs (`X-Correlation-ID`) propagated through all layers via `ContextVar`.
- Event-based logging: `ServiceEvent` and `ExecutionEvent` with automatic context population.
- RotatingFileHandler (10 MB, 5 backups) for persistent log storage.
- Multi-destination telemetry: Azure Log Analytics (shared key or MSI) + Azure Data Explorer (Kusto).

### Resilience

- Timeouts on subprocess calls (`execute_command_subprocess` with configurable timeout).
- Workspace locking (one active job per workspace; prevents concurrent execution).
- Crash recovery on worker startup (detects and marks orphaned running jobs).
- Graceful job cancellation via subprocess signal handling.
- SSH credential provisioning with auto-detect (Key Vault MSI or local workspace files).

### Security

- Least privilege: non-root Docker user (`appuser:1000`).
- No plaintext secrets: Azure Key Vault integration for SSH credentials.
- Input validation: Pydantic models, command sanitization (`DANGEROUS_COMMANDS` blocklist).
- CORS configuration via environment variable (`CORS_ORIGINS`).
- Hardened CI: `step-security/harden-runner`, pinned action SHAs, Trivy scanning, OSSF Scorecard.

### Performance

- SQLite WAL mode for concurrent read/write.
- Indexed queries on `workspace_id`, `status`, `schedule_id`, `created_at`.
- Threaded background batching for telemetry delivery.
- `ThreadPoolExecutor` for parallel configuration checks.
- Async job execution with `asyncio.create_task()`.

---

## Object-Oriented Design — Hard Rules

Code reuse through abstraction is mandatory. Every new feature must evaluate
whether it can extend an existing class, implement an existing Protocol, or
extract shared logic into a base class. **Duplication is a defect.**

### Rule 1: Search → Reuse → Extract → Create (in that order)

This is the most important rule. Before writing ANY new class or function:

**Step 1 — Search**: Look for existing code that does what you need.
Use `search/codebase`, `search/usages`, `grep` to find related functions,
classes, and patterns.

**Step 2 — Reuse**: If you find existing code that does what you need, use it.
Import it, call it, extend it.

**Step 3 — Extract**: If you find similar code that ISN'T reusable (e.g., it's
buried inside another function, or it mixes concerns), refactor it:
- Extract the shared logic into a base class method, utility function, or
  shared module
- Update the original code to use the extracted version
- Then use the extracted version in your new code too

**Step 4 — Create**: Only if nothing exists. Place it in the most reusable
location — base class > utility module > inline.

This codebase has established hierarchies — search these first:

| Need | Existing Abstraction | Location |
|------|---------------------|----------|
| Custom Ansible module | `SapAutomationQA` ABC | `module_utils/sap_automation_qa.py` |
| Cluster status check | `BaseClusterStatusChecker` | `module_utils/get_cluster_status.py` |
| Pacemaker CIB validation | `BaseHAClusterValidator` | `module_utils/get_pcmk_properties.py` |
| Data collection | `Collector` ABC | `module_utils/collector.py` |
| Filesystem data gathering | `FileSystemCollector` | `module_utils/filesystem_collector.py` |
| Async job execution | `ExecutorProtocol` | `core/execution/executor.py` |
| Workspace storage backend | `WorkspaceBackend` Protocol | `core/services/workspace_backend.py` |
| Structured logging | `LogFormatter` ABC | `core/observability/logger.py` |
| Remote log shipping | `_BaseRemoteLogHandler` | `core/observability/telemetry_handlers.py` |
| Context propagation | `IContextProvider` Protocol | `core/observability/context.py` |
| Evidence collection | `CollectorStrategy` Protocol | `core/execution/evidence_collector.py` |

```python
# WRONG — new module that does cluster checks from scratch
class MyNewClusterCheck:
    def __init__(self, module):
        self.module = module
    def run(self):
        # reimplements command execution, result parsing, etc.
        ...

# RIGHT — extend the existing ABC
class MyNewClusterCheck(BaseClusterStatusChecker):
    """Check for new cluster scenario.

    Extends BaseClusterStatusChecker to reuse command execution,
    OS-family dispatching, and result formatting.
    """

    def _parse_cluster_output(self, output: str) -> dict[str, str]:
        # Only implement the part that's different
        ...
```

### Rule 2: ABC for "is-a" hierarchies with shared behavior

Use ABCs when subclasses share implementation (template method pattern).
The ABC defines the skeleton; subclasses override specific steps.

This codebase uses this pattern extensively — follow it:

```python
class BaseClusterStatusChecker(SapAutomationQA):
    """Template method: run() calls abstract hooks in sequence."""

    def run(self) -> dict[str, str]:
        """Execute cluster check — DO NOT OVERRIDE."""
        raw = self._collect_data()       # concrete
        parsed = self._parse_output(raw)  # abstract — subclass implements
        return self._format_result(parsed) # concrete

    @abstractmethod
    def _parse_output(self, raw: str) -> dict[str, Any]:
        """Parse raw cluster output. Subclass MUST implement."""
        ...
```

**When to use ABC**: You have 2+ classes that share >50% of their logic
and differ in specific steps. Extract the shared logic into an ABC.

### Rule 3: Protocol for structural typing (duck typing with safety)

Use `Protocol` when you need an interface for dependency injection or
testing, but the implementations don't share logic.

```python
class ExecutorProtocol(Protocol):
    """Any object that can execute Ansible jobs."""

    def execute(self, playbook: str, extra_vars: dict[str, str]) -> int:
        ...

    def cancel(self, job_id: str) -> None:
        ...
```

**When to use Protocol vs ABC**:
- Protocol: consumer needs an interface, implementations are independent
- ABC: implementations share behavior that should be written once

### Rule 4: Encapsulate external systems behind adapters

Never call Azure SDKs, subprocess, SSH, or HTTP directly from business logic.
Wrap them in adapter classes that can be mocked:

```python
# WRONG — Azure SDK call in business logic
class JobWorker:
    async def submit_job(self, request):
        credential = DefaultAzureCredential()  # ❌ direct SDK call
        client = SecretClient(vault_url, credential)
        key = client.get_secret("ssh-key")
        ...

# RIGHT — inject an adapter
class JobWorker:
    def __init__(self, credential_provider: SshCredentialProvider) -> None:
        self._credentials = credential_provider

    async def submit_job(self, request: JobRequest) -> Job:
        key = await self._credentials.get_ssh_key(request.workspace_id)
        ...
```

### Rule 5: Extract shared logic — DRY enforcement

When you find yourself writing similar code in 2+ places, extract it
immediately. Common extraction targets in this codebase:

| Duplication Signal | Extraction Pattern |
|-------------------|-------------------|
| Same command execution + error handling | Add to `SapAutomationQA.execute_command_subprocess()` |
| Same XML/JSON parsing logic | Create a parser method in the base class |
| Same OS-family conditional | Use the `commands.py` dispatch pattern |
| Same validation logic (string/numeric/list) | Add to the validation strategy in `configuration_check_module.py` |
| Same test setup (mock module, mock commands) | Add fixture to `conftest.py` |

```python
# WRONG — duplicated validation in two modules
# Module A:
def validate_value(self, expected, actual):
    if expected == actual:
        return {"status": "PASSED"}
    return {"status": "FAILED", "message": f"Expected {expected}, got {actual}"}

# Module B:
def check_value(self, exp, act):
    if exp == act:
        return {"result": "PASSED"}
    return {"result": "FAILED", "detail": f"Want {exp}, have {act}"}

# RIGHT — extract to base class
class SapAutomationQA(ABC):
    def _validate_expected_value(
        self,
        expected: str,
        actual: str,
        context: str,
    ) -> ValidationResult:
        """Compare expected vs actual and return a standardized result."""
        ...
```

### Rule 6: Composition for cross-cutting concerns

When behavior needs to be shared across unrelated classes (not "is-a"),
use composition — inject collaborators rather than inheriting.

```python
# WRONG — multiple inheritance for logging + validation
class MyModule(SapAutomationQA, LoggingMixin, ValidationMixin):
    ...

# RIGHT — compose collaborators
class MyModule(SapAutomationQA):
    def __init__(self, module: AnsibleModule) -> None:
        super().__init__(module)
        self._validator = PropertyValidator()  # composed
```

### Rule 7: State machines for workflow objects

Model any object with lifecycle states as an explicit state machine with
typed transitions. Never use string comparisons for state checks.

```python
class Job:
    """Explicit state machine — see core/models/job.py."""

    def start(self) -> None:
        if self.status != JobStatus.PENDING:
            raise InvalidStateTransition(self.status, JobStatus.RUNNING)
        self.status = JobStatus.RUNNING

    @property
    def is_terminal(self) -> bool:
        return self.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
```

### Decision Checklist — Before Writing Any New Class

Ask these questions in order:

1. **Does an existing class already do this?** → Extend it.
2. **Does it share >50% logic with an existing class?** → Extract an ABC, inherit.
3. **Does it need to satisfy an interface for DI/testing?** → Implement a Protocol.
4. **Does it wrap an external system?** → Write an adapter, inject it.
5. **Is similar logic duplicated elsewhere?** → Extract to a shared base or utility.
6. **None of the above?** → Create a new class with single responsibility.

---

## Coding Partnership Rules

Follow these at all times:

1. **Be critical, not agreeable**
   - Flag missing context, risky designs, and incorrect SAP/Azure assumptions.
   - Provide counterpoints and alternatives -- especially for cluster behavior edge cases.

2. **Apply best design principles**
   - SOLID, DRY, KISS, clear separation of concerns.
   - Maintainability > cleverness. Small units > god-objects.
   - Production SAP constraints: reliability, observability, rollback capability, operability.

3. **Cover edge cases thoroughly**
   - Empty/invalid inputs, boundary conditions, transient Azure failures.
   - Cluster-specific: partial outages, quorum loss, fencing misconfiguration, split-brain,
     storage throttling, DNS/MI/IMDS hiccups, SAPHanaSR vs SAPHanaSR-angi differences.

4. **Output style**
   - Concise, minimal yet complete. Black-formatted, pylint-clean, <=100-char lines.
   - Include types, docstrings, explicit exceptions. Show tests when relevant.
   - Ansible tasks: proper `name`, `become`, `changed_when`, `failed_when`, `block/rescue`.

5. **Collaboration stance**
   - Act as a Principal software reviewer. Push back on weak requests or ambiguous scope.
   - Offer 2-3 viable designs when trade-offs exist, with crisp pros/cons.
   - When modifying HA test scenarios, consider both SUSE and RHEL code paths.

---

## File-Specific Guidance

| When editing... | Remember to... |
|----------------|----------------|
| `src/api/routes/*.py` | Use dependency injection via module-level setters; return Pydantic models; document endpoints |
| `src/core/models/*.py` | Validate state transitions; use frozen dataclasses for value objects; include `is_terminal` helpers |
| `src/core/execution/worker.py` | Respect workspace locking; handle crash recovery; propagate events via `AsyncGenerator` |
| `src/core/observability/*.py` | Maintain correlation ID propagation; use `StructuredLogger` not `print`/raw `logging` |
| `src/module_utils/*.py` | Extend ABCs properly; keep command constants OS-family-aware; sanitize inputs |
| `src/modules/*.py` | Follow `AnsibleModule` + `DOCUMENTATION` string pattern; return standardized result dicts |
| `src/roles/*/tasks/*.yml` | Use `block/rescue/always`; include `test-case-setup.yml`; post telemetry; handle both OS families |
| `tests/` | Maintain 85% coverage; use `conftest.py` fixtures; mock external deps; test failure paths |
| `scripts/*.sh` | Use `_prefixed` internal functions; validate tool availability; provide colored output |
| `deploy/` | Keep non-root; pin base images; test healthcheck; preserve volume mounts |

---

## CI/CD Pipeline

| Workflow | Trigger | Checks |
|----------|---------|--------|
| Code Coverage | push, PR | pytest `--cov-fail-under=85`, pylint `--fail-under=9`, black `--check` |
| Ansible Lint | push, PR | `ansible-lint src/` |
| Docker Build | push (main/dev), PR | Multi-stage build; optional ACR push via OIDC |
| CodeQL | push, PR, weekly | JavaScript + Python security analysis |
| Trivy | PR, merge_group | Filesystem vulnerability scanning |
| Dependency Review | PR | Dependency vulnerability review |
| OSSF Scorecard | push, PR, weekly | Supply-chain security scoring |

---

## Common Workflows

### Running tests locally

```bash
source .venv/bin/activate
pytest tests/ --cov=src --cov-fail-under=85 -v
```

### Starting the full stack (API + React)

```bash
# Backend: uvicorn on port 8000
PYTHONPATH=src uvicorn api.app:app --reload --host 0.0.0.0 --port 8000

# Frontend: React on port 3000
cd client && npm start
```

### Running a direct Ansible test

```bash
./scripts/sap_automation_qa.sh --test_groups DatabaseHighAvailability --test_cases ha-config
```

### Docker deployment

```bash
cd deploy && docker compose up -d
```

---

## Pre-Completion Checklist

> **MANDATORY** — Before declaring any code task complete, verify ALL of the following.
> No exceptions. Run the commands, check the output, fix failures.

### Python Code Quality

1. **Format**: `black --check src/ tests/` — zero reformatting needed.
   If files need reformatting, run `black src/ tests/` first, then verify.
   > Ref: [black documentation](https://black.readthedocs.io/en/stable/)

2. **Lint**: `pylint src/{changed_modules} --fail-under=9` — score 9.0 or higher.
   Fix all errors and warnings before declaring done.
   > Ref: [pylint documentation](https://pylint.readthedocs.io/en/stable/)

3. **Type annotations**: Every function parameter and return type MUST have a type
   annotation. No `Any` without explicit justification in a comment. Use `Protocol`
   for structural typing, not `ABC` unless there is a true "is-a" hierarchy.
   > Ref: [PEP 484](https://peps.python.org/pep-0484/), [typing module](https://docs.python.org/3/library/typing.html)

4. **Docstrings**: Every public class, method, and function MUST have a sphinx-style
   docstring with `:param:`, `:returns:`, and `:raises:` fields. Example:

   ```python
   def execute_command(self, cmd: str, timeout: int = 30) -> CommandResult:
       """
       Execute a shell command with timeout.

       :param cmd: The shell command to execute.
       :param timeout: Maximum seconds to wait. Defaults to 30.
       :returns: A CommandResult with stdout, stderr, and return code.
       :raises TimeoutError: If the command exceeds the timeout.
       :raises CommandExecutionError: If the command fails to start.
       """
   ```

5. **Imports**: All imports at the top of the file. No inline or lazy imports inside
   functions or methods. Ansible modules use the dual-import fallback pattern only:
   ```python
   try:
       from ansible.module_utils.sap_automation_qa import SapAutomationQA
   except ImportError:
       from src.module_utils.sap_automation_qa import SapAutomationQA
   ```

6. **Tests**: `pytest tests/ --cov=src --cov-fail-under=85 -v` — all tests pass,
   coverage at or above 85%. After writing or modifying tests, run them and verify.

7. **Ansible lint**: `ansible-lint src/` — passes with zero errors when any YAML
   files under `src/roles/` or `src/playbook_*.yml` are changed.

8. **Type checking**: Zero Pylance/pyright errors in changed files.

### Evidence-Based Development

9. **Documentation references**: Every non-trivial technical decision, tool usage,
   or behavioral claim MUST cite an official public documentation source.
   Acceptable sources: GitHub Docs, Microsoft Learn, Python Docs, Ansible Docs,
   SAP Help Portal, SUSE/Red Hat documentation. Include URLs in code comments
   for non-obvious patterns.

### Verification Order

Run checks in this order — stop and fix at the first failure:

```bash
# 1. Format
black --check src/ tests/

# 2. Lint
pylint src/ --fail-under=9

# 3. Tests + coverage
pytest tests/ --cov=src --cov-fail-under=85 -v

# 4. Ansible lint (if applicable)
ansible-lint src/

# 5. Type check (if pyright/pylance available)
pyright src/
```

---

## Copilot CLI Skills

This repo includes skills in `.github/skills/` that provide guided workflows.
Skills activate automatically based on prompt context, or can be invoked directly
with the `/` prefix (e.g., `/test-runner`).

| Skill | When to Use |
|-------|-------------|
| `/setup-guide` | Setup, installation, Docker deployment, `vars.yaml` configuration |
| `/workspace-validator` | Validate workspace config, troubleshoot workspace issues |
| `/workspace-creator` | Create new workspace, onboard SAP system |
| `/test-runner` | Run tests, execute HA tests, trigger configuration checks |
| `/test-result-analyzer` | Analyze test failures, interpret test output, read test logs |
| `/dev-workflow` | Start dev workflow for an issue, create spec, review plan, validate |
