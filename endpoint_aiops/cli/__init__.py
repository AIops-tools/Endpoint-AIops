"""CLI package for endpoint-aiops.

Re-exports ``app`` so the pyproject entry point
``endpoint-aiops = "endpoint_aiops.cli:app"`` works unchanged.
"""

from endpoint_aiops.cli._root import app

__all__ = ["app"]
