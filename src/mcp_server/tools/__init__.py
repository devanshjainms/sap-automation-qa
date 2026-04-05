# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""SAP MCP tools — split by domain.

Submodules register ``@mcp.tool()`` decorators on import:

- :mod:`schedule_ops` — schedule CRUD, triggering, schedule-job listing.
- :mod:`workspace_ops` — workspace listing and detail lookup.
- :mod:`jobs_ops` — job status, results, listing, cancellation, events, logs.
- :mod:`staf` — test execution (submit STAF tests).
- :mod:`retrieval` — knowledge base search (rules, playbooks, patterns).
- :mod:`triage_analyzer` — evidence collection, analysis, reporting,
  command execution, log search, investigation feedback.
"""

import src.mcp_server.tools.schedule_ops  # noqa: F401
import src.mcp_server.tools.workspace_ops  # noqa: F401
import src.mcp_server.tools.jobs_ops  # noqa: F401
import src.mcp_server.tools.staf  # noqa: F401
import src.mcp_server.tools.retrieval  # noqa: F401
import src.mcp_server.tools.triage_analyzer  # noqa: F401
