#!/bin/bash
# SAP Automation QA - VM Setup Script
# Run this on a fresh Ubuntu 22.04 VM

set -e

echo "=========================================="
echo "SAP Automation QA - VM Setup"
echo "=========================================="

# Update system
echo "[1/6] Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# Install Docker
echo "[2/6] Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    rm get-docker.sh
    echo "Docker installed. You may need to log out and back in for group changes."
else
    echo "Docker already installed."
fi

# Install Docker Compose
echo "[3/6] Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
else
    echo "Docker Compose already installed."
fi

# Create application directory
echo "[4/6] Setting up application directory..."
APP_DIR="/opt/sap-automation-qa"
sudo mkdir -p $APP_DIR
sudo chown $USER:$USER $APP_DIR

# Clone repository (or copy files)
echo "[5/6] Setting up application..."
cd $APP_DIR

if [ ! -d ".git" ]; then
    echo "Please clone your repository or copy files to $APP_DIR"
    echo "Example: git clone https://github.com/your-org/sap-automation-qa.git ."
fi

# Create SSL directory
echo "[6/6] Creating SSL directory..."
mkdir -p $APP_DIR/deploy/ssl

echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Clone/copy your code to $APP_DIR"
echo "2. Copy your .env file: cp deploy/.env.example deploy/.env"
echo "3. Edit deploy/.env with your Azure credentials"
echo "4. (Optional) Add SSL certificates to deploy/ssl/"
echo "5. Start the application:"
echo "   cd $APP_DIR/deploy"
echo "   docker-compose up -d"
echo ""
echo "To view logs: docker-compose logs -f"
echo "To stop: docker-compose down"
echo ""
