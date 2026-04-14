#!/bin/bash

# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

# Copilot integration — builds and manages the lightweight MCP server
# for use with GitHub Copilot (VS Code, CLI, Cloud Agent).
#
# Sourced by setup.sh. Requires: $PROJECT_ROOT, $script_dir,
# log(), _ensure_docker() from utils.sh / container_setup.sh.

# Note: $compose_file uses $PROJECT_ROOT which is set by setup.sh
# after sourcing this file, so we reference it lazily inside functions.

# ---------------------------------------------------------------------------
# Write the Copilot CLI config (~/.config/gh-copilot/config.yml)
# ---------------------------------------------------------------------------

_write_copilot_cli_config() {
    local mcp_url="$1"
    local config_dir="$HOME/.config/gh-copilot"
    local config_file="$config_dir/config.yml"

    if [[ -f "$config_file" ]] && grep -q "sap-staf" "$config_file" 2>/dev/null; then
        log "INFO" "Copilot CLI config already has sap-staf entry."
        return
    fi

    mkdir -p "$config_dir"
    if [[ -f "$config_file" ]]; then
        if grep -q "^mcp-servers:" "$config_file" 2>/dev/null; then
            # Append under the existing mcp-servers block
            sed -i '/^mcp-servers:/a\  sap-staf:\n    type: http\n    url: '"$mcp_url" "$config_file"
            log "INFO" "Added sap-staf under existing mcp-servers in $config_file"
        else
            cat >> "$config_file" <<EOF

mcp-servers:
  sap-staf:
    type: http
    url: $mcp_url
EOF
            log "INFO" "Added mcp-servers block with sap-staf to $config_file"
        fi
    else
        cat > "$config_file" <<EOF
mcp-servers:
  sap-staf:
    type: http
    url: $mcp_url
EOF
        log "INFO" "Created $config_file with sap-staf entry."
    fi
}

# ---------------------------------------------------------------------------
# run_copilot  start | stop | update
# ---------------------------------------------------------------------------

run_copilot() {
    local command="${1:-}"
    local compose_file="$PROJECT_ROOT/deploy/docker-compose.copilot.yml"
    if [[ -z "$command" ]]; then
        log "ERROR" "Missing copilot command (start|stop|update)."
        show_help
        exit 1
    fi
    shift

    _ensure_docker

    export HOST_UID="$(id -u)"
    export HOST_GID="$(id -g)"
    export GIT_COMMIT="$(git -C "$PROJECT_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"

    case "$command" in
        start)
            log "INFO" "Starting SAP STAF MCP server..."
            docker compose -f "$compose_file" up -d --build
            local mcp_url="http://localhost:${MCP_PORT:-8001}/mcp"
            log "INFO" "SAP STAF MCP server starting on $mcp_url"
            log "INFO" ""
            log "INFO" "=== VS Code Copilot Chat ==="
            log "INFO" "Auto-configured via .vscode/mcp.json — just open Copilot Chat."
            log "INFO" ""
            log "INFO" "=== GitHub Copilot CLI ==="
            log "INFO" "Add to ~/.config/gh-copilot/config.yml:"
            log "INFO" "  mcp-servers:"
            log "INFO" "    sap-staf:"
            log "INFO" "      type: http"
            log "INFO" "      url: $mcp_url"
            log "INFO" ""
            log "INFO" "Then: gh copilot chat"
            _write_copilot_cli_config "$mcp_url"
            ;;
        stop)
            log "INFO" "Stopping SAP STAF MCP server..."
            docker compose -f "$compose_file" down
            ;;
        update)
            log "INFO" "Rebuilding SAP STAF MCP server..."
            docker compose -f "$compose_file" up -d --build --force-recreate
            ;;
        *)
            log "ERROR" "Unknown copilot command: $command (use start|stop|update)"
            show_help
            exit 1
            ;;
    esac
}
