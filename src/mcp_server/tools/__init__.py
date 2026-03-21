# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""SAP MCP tools — split by domain for the three-agent architecture.

Submodules register ``@mcp.tool()`` decorators on import:

- :mod:`triage` — evidence collection, analysis, knowledge, workspace lookup.
- :mod:`staf` — test execution, job management, log retrieval.
- :mod:`ops` — schedule CRUD, triggering, schedule-job listing.
"""

import src.mcp_server.tools.triage  # noqa: F401
import src.mcp_server.tools.staf  # noqa: F401
import src.mcp_server.tools.ops  # noqa: F401
