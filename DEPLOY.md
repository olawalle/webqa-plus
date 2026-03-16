# Deploying WebQA-Plus on a Bare Linux Server

This guide walks you through hosting WebQA-Plus so anyone on the internet can access it.  
Everything runs inside Docker, with Nginx as the public-facing reverse proxy and Let's Encrypt for free HTTPS.

---

## Prerequisites

| Requirement                                         | Minimum                                 |
| --------------------------------------------------- | --------------------------------------- |
| Linux server (Ubuntu 22.04 / Debian 12 recommended) | 2 vCPU, 4 GB RAM                        |
| Open ports                                          | 22 (SSH), 80 (HTTP), 443 (HTTPS)        |
| A domain name pointed at your server's IP           | Required for HTTPS                      |
| Google API key (Gemini)                             | From https://aistudio.google.com/apikey |

---

## Step 1 — Prepare your server

SSH into your server, then run:

```bash
# Update packages
sudo apt update && sudo apt upgrade -y

# Install Docker + Docker Compose plugin
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker                     # reload group without logout

# Verify
docker --version
docker compose version
```

---

## Step 2 — Get the code onto the server

**Option A — clone from Git (recommended):**

```bash
git clone https://github.com/yourusername/webqa-plus.git
cd webqa-plus
```

**Option B — copy from your local machine:**

```bash
# Run from your Mac
rsync -avz --exclude node_modules --exclude __pycache__ --exclude .git \
  /Users/olawaleariyo/Documents/projects/exploration/webqa-plus/ \
  user@YOUR_SERVER_IP:~/webqa-plus/

ssh user@YOUR_SERVER_IP
cd ~/webqa-plus
```

---

## Step 3 — Configure environment variables

```bash
cp .env.example .env
nano .env          # or: vim .env
```

Set your `GOOGLE_API_KEY`. That is the only required value.  
Save and close (Ctrl+O, Enter, Ctrl+X in nano).

---

## Step 4 — Point your domain at the server

In your DNS provider's control panel, create an **A record**:

```
Type:  A
Name:  @  (or subdomain, e.g. webqa)
Value: YOUR_SERVER_IP
TTL:   300
```

Wait for DNS to propagate (check with `dig YOUR_DOMAIN +short`).

---

## Step 5 — Deploy (with HTTPS)

Replace `YOUR_DOMAIN` and `YOUR_EMAIL` with real values:

```bash
chmod +x deploy.sh
./deploy.sh --domain YOUR_DOMAIN --email YOUR_EMAIL
```

The script will:

1. Build the Docker image (Python backend + React frontend compiled in)
2. Start Nginx + the app container
3. Use Certbot to get a free Let's Encrypt SSL certificate
4. Enable the HTTPS block in the Nginx config
5. Start the Certbot auto-renewal service

Your app is now live at **https://YOUR_DOMAIN** 🎉

---

## Step 5 (alternative) — HTTP only, no domain

If you just want to test with the server IP:

```bash
docker compose build
docker compose up -d webqa nginx
```

Access at `http://YOUR_SERVER_IP` (no HTTPS).

---

## Day-2 operations

### View live logs

```bash
docker compose logs -f webqa
```

### Restart the app

```bash
docker compose restart webqa
```

### Deploy a new version

```bash
git pull                          # or rsync from local
docker compose build webqa        # rebuild image
docker compose up -d --no-deps webqa   # rolling restart
```

### Stop everything

```bash
docker compose down
```

### Reports are persisted here

```bash
ls ./reports/
```

The `reports/` folder on the host is mounted into the container, so generated HTML/PDF reports survive container restarts.

---

## Firewall (optional but recommended)

```bash
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

---

## Files added by this guide

| File                 | Purpose                                      |
| -------------------- | -------------------------------------------- |
| `Dockerfile`         | Fixed to include the React frontend build    |
| `docker-compose.yml` | Orchestrates app + Nginx + Certbot           |
| `nginx/nginx.conf`   | Reverse proxy config (HTTP redirect → HTTPS) |
| `.env.example`       | Template for environment variables           |
| `deploy.sh`          | One-command deploy + SSL provisioning script |

---

## Troubleshooting

**App container keeps restarting:**

```bash
docker compose logs webqa --tail 50
```

Usually a missing API key or Playwright browser not installed yet (first boot).

**SSL certificate fails:**

- Check DNS has propagated: `dig YOUR_DOMAIN +short` should return your server IP
- Ports 80 and 443 must be reachable from the internet
- Re-run: `docker compose run --rm certbot certonly --webroot --webroot-path /var/www/certbot --email YOUR_EMAIL --agree-tos -d YOUR_DOMAIN`

**"Browser runtime is not installed" error in the web UI:**

```bash
docker compose exec webqa playwright install chromium
docker compose restart webqa
```
