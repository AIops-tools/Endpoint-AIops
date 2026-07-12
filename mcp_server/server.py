"""MCP server wrapping endpoint-aiops operations (stdio transport).

Thin adapter layer: each ``@mcp.tool()`` function (in ``mcp_server/tools/``)
delegates to the ``endpoint_aiops`` ops package and is wrapped with the
endpoint-aiops ``@governed_tool`` harness (audit / budget / undo / risk-tier).

Standalone, self-governed managed-endpoint operations (preview).
For endpoint-management fleets (thin clients / VDI / managed devices).

Source: https://github.com/AIops-tools/Endpoint-AIops
License: MIT
"""

import logging

from mcp_server._shared import _safe_error, mcp, tool_errors

# Importing the tool modules registers every @mcp.tool() onto the shared
# `mcp` instance. Order does not matter; each module is self-contained.
from mcp_server.tools import (  # noqa: F401 — side effects
    drift,
    inventory,
    remediation,
    sessions,
)

__all__ = ["mcp", "main", "_safe_error", "tool_errors"]


def main() -> None:
    """Run the MCP server over stdio."""
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport="stdio")
