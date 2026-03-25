#!/usr/bin/env bash
# Deploy SamCart Analytics Dashboard to DigitalOcean droplet.
# Run as: sudo bash deploy.sh
# Expects to be run on the droplet as root (or with sudo).

set -euo pipefail

APP_NAME="samcart-analytics"
APP_DIR="/home/deploy/${APP_NAME}"
REPO_URL="https://github.com/cdelvalle81282/samcart-analytics.git"
DOMAIN="samcart-analytics.duckdns.org"
PORT=8501

echo "=== SamCart Analytics Deployment ==="

# ── 1. System dependencies ────────────────────────────────────────────
echo "[1/8] Checking system dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx certbot python3-certbot-nginx > /dev/null

# ── 2. Clone repo ─────────────────────────────────────────────────────
echo "[2/8] Cloning repository..."
if [ -d "$APP_DIR" ]; then
    echo "  Directory exists — pulling latest..."
    cd "$APP_DIR"
    sudo -u deploy git pull origin master
else
    sudo -u deploy git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# ── 3. Python venv + deps ─────────────────────────────────────────────
echo "[3/8] Setting up Python virtualenv..."
if [ ! -d "${APP_DIR}/venv" ]; then
    sudo -u deploy python3 -m venv "${APP_DIR}/venv"
fi
sudo -u deploy "${APP_DIR}/venv/bin/pip" install --upgrade pip -q
sudo -u deploy "${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt" -q
echo "  Dependencies installed."

# ── 4. Secrets ─────────────────────────────────────────────────────────
echo "[4/8] Configuring secrets..."
SECRETS_FILE="${APP_DIR}/.streamlit/secrets.toml"
sudo -u deploy mkdir -p "${APP_DIR}/.streamlit"

if [ -f "$SECRETS_FILE" ]; then
    echo "  secrets.toml already exists — skipping."
else
    echo "  Creating secrets.toml..."
    echo "  You will need to paste your secrets into: ${SECRETS_FILE}"
    echo "  Template:"
    cat <<'TEMPLATE'

SAMCART_API_KEY = "your-api-key-here"

[auth]
cookie_name = "samcart_analytics"
cookie_key = "your-cookie-key-here"
cookie_expiry_days = 7

[auth.credentials.usernames.admin]
email = "you@example.com"
name = "Admin"
password = "$2b$12$your-bcrypt-hash-here"

TEMPLATE
    read -r -p "  Do you have secrets ready to paste now? (y/n): " PASTE_SECRETS
    if [[ "$PASTE_SECRETS" == "y" ]]; then
        echo "  Paste your secrets.toml content, then press Ctrl+D when done:"
        sudo -u deploy tee "$SECRETS_FILE" > /dev/null
        chmod 600 "$SECRETS_FILE"
        chown deploy:deploy "$SECRETS_FILE"
        echo "  secrets.toml written."
    else
        echo "  Skipped. Create it manually before starting the service:"
        echo "    sudo -u deploy nano ${SECRETS_FILE}"
    fi
fi

# ── 5. Systemd service ────────────────────────────────────────────────
echo "[5/8] Creating systemd service..."
cat > /etc/systemd/system/${APP_NAME}.service <<EOF
[Unit]
Description=SamCart Analytics Dashboard
After=network.target

[Service]
Type=simple
User=deploy
WorkingDirectory=${APP_DIR}
Environment=PATH=${APP_DIR}/venv/bin:/usr/bin:/bin
ExecStart=${APP_DIR}/venv/bin/streamlit run app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ${APP_NAME}
systemctl restart ${APP_NAME}
echo "  Service started."

# ── 6. Nginx reverse proxy ────────────────────────────────────────────
echo "[6/8] Configuring Nginx..."
cat > /etc/nginx/sites-available/${APP_NAME} <<EOF
server {
    listen 80;
    server_name ${DOMAIN};

    # Security headers
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'self' 'unsafe-inline' 'unsafe-eval' https:; img-src 'self' data: https:; connect-src 'self' wss: https:;" always;

    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 86400;
    }
}
EOF

if [ ! -L /etc/nginx/sites-enabled/${APP_NAME} ]; then
    ln -s /etc/nginx/sites-available/${APP_NAME} /etc/nginx/sites-enabled/${APP_NAME}
fi

nginx -t
systemctl reload nginx
echo "  Nginx configured."

# ── 7. DuckDNS + SSL ──────────────────────────────────────────────────
echo "[7/8] Setting up DuckDNS + SSL..."
read -r -p "  Enter your DuckDNS token (or press Enter to skip): " DUCKDNS_TOKEN
if [ -n "$DUCKDNS_TOKEN" ]; then
    RESULT=$(curl -s "https://www.duckdns.org/update?domains=samcart-analytics&token=${DUCKDNS_TOKEN}&ip=167.99.167.244")
    echo "  DuckDNS update: ${RESULT}"

    echo "  Running Certbot for SSL..."
    certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos --email admin@example.com --redirect || {
        echo "  Certbot failed — you may need to run it manually after DNS propagates."
        echo "  Command: sudo certbot --nginx -d ${DOMAIN}"
    }
else
    echo "  Skipped DuckDNS. Set it up manually, then run:"
    echo "    sudo certbot --nginx -d ${DOMAIN}"
fi

# ── 8. Cron for daily sync + reports ──────────────────────────────────
echo "[8/8] Setting up daily sync & report crons..."
SYNC_CRON="0 12 * * * cd ${APP_DIR} && ${APP_DIR}/venv/bin/python sync_job.py >> ${APP_DIR}/sync.log 2>&1"
REPORT_CRON="30 12 * * * cd ${APP_DIR} && ${APP_DIR}/venv/bin/python report_runner.py >> /var/log/samcart-reports.log 2>&1"
(sudo -u deploy crontab -l 2>/dev/null | grep -v "sync_job.py" | grep -v "report_runner.py"; echo "$SYNC_CRON"; echo "$REPORT_CRON") | sudo -u deploy crontab -
echo "  Cron installed: sync at noon UTC, reports at 12:30 UTC."

# ── Done ───────────────────────────────────────────────────────────────
echo ""
echo "=== Deployment complete ==="
echo ""
echo "Verify with:"
echo "  sudo systemctl status ${APP_NAME}"
echo "  curl -s http://127.0.0.1:${PORT} | head -5"
echo "  https://${DOMAIN}"
echo ""
echo "To run initial sync:"
echo "  cd ${APP_DIR} && sudo -u deploy ${APP_DIR}/venv/bin/python sync_job.py"
echo ""
echo "Logs:"
echo "  journalctl -u ${APP_NAME} -f        # Streamlit logs"
echo "  tail -f ${APP_DIR}/sync.log          # Sync logs"
echo "  tail -f /var/log/samcart-reports.log # Report logs"
