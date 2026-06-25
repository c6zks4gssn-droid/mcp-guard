FROM python:3.12-slim

LABEL org.opencontainers.image.title="mcp-guard"
LABEL org.opencontainers.image.description="MCP gateway — auth, rate limits, spend caps, audit logs"
LABEL org.opencontainers.image.source="https://github.com/c6zks4gssn-droid/mcp-guard"
LABEL org.opencontainers.image.license="Apache-2.0"

WORKDIR /app

# Install without yaml extra — pyyaml is already in slim
COPY pyproject.toml README.md ./
COPY mcp_guard/ ./mcp_guard/

RUN pip install --no-cache-dir .

# Default config location
ENV MCP_GUARD_CONFIG=/etc/mcp-guard/config.yaml

# Config volume
VOLUME ["/etc/mcp-guard"]

# stdio gateway — reads from stdin, writes to stdout
ENTRYPOINT ["mcp-guard"]
CMD ["serve", "--config", "/etc/mcp-guard/config.yaml"]

# For HTTP mode: docker run -p 8080:8080 mcp-guard serve-http -c /etc/mcp-guard/config.yaml -p 8080
EXPOSE 8080