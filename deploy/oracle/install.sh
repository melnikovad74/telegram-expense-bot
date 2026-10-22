#!/usr/bin/env bash
set -euo pipefail

# Run on a fresh Ubuntu 22.04/24.04 Oracle Cloud VM:
#   chmod +x deploy/oracle/install.sh
#   sudo ./deploy/oracle/install.sh
#
# Then add the token:
#   sudo nano /etc/telegram-expense-bot.env
# and restart:
#   sudo systemctl restart telegram-expense-bot

REPO_URL="https://github.com/melnikovad74/telegram-expense-bot.git"
APP_DIR="/opt/telegram-expense-bot"
DATA_DIR="/var/lib/telegram-expense-bot"
ENV_FILE="/etc/telegram-expense-bot.env"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run with sudo: sudo ./deploy/oracle/install.sh"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip git

if ! id -u expensebot >/dev/null 2>&1; then
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin expensebot
fi

if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" pull --ff-only
fi

install -d -o expensebot -g expensebot "$DATA_DIR"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<'EOF'
BOT_TOKEN=PASTE_NEW_TOKEN_HERE
DB_PATH=/var/lib/telegram-expense-bot/expenses.db
EOF
  chmod 600 "$ENV_FILE"
  chown root:root "$ENV_FILE"
  echo
  echo "Created $ENV_FILE. Edit it and replace PASTE_NEW_TOKEN_HERE with the NEW token from @BotFather."
fi

cat > /etc/systemd/system/telegram-expense-bot.service <<EOF
[Unit]
Description=Telegram Expense Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=expensebot
Group=expensebot
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/bot.py
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=$DATA_DIR

[Install]
WantedBy=multi-user.target
EOF

chown -R expensebot:expensebot "$APP_DIR"
systemctl daemon-reload
systemctl enable telegram-expense-bot
echo
echo "Installation prepared."
echo "1) Edit token: sudo nano $ENV_FILE"
echo "2) Start:      sudo systemctl start telegram-expense-bot"
echo "3) Status:     sudo systemctl status telegram-expense-bot --no-pager"
echo "4) Logs:       sudo journalctl -u telegram-expense-bot -n 50 --no-pager"
