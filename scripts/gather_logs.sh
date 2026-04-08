#!/bin/bash
# Gather logs from all containers for debugging.
# Usage: ./scripts/gather_logs.sh [minutes]  (default: 5 minutes)

MINS=${1:-5}
OUT="data/logs/debug-$(date +%Y%m%d-%H%M%S).log"
mkdir -p "$(dirname "$OUT")"

{
  echo "=== Debug log gathered at $(date -u) — last ${MINS}m ==="
  echo ""

  for c in sap-qa-service sap-mcp-server sap-ui sap-azure-mcp sap-ollama; do
    echo "──────────────────────────────────────────"
    echo "CONTAINER: $c"
    echo "──────────────────────────────────────────"
    docker logs "$c" --since "${MINS}m" 2>&1
    echo ""
  done

  echo "=== Structured errors ==="
  for c in sap-qa-service sap-mcp-server sap-ui sap-azure-mcp sap-ollama; do
    errs=$(docker logs "$c" --since "${MINS}m" 2>&1 | grep -c '"level": "ERROR"\|"level": "WARNING"' 2>/dev/null || echo "0")
    echo "  $c: $errs"
  done

  echo ""
  echo "=== Container status ==="
  docker ps --format "{{.Names}}: {{.Status}}" 2>/dev/null

  echo ""
  echo "=== Recent AG-UI requests ==="
  docker logs sap-qa-service --since "${MINS}m" 2>&1 | grep -E 'AG-UI (run|done):' | tail -20

  echo ""
  echo "=== Conversation persistence ==="
  docker logs sap-qa-service --since "${MINS}m" 2>&1 | grep -E 'Persist:|Could not save|Cleaned up' | tail -10

} > "$OUT" 2>&1

echo "Logs saved to $OUT ($(wc -l < "$OUT") lines)"
echo "Quick summary:"
grep -c '"level": "ERROR"' "$OUT" 2>/dev/null && echo " errors found" || echo " 0 errors"
grep 'AG-UI done:' "$OUT" | tail -3
