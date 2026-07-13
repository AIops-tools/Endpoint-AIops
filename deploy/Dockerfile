# Neutral OCI image for endpoint-aiops — a reproducible runtime for the governed
# managed-endpoint tools + CLI. Vendor-neutral: it installs the published package
# and nothing vendor-specific. Runs as a non-root user; state under /state.
#
# Build:  docker build -t <registry>/endpoint-aiops:0.1.0 -f deploy/Dockerfile .
# The MCP server speaks stdio (the MCP client launches it), so run it attached:
#   podman run -i --rm -v endpoint-state:/state <image> endpoint-aiops mcp
# Or use the CLI directly:
#   podman run --rm -v endpoint-state:/state <image> endpoint-aiops overview
FROM python:3.12-slim

# Install the published package (pin at build time for reproducibility).
ARG ENDPOINT_AIOPS_VERSION=
RUN pip install --no-cache-dir "endpoint-aiops${ENDPOINT_AIOPS_VERSION:+==$ENDPOINT_AIOPS_VERSION}"

# Non-root runtime; audit/policy/undo store + config live under ENDPOINT_AIOPS_HOME.
RUN useradd --create-home --uid 10001 app
USER app
ENV ENDPOINT_AIOPS_HOME=/state
VOLUME ["/state"]

ENTRYPOINT ["endpoint-aiops"]
CMD ["--help"]
