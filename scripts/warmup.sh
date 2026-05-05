#!/usr/bin/env bash
# Post-startup warmup for SamCart Analytics.
# Polls Streamlit's health endpoint until ready, then hits the main page
# to warm the OS page cache for Python bytecode files.
# Run by systemd ExecStartPost — blocks until ready so deploys know
# the service is actually accepting traffic before returning.

set -euo pipefail

PORT=8501
TIMEOUT=90
HEALTH_URL="http://localhost:${PORT}/_stcore/health"
MAIN_URL="http://localhost:${PORT}/"

echo "Waiting for Streamlit to be ready on port ${PORT}..."

for i in $(seq 1 "${TIMEOUT}"); do
    if curl -sf "${HEALTH_URL}" > /dev/null 2>&1; then
        echo "Streamlit healthy after ${i}s — warming up..."
        # Hit the main page to pre-load static assets and warm OS page cache
        curl -s "${MAIN_URL}" > /dev/null 2>&1 || true
        echo "Warmup complete."
        exit 0
    fi
    sleep 1
done

echo "Streamlit did not become ready within ${TIMEOUT}s" >&2
exit 1
