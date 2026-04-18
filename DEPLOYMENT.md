# Deployment Guide — GitHub → DigitalOcean → import-car.net

Complete step-by-step to deploy TurboMarket from a GitHub repo to a DigitalOcean droplet, with the Squarespace-registered domain `import-car.net` and HTTPS via Let's Encrypt.

---

## Prerequisites

- GitHub account
- DigitalOcean account with billing enabled
- Squarespace domain `import-car.net` (registered, not yet pointed anywhere)
- Local machine with `git` installed
- SSH key on your local machine (`~/.ssh/id_rsa.pub`). If you don't have one:
  ```bash
  ssh-keygen -t ed25519 -C "you@example.com"
  ```

---

## Step 1 — Push the project to GitHub

### 1a. Initialize git in the project
```bash
cd "C:/Users/info/Naachtech/NaachTech - Documents/Projects/AI Projects/turbo_market"
git init
git add .
git commit -m "Initial commit: TurboMarket web app"
```

### 1b. Create a GitHub repository
1. Go to https://github.com/new
2. Repository name: `turbo_market`
3. **Private** (recommended — contains scraping logic and admin keys structure)
4. Do NOT initialize with README / .gitignore / license (already exist)
5. Click "Create repository"

### 1c. Push
```bash
git remote add origin git@github.com:YOUR_USERNAME/turbo_market.git
git branch -M main
git push -u origin main
```

If you use HTTPS instead of SSH:
```bash
git remote add origin https://github.com/YOUR_USERNAME/turbo_market.git
```

---

## Step 2 — Create a DigitalOcean Droplet

### 2a. Droplet specs
- **Image:** Ubuntu 24.04 LTS x64
- **Plan:** Basic → **Regular SSD**
- **Size:** Minimum **$24/mo (4 GB RAM / 2 vCPU / 80 GB SSD)** — Playwright + PostgreSQL + Redis + Celery need RAM. Recommended: **$48/mo (8 GB RAM / 4 vCPU)** for production.
- **Region:** Frankfurt or Amsterdam (closest to Azerbaijan for turbo.az latency)
- **Authentication:** SSH key (paste your `~/.ssh/id_rsa.pub` content)
- **Hostname:** `turbo-market-prod`
- **Enable backups:** Yes (optional, +20% cost)

Click **Create Droplet**. Note the **public IPv4 address** — you'll need it in Steps 3 and 5.

### 2b. Connect via SSH
```bash
ssh root@YOUR_DROPLET_IP
```

---

## Step 3 — Initial Server Setup (on the droplet)

### 3a. Update and install basics
```bash
apt update && apt upgrade -y
apt install -y git ufw curl
```

### 3b. Firewall
```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

### 3c. Install Docker + Docker Compose
```bash
curl -fsSL https://get.docker.com | sh
apt install -y docker-compose-plugin
docker --version
docker compose version
```

### 3d. Create a deploy user (optional but recommended)
```bash
adduser deploy
usermod -aG docker deploy
usermod -aG sudo deploy
mkdir -p /home/deploy/.ssh
cp ~/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
```

From now on: `ssh deploy@YOUR_DROPLET_IP`

---

## Step 4 — Deploy the App (on the droplet)

### 4a. Create a deploy key so the droplet can pull from your private repo
```bash
ssh-keygen -t ed25519 -C "deploy@turbo-market" -f ~/.ssh/github_deploy -N ""
cat ~/.ssh/github_deploy.pub
```
Copy the printed key. In GitHub:
1. Go to your repo → **Settings → Deploy keys → Add deploy key**
2. Title: `turbo-market-prod-droplet`
3. Paste the key
4. Leave "Allow write access" unchecked
5. Add key

Configure SSH to use this key for GitHub:
```bash
cat >> ~/.ssh/config <<'EOF'
Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/github_deploy
  IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
