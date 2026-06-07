# syntax=docker/dockerfile:1

# Container image for running APL as a remote HTTP policy server (`apl serve`).
# The library itself installs with plain `pip install agent-policy-layer`; this
# image is only for deploying the server component.
#
#   docker build -t apl .
#   docker run --rm -p 8080:8080 -v "$PWD/policies:/policies:ro" \
#     apl serve /policies/my_policy.py --http 8080 --host 0.0.0.0
#
# Pass --host 0.0.0.0 so the server is reachable from outside the container
# (APL binds 127.0.0.1 by default for safety).

FROM python:3.12-slim AS builder
WORKDIR /src
RUN pip install --no-cache-dir build
COPY . .
RUN python -m build --wheel --outdir /dist

FROM python:3.12-slim AS runtime
LABEL org.opencontainers.image.title="agent-policy-layer" \
      org.opencontainers.image.description="Portable, composable policies for AI agents — HTTP policy server" \
      org.opencontainers.image.source="https://github.com/nimonkaranurag/agentpolicylayer" \
      org.opencontainers.image.licenses="MIT"

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 apl
WORKDIR /home/apl

COPY --from=builder /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -rf /tmp/*.whl

USER apl
EXPOSE 8080

# Liveness against the server's health endpoint (only meaningful when the
# container is run as `serve ... --http 8080`).
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/health').status==200 else 1)" || exit 1

ENTRYPOINT ["apl"]
CMD ["--help"]
