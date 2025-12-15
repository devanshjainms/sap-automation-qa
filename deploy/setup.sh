#!/bin/bash
# SAP Automation QA - VM Deployment Setup Script
# This script sets up and runs the complete application stack

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DEPLOY_DIR="$SCRIPT_DIR"

print_banner() {
    echo -e "${BLUE}"
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║           SAP Automation QA - Deployment Setup                ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [[ $EUID -eq 0 ]]; then
        log_warn "Running as root. Consider using a non-root user with docker group."
    fi
}

# Check if Docker is installed
check_docker() {
    log_info "Checking Docker installation..."
    
    if ! command -v docker &> /dev/null; then
        log_warn "Docker not found. Installing Docker..."
        install_docker
    else
        log_success "Docker is installed: $(docker --version)"
    fi
    
    # Check if Docker daemon is running
    if ! docker info &> /dev/null; then
        log_error "Docker daemon is not running. Starting Docker..."
        sudo systemctl start docker
    fi
    
    # Check if user can run docker without sudo
    if ! docker ps &> /dev/null 2>&1; then
        log_warn "Current user cannot run Docker. Adding to docker group..."
        sudo usermod -aG docker "$USER"
        log_warn "Please log out and back in, then run this script again."
        exit 1
    fi
    
    # Enable Docker to start on boot
    sudo systemctl enable docker &> /dev/null || true
    log_success "Docker daemon is running and enabled on boot"
}

install_docker() {
    log_info "Installing Docker..."
    
    # Detect OS
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
    else
        log_error "Cannot detect OS. Please install Docker manually."
        exit 1
    fi
    
    case $OS in
        ubuntu|debian)
            sudo apt-get update
            sudo apt-get install -y ca-certificates curl gnupg
            sudo install -m 0755 -d /etc/apt/keyrings
            curl -fsSL https://download.docker.com/linux/$OS/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
            sudo chmod a+r /etc/apt/keyrings/docker.gpg
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/$OS $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
            sudo apt-get update
            sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
            ;;
        rhel|centos|fedora)
            sudo dnf -y install dnf-plugins-core
            sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
            sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
            ;;
        sles|opensuse*)
            sudo zypper install -y docker docker-compose
            ;;
        *)
            log_error "Unsupported OS: $OS. Please install Docker manually."
            exit 1
            ;;
    esac
    
    sudo systemctl start docker
    sudo systemctl enable docker
    sudo usermod -aG docker "$USER"
    
    log_success "Docker installed successfully"
    log_warn "Please log out and back in, then run this script again."
    exit 0
}

# Check Docker Compose
check_docker_compose() {
    log_info "Checking Docker Compose..."
    
    if docker compose version &> /dev/null; then
        log_success "Docker Compose (plugin): $(docker compose version --short)"
    elif command -v docker-compose &> /dev/null; then
        log_success "Docker Compose (standalone): $(docker-compose --version)"
        # Create alias for consistency
        COMPOSE_CMD="docker-compose"
    else
        log_error "Docker Compose not found. Please install docker-compose-plugin."
        exit 1
    fi
}