```

### 4b. Clone the repo
```bash
cd ~
git clone git@github.com:YOUR_USERNAME/turbo_market.git
cd turbo_market
```

### 4c. Configure environment variables
```bash
cp .env.example .env
nano .env
```
Set at minimum:
```env
DB_PASSWORD=<generate a strong password>
ADMIN_API_KEY=<generate a strong random string>
AZN_PER_USD=1.7
```
Generate strong values:
```bash
openssl rand -hex 32
```

### 4d. First build & start
```bash
docker compose up -d --build
```
Watch logs:
```bash
docker compose logs -f backend
```
Expect to see Alembic migrations run, then Uvicorn start on port 8000.

### 4e. Verify
```bash
curl http://localhost/health
# → {"status":"ok"}

curl http://YOUR_DROPLET_IP/health
# should also work from your local machine
```

Trigger a first scrape (optional, to populate the DB):
```bash
curl -X POST http://localhost/api/v1/admin/scrape/trigger \
  -H "X-Admin-Key: <your ADMIN_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"job_type":"make_scan","target_make":"Toyota"}'
```

---

## Step 5 — Point import-car.net from Squarespace to the Droplet

Squarespace **Domains** (registrar) allows editing DNS records directly — you do NOT need Squarespace hosting.

### 5a. Log into Squarespace
1. https://account.squarespace.com/domains
2. Click `import-car.net`
3. Find **DNS Settings** (left sidebar) → **DNS**

### 5b. Remove or disable conflicting records
Delete or leave blank any existing `A` record on the apex (`@`) and `www` that Squarespace pre-configured to point to parking/website hosting. You want full control.

### 5c. Add these records
| Type | Host | Value | TTL |
|------|------|-------|-----|
| A | `@` | `YOUR_DROPLET_IP` | 3600 |
| A | `www` | `YOUR_DROPLET_IP` | 3600 |

### 5d. Save and wait
DNS propagation is usually 5–30 minutes (sometimes a few hours). Check from your local machine:
```bash
nslookup import-car.net 8.8.8.8
```
When it returns `YOUR_DROPLET_IP`, proceed to Step 6.

---

## Step 6 — Configure Nginx for the Domain + SSL

### 6a. Update the Nginx config to know the domain
On the droplet:
```bash
cd ~/turbo_market
nano nginx/nginx.conf
```
Replace the `server {}` block with:
```nginx
events {
    worker_connections 1024;
}

http {
    upstream backend {
        server backend:8000;
    }
    upstream frontend {
        server frontend:80;
    }

    # HTTP: redirect to HTTPS (except Let's Encrypt challenges)
    server {
        listen 80;
        server_name import-car.net www.import-car.net;

        location /.well-known/acme-challenge/ {
            root /var/www/certbot;
        }

        location / {
            return 301 https://$host$request_uri;
        }
    }

    # HTTPS
    server {
        listen 443 ssl;
        server_name import-car.net www.import-car.net;

        ssl_certificate     /etc/letsencrypt/live/import-car.net/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/import-car.net/privkey.pem;
        ssl_protocols TLSv1.2 TLSv1.3;

        client_max_body_size 20M;

        location /api/ {
            proxy_pass http://backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 120s;
        }
        location /health {
            proxy_pass http://backend/health;
        }
        location / {
            proxy_pass http://frontend;
            proxy_set_header Host $host;
        }
    }
}
```

### 6b. Update `docker-compose.yml` to mount SSL certs and webroot
Edit the `nginx:` service:
```bash
nano docker-compose.yml
```
Change it to:
```yaml
  nginx:
    image: nginx:alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./certbot/conf:/etc/letsencrypt:ro
      - ./certbot/www:/var/www/certbot:ro
    depends_on:
      - backend
      - frontend
```

### 6c. First start: get the certificate
Temporarily revert Nginx to a simple HTTP-only config so certbot can run the challenge:
```bash
cat > nginx/nginx.conf <<'EOF'
events { worker_connections 1024; }
http {
    server {
        listen 80;
        server_name import-car.net www.import-car.net;
        location /.well-known/acme-challenge/ {
            root /var/www/certbot;
        }
        location / { return 200 "ok"; }
    }
}
EOF

