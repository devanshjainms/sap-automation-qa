# Deployment Guide

## VM Deployment (All-in-One)

This deploys both frontend and backend on a single VM. Ideal for internal networks where the VM is accessible via VPN or corporate network.

### Architecture
```
User (VPN) → VM (nginx:80) → React Frontend (static files)
                           → /api/* → Backend (FastAPI)
```

### Prerequisites
- Ubuntu 22.04 VM (D2s_v3 or similar)
- VM in same VNet as SAP systems (for SSH access)
- Managed Identity enabled (for KeyVault access)
- Docker & Docker Compose installed

### Quick Start

1. **SSH into your VM:**
   ```bash
   ssh azureuser@your-vm-ip
   ```

2. **Install Docker (if not already installed):**
   ```bash
   curl -fsSL https://get.docker.com | bash
   sudo usermod -aG docker $USER
   newgrp docker
   ```

3. **Clone the repository:**
   ```bash
   git clone https://github.com/your-org/sap-automation-qa.git
   cd sap-automation-qa/deploy
   ```

4. **Configure environment:**
   ```bash
   cp .env.example .env
   nano .env  # Edit with your Azure OpenAI credentials
   ```

5. **Build frontend and start all services:**
   ```bash
   # Build the React frontend (first time only, or after frontend changes)
   docker compose --profile build up frontend
   
   # Start backend and nginx
   docker compose up -d
   ```

6. **Verify it's running:**
   ```bash
   curl http://localhost/health         # Backend health
   curl http://localhost/               # Frontend
   ```

7. **Access the application** (see [Accessing the Web UI](#accessing-the-web-ui) below)

### Accessing the Web UI

Since the VM has only a private IP, choose one of these methods:

#### Option A: Jump VM with Desktop (Recommended)
If you have a Windows/Linux VM with desktop access in the same VNet:
1. RDP/VNC into the jump VM
2. Open a browser and navigate to `http://<backend-vm-private-ip>/`

#### Option B: VS Code Remote-SSH with Port Forwarding
1. Install VS Code with Remote-SSH extension
2. Configure SSH via jump host or VPN in `~/.ssh/config`
3. Connect to the VM via Remote-SSH
4. VS Code auto-forwards ports - click on port 80 in the Ports panel
5. Browse to the forwarded local URL

#### Option C: SSH Tunnel (if direct SSH available)
```bash
ssh -L 8080:localhost:80 user@<vm-ip>
# Then browse to http://localhost:8080
```

#### Option D: Bastion Native Client (requires admin setup)
Ask your Azure admin to enable tunneling on Bastion:
```bash
az network bastion update --name <bastion-name> -g <rg> --enable-tunneling true
```
Then users can tunnel via CLI.

### Updating the Application

```bash
cd sap-automation-qa
git pull

# If frontend changed:
docker compose --profile build up frontend

# Rebuild and restart backend:
docker compose up -d --build
```

### SSL Setup (Optional but Recommended)

**Option A: Let's Encrypt (Free)**
```bash
# Install certbot
sudo apt-get install certbot

# Get certificate (replace with your domain)
sudo certbot certonly --standalone -d your-domain.com

# Copy certificates
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem deploy/ssl/
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem deploy/ssl/

# Uncomment SSL lines in nginx.conf and restart
docker-compose restart nginx
```

**Option B: Self-signed (Development)**
```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout deploy/ssl/privkey.pem \
  -out deploy/ssl/fullchain.pem \
  -subj "/CN=localhost"
```

### Management Commands

```bash
# View logs
docker-compose logs -f

# Restart services
docker-compose restart

# Stop services
docker-compose down

# Update application
git pull
docker-compose build
docker-compose up -d

# View running containers
docker-compose ps

# Enter backend container
docker-compose exec backend bash
```

### Troubleshooting

**Check if services are healthy:**
```bash
docker-compose ps
curl http://localhost:8000/health
```

**View backend logs:**
```bash
docker-compose logs backend
```

**Check nginx logs:**
```bash
docker-compose logs nginx
```

**Database issues:**
```bash
# SQLite database is stored in a Docker volume
docker volume inspect sap-qa-data
```

### Architecture

```
┌─────────────────────────────────────────────┐
│                 Azure VM                     │
│  ┌─────────────────────────────────────┐    │
│  │          Docker Compose             │    │
│  │  ┌─────────┐      ┌─────────────┐   │    │
│  │  │  nginx  │ ───▶ │   backend   │   │    │
│  │  │  :80    │      │   :8000     │   │    │
│  │  └─────────┘      └─────────────┘   │    │
│  │                          │          │    │
│  │                   ┌──────┴──────┐   │    │
│  │                   │   SQLite    │   │    │
│  │                   │  (volume)   │   │    │
│  │                   └─────────────┘   │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────┐
│ Azure Static Web App│  (Frontend)
│   → /api/* proxy    │──────────────▶ VM:80
└─────────────────────┘
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Yes | Azure OpenAI endpoint URL |
| `AZURE_OPENAI_API_KEY` | Yes | Azure OpenAI API key |
| `AZURE_OPENAI_DEPLOYMENT` | Yes | Model deployment name |
| `AZURE_KEYVAULT_NAME` | No | KeyVault for SSH keys |
| `LOG_LEVEL` | No | Logging level (default: INFO) |
