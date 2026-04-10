# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""SAP MCP tools — split by domain.

Submodules register ``@mcp.tool()`` decorators on import:

- :mod:`schedule_ops` — schedule CRUD, triggering, schedule-job listing.
- :mod:`workspace_ops` — workspace listing and detail lookup.
- :mod:`jobs_ops` — job status, results, listing, cancellation, events, logs.
- :mod:`staf` — test execution (submit STAF tests).
- :mod:`retrieval` — knowledge base search (rules, playbooks, patterns).
- :mod:`triage_evidence` — evidence catalog, collection, and execution.
- :mod:`triage_analysis` — rule-based analysis and report generation.
- :mod:`triage_commands` — log search and investigation feedback.
"""

import src.mcp_server.tools.schedule_ops  # noqa: F401
import src.mcp_server.tools.workspace_ops  # noqa: F401
import src.mcp_server.tools.jobs_ops  # noqa: F401
import src.mcp_server.tools.staf  # noqa: F401
import src.mcp_server.tools.retrieval  # noqa: F401
import src.mcp_server.tools.triage_evidence  # noqa: F401
import src.mcp_server.tools.triage_analysis  # noqa: F401
import src.mcp_server.tools.triage_commands  # noqa: F401