mkdir -p certbot/conf certbot/www
docker compose up -d nginx
```

Run certbot in a one-off container:
```bash
docker run --rm \
  -v "$(pwd)/certbot/conf:/etc/letsencrypt" \
  -v "$(pwd)/certbot/www:/var/www/certbot" \
  certbot/certbot certonly --webroot -w /var/www/certbot \
  -d import-car.net -d www.import-car.net \
  --email you@example.com --agree-tos --no-eff-email
```

You should see `Successfully received certificate.`

### 6d. Restore the full HTTPS Nginx config
Restore the config from Step 6a (the one with the `ssl_certificate` lines):
```bash
nano nginx/nginx.conf
# paste the full config from 6a
```

Reload Nginx:
```bash
docker compose restart nginx
```

### 6e. Verify
Visit:
- https://import-car.net — should load the frontend
- https://import-car.net/api/v1/vehicles — should return JSON
- https://import-car.net/health — should return `{"status":"ok"}`

---

## Step 7 — Auto-renew SSL

Let's Encrypt certs expire every 90 days. Set up a cron job:
```bash
crontab -e
```
Add:
```
0 3 * * * cd /home/deploy/turbo_market && docker run --rm -v "$(pwd)/certbot/conf:/etc/letsencrypt" -v "$(pwd)/certbot/www:/var/www/certbot" certbot/certbot renew --quiet && docker compose exec nginx nginx -s reload
```

---

## Step 8 — Deploying Updates

Whenever you push changes to GitHub:
```bash
ssh deploy@YOUR_DROPLET_IP
cd ~/turbo_market
git pull
docker compose up -d --build
```

Zero-downtime tip: deploy during low-traffic hours (the daily scan runs at 2 AM UTC).

---

## Step 9 — Monitoring & Maintenance

### View logs
```bash
docker compose logs -f backend                # FastAPI
docker compose logs -f celery_listing         # listing scraper
docker compose logs -f celery_detail          # detail scraper
docker compose logs -f celery_beat            # scheduler
```

### Database backups
```bash
# Manual backup
docker compose exec db pg_dump -U turbo turbo_market | gzip > backup_$(date +%F).sql.gz

# Automated daily backup via cron:
crontab -e
```
Add:
```
0 4 * * * cd /home/deploy/turbo_market && docker compose exec -T db pg_dump -U turbo turbo_market | gzip > ~/backups/turbo_$(date +\%F).sql.gz && find ~/backups -name "turbo_*.sql.gz" -mtime +14 -delete
```
```bash
mkdir -p ~/backups
```

### Check Celery queue status
```bash
docker compose exec redis redis-cli llen celery
docker compose exec redis redis-cli llen listing
docker compose exec redis redis-cli llen detail
```

---

## Troubleshooting

**"502 Bad Gateway" from Nginx**
Backend not ready. `docker compose logs backend` — wait for migrations to finish.

**Cloudflare challenge blocks scraper**
The `browser_profile` volume needs to accumulate trust cookies. If headless fails, SSH in and run:
```bash
docker compose exec celery_listing python -c "from app.scraper.browser import BrowserManager; BrowserManager().start()"
```
Or temporarily switch `SCRAPER_MODE=cdp` for local debugging.

**Out of memory / OOM-killed**
Upgrade droplet to 8 GB RAM, or reduce `celery_detail` concurrency from 3 to 1.

**DNS not resolving after 1 hour**
Squarespace DNS can be slow — try a different DNS lookup: https://dnschecker.org/#A/import-car.net

---

## Cost Summary

| Item | Monthly |
|---|---|
| DO Droplet (4 GB / 2 vCPU) | $24 |
| DO Droplet (8 GB / 4 vCPU, recommended) | $48 |
| DO Backups (optional, 20%) | $5 – $10 |
| Let's Encrypt SSL | Free |
| Squarespace domain (annual) | ~$2/mo |
| **Total (recommended tier)** | **~$55 – $60/mo** |