# Setup environment file
setup_environment() {
    log_info "Setting up environment configuration..."
    
    ENV_FILE="$DEPLOY_DIR/.env"
    ENV_EXAMPLE="$DEPLOY_DIR/.env.example"
    
    # Create .env from example if it doesn't exist
    if [ ! -f "$ENV_FILE" ]; then
        if [ ! -f "$ENV_EXAMPLE" ]; then
            log_error ".env.example not found at $ENV_EXAMPLE"
            exit 1
        fi
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        log_info "Created .env from template"
    fi
    
    # Check if Azure OpenAI is already configured
    CURRENT_ENDPOINT=$(grep "^AZURE_OPENAI_ENDPOINT=" "$ENV_FILE" | cut -d'=' -f2)
    CURRENT_KEY=$(grep "^AZURE_OPENAI_API_KEY=" "$ENV_FILE" | cut -d'=' -f2)
    
    # Check if values are set and not placeholders
    if [[ -n "$CURRENT_ENDPOINT" && "$CURRENT_ENDPOINT" != "https://your-resource.openai.azure.com/" && \
          -n "$CURRENT_KEY" && "$CURRENT_KEY" != "your-api-key-here" ]]; then
        log_success "Azure OpenAI already configured"
        log_info "  Endpoint: ${CURRENT_ENDPOINT:0:50}..."
        
        read -p "Do you want to reconfigure? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Keeping existing configuration"
            return
        fi
    fi
    
    echo ""
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  Azure OpenAI Configuration Required${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
    
    # Get Azure OpenAI configuration
    read -p "Enter Azure OpenAI Endpoint (e.g., https://your-resource.openai.azure.com/): " AZURE_ENDPOINT
    read -p "Enter Azure OpenAI API Key: " -s AZURE_API_KEY
    echo ""
    read -p "Enter Azure OpenAI Deployment Name [gpt-4o]: " AZURE_DEPLOYMENT
    AZURE_DEPLOYMENT=${AZURE_DEPLOYMENT:-gpt-4o}
    read -p "Enter Azure OpenAI API Version [2024-02-15-preview]: " AZURE_API_VERSION
    AZURE_API_VERSION=${AZURE_API_VERSION:-2024-02-15-preview}
    
    # Validate required fields
    if [[ -z "$AZURE_ENDPOINT" || -z "$AZURE_API_KEY" ]]; then
        log_error "Azure OpenAI Endpoint and API Key are required"
        exit 1
    fi
    
    # Update .env file
    sed -i "s|AZURE_OPENAI_ENDPOINT=.*|AZURE_OPENAI_ENDPOINT=$AZURE_ENDPOINT|" "$ENV_FILE"
    sed -i "s|AZURE_OPENAI_API_KEY=.*|AZURE_OPENAI_API_KEY=$AZURE_API_KEY|" "$ENV_FILE"
    sed -i "s|AZURE_OPENAI_DEPLOYMENT=.*|AZURE_OPENAI_DEPLOYMENT=$AZURE_DEPLOYMENT|" "$ENV_FILE"
    sed -i "s|AZURE_OPENAI_API_VERSION=.*|AZURE_OPENAI_API_VERSION=$AZURE_API_VERSION|" "$ENV_FILE"
    
    # Optional: Azure Client ID for Managed Identity
    echo ""
    read -p "Enter Azure Client ID for Managed Identity (leave empty for system-assigned): " AZURE_CLIENT_ID
    if [ -n "$AZURE_CLIENT_ID" ]; then
        sed -i "s|AZURE_CLIENT_ID=.*|AZURE_CLIENT_ID=$AZURE_CLIENT_ID|" "$ENV_FILE"
    fi
    
    log_success "Environment configured successfully"
}

# Build frontend
build_frontend() {
    log_info "Building frontend..."
    
    cd "$DEPLOY_DIR"
    
    # Remove old frontend container and volume if they exist
    docker rm -f sap-qa-frontend-build 2>/dev/null || true
    
    # Check if volume exists and has files
    if docker volume inspect sap-qa-frontend-dist &>/dev/null; then
        VOLUME_FILES=$(docker run --rm -v sap-qa-frontend-dist:/data alpine ls -la /data 2>/dev/null | wc -l)
        if [ "$VOLUME_FILES" -le 3 ]; then
            log_info "Frontend volume is empty, will rebuild..."
            docker volume rm sap-qa-frontend-dist 2>/dev/null || true
        else
            read -p "Frontend already built. Rebuild? (y/N): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                log_info "Skipping frontend build"
                return
            fi
            docker volume rm sap-qa-frontend-dist 2>/dev/null || true
        fi
    fi
    
    log_info "Building React frontend (this may take a few minutes)..."
    docker compose --profile build up frontend
    
    # Verify build succeeded
    VOLUME_FILES=$(docker run --rm -v sap-qa-frontend-dist:/data alpine ls -la /data 2>/dev/null | wc -l)
    if [ "$VOLUME_FILES" -gt 3 ]; then
        log_success "Frontend built successfully"
    else
        log_error "Frontend build failed - volume is empty"
        exit 1
    fi
}

# Start services
start_services() {
    log_info "Starting services..."
    
    cd "$DEPLOY_DIR"
    
    # Stop existing services
    docker compose down 2>/dev/null || true
    
    # Start backend and nginx
    docker compose up -d
    
    log_info "Waiting for services to be healthy..."
    
    # Wait for backend to be healthy
    RETRIES=30
    while [ $RETRIES -gt 0 ]; do
        if docker exec sap-qa-backend curl -sf http://localhost:8000/health &>/dev/null; then
            break
        fi
        RETRIES=$((RETRIES-1))
        sleep 2
    done
    
    if [ $RETRIES -eq 0 ]; then
        log_error "Backend failed to start. Check logs with: docker logs sap-qa-backend"
        exit 1
    fi
    
    log_success "All services started successfully"
}

# Verify deployment
verify_deployment() {
    log_info "Verifying deployment..."
    
    echo ""
    echo "Service Status:"
    echo "───────────────────────────────────────"
    
    # Check backend
    if curl -sf http://localhost:8000/health &>/dev/null; then
        echo -e "  Backend (direct):    ${GREEN}✓ Healthy${NC}"
    else
        echo -e "  Backend (direct):    ${RED}✗ Unhealthy${NC}"
    fi
    
    # Check nginx
    if curl -sf http://localhost/ &>/dev/null; then
        echo -e "  Frontend (nginx):    ${GREEN}✓ Serving${NC}"
    else
        echo -e "  Frontend (nginx):    ${RED}✗ Not responding${NC}"
    fi
    
    # Check API through nginx
    if curl -sf http://localhost/api/health &>/dev/null; then
        echo -e "  API (via nginx):     ${GREEN}✓ Proxying${NC}"
    else
        echo -e "  API (via nginx):     ${RED}✗ Proxy failed${NC}"
    fi
    
    # Check workspaces
    WORKSPACE_COUNT=$(curl -sf http://localhost:8000/workspaces 2>/dev/null | grep -o '"workspace_id"' | wc -l || echo "0")
    echo -e "  Workspaces found:    ${BLUE}$WORKSPACE_COUNT${NC}"
    
    echo "───────────────────────────────────────"
    echo ""
    
    # Get VM IP
    VM_IP=$(hostname -I | awk '{print $1}')
    
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  Deployment Complete!${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo "  Access the application:"
    echo -e "    ${BLUE}http://$VM_IP/${NC}"
    echo ""
    echo "  From a jump VM with browser, navigate to the URL above."
    echo ""
    echo "  Useful commands:"
    echo "    View logs:      docker compose -f $DEPLOY_DIR/docker-compose.yml logs -f"
    echo "    Restart:        docker compose -f $DEPLOY_DIR/docker-compose.yml restart"
    echo "    Stop:           docker compose -f $DEPLOY_DIR/docker-compose.yml down"
    echo ""
}

# Show logs
show_logs() {
    cd "$DEPLOY_DIR"
    docker compose logs -f
}

# Main menu
show_menu() {
    echo ""
    echo "What would you like to do?"
    echo ""
    echo "  1) Full setup (recommended for first time)"
    echo "  2) Reconfigure environment (.env)"
    echo "  3) Rebuild frontend only"
    echo "  4) Restart services"
    echo "  5) View logs"
    echo "  6) Check status"
    echo "  7) Stop services"
    echo "  8) Exit"
    echo ""
    read -p "Select option [1-8]: " choice
    
    case $choice in
        1) full_setup ;;
        2) setup_environment ;;
        3) build_frontend && docker compose -f "$DEPLOY_DIR/docker-compose.yml" restart nginx ;;
        4) start_services && verify_deployment ;;
        5) show_logs ;;
        6) verify_deployment ;;
        7) cd "$DEPLOY_DIR" && docker compose down && log_success "Services stopped" ;;
        8) exit 0 ;;
        *) log_error "Invalid option" && show_menu ;;
    esac
}

