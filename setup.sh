#!/bin/bash
# ===================================================
# Oracle Cloud VM Setup Script
# Run as root on Ubuntu 22.04/24.04
# ===================================================
set -e

echo "=== System update ==="
apt-get update -y && apt-get upgrade -y

echo "=== Install Python3, Nginx, Certbot ==="
apt-get install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx ufw

echo "=== Create app user ==="
useradd -m -s /bin/bash withdrawal 2>/dev/null || true

echo "=== Setup app directory ==="
mkdir -p /opt/withdrawal/data/attachments
chown -R withdrawal:withdrawal /opt/withdrawal

echo "=== Setup Python venv ==="
sudo -u withdrawal python3 -m venv /opt/withdrawal/venv
sudo -u withdrawal /opt/withdrawal/venv/bin/pip install --upgrade pip

echo "=== Setup systemd service ==="
cat > /etc/systemd/system/withdrawal.service << 'EOF'
[Unit]
Description=Withdrawal System (Towing Records)
After=network.target

[Service]
Type=simple
User=withdrawal
WorkingDirectory=/opt/withdrawal
ExecStart=/opt/withdrawal/venv/bin/gunicorn -w 2 -b 127.0.0.1:8081 --timeout 120 server:app
Restart=always
RestartSec=5
Environment=PORT=8081

[Install]
WantedBy=multi-user.target
EOF

echo "=== Setup Nginx ==="
cat > /etc/nginx/sites-available/withdrawal << 'NGINX'
server {
    listen 80;
    server_name _;

    client_max_body_size 25M;

    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
NGINX

ln -sf /etc/nginx/sites-available/withdrawal /etc/nginx/sites-enabled/withdrawal
rm -f /etc/nginx/sites-enabled/default

echo "=== Configure firewall ==="
ufw allow 'Nginx Full'
ufw allow OpenSSH
ufw --force enable

echo "=== Start services ==="
systemctl daemon-reload
systemctl enable withdrawal nginx
systemctl restart withdrawal nginx

echo ""
echo "====================================="
echo "Setup complete!"
echo "Next steps:"
echo "1. Upload your app files to /opt/withdrawal/"
echo "2. Run: sudo chown -R withdrawal:withdrawal /opt/withdrawal"
echo "3. Run: sudo systemctl restart withdrawal"
echo "4. Get SSL: sudo certbot --nginx -d YOUR_DOMAIN"
echo "====================================="
