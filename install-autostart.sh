#!/usr/bin/env bash
# Автостарт на Linux: systemd --user юнит (доступ к звуку сессии, перезапуск при падении).
# Запуск:  ./install-autostart.sh   (один раз)
# Удалить: systemctl --user disable --now voice-bridge
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"

cat > "$UNIT_DIR/voice-bridge.service" << EOF
[Unit]
Description=Голосовой ассистент voice-bridge (живой разговор)
After=network-online.target sound.target

[Service]
Type=simple
WorkingDirectory=$REPO
ExecStart=$REPO/run.sh --talk
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable voice-bridge
echo "Готово: автостарт при входе. Запустить сейчас: systemctl --user start voice-bridge"
echo "Логи: journalctl --user -u voice-bridge -f"