# Full setup
full_setup() {
    check_root
    check_docker
    check_docker_compose
    setup_environment
    build_frontend
    start_services
    verify_deployment
}

# Main
main() {
    print_banner
    
    # Check if running from correct directory
    if [ ! -f "$DEPLOY_DIR/docker-compose.yml" ]; then
        log_error "docker-compose.yml not found. Please run from the deploy directory."
        exit 1
    fi
    
    # Parse command line arguments
    case "${1:-}" in
        --full|--install)
            full_setup
            ;;
        --configure)
            setup_environment
            ;;
        --build)
            check_docker
            build_frontend
            ;;
        --start)
            check_docker
            start_services
            verify_deployment
            ;;
        --status)
            verify_deployment
            ;;
        --logs)
            show_logs
            ;;
        --stop)
            cd "$DEPLOY_DIR"
            docker compose down
            log_success "Services stopped"
            ;;
        --help|-h)
            echo "Usage: $0 [OPTION]"
            echo ""
            echo "Options:"
            echo "  --full, --install   Run complete setup"
            echo "  --configure         Configure environment only"
            echo "  --build             Build frontend only"
            echo "  --start             Start services"
            echo "  --status            Check deployment status"
            echo "  --logs              View service logs"
            echo "  --stop              Stop all services"
            echo "  --help, -h          Show this help"
            echo ""
            echo "Without options, shows interactive menu."
            ;;
        "")
            show_menu
            ;;
        *)
            log_error "Unknown option: $1"
            echo "Use --help for usage information."
            exit 1
            ;;
    esac
}

main "$@"
