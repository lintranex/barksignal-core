#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/barksignal/barksignal"

systemctl stop barksignal-detector.service || true
systemctl stop barksignal-portal.service || true
systemctl stop barksignal-guard.service || true
systemctl stop barksignal-update.timer || true
systemctl stop barksignal-update.service || true

rm -f "${APP_DIR}/.wifi_configured" "${APP_DIR}/.dog_configured" "${APP_DIR}/.configured" || true

python3 - <<'PY'
import configparser
p="/home/barksignal/barksignal/config.ini"
cp=configparser.ConfigParser()
cp.read(p)
if "barksignal" not in cp: cp["barksignal"]={}
cp["barksignal"]["dog_id"]="DEMO"
with open(p,"w") as f: cp.write(f)
print("dog_id reset to DEMO")
PY

rm -f /etc/ssh/ssh_host_* || true
truncate -s 0 /etc/machine-id || true
rm -f /var/lib/dbus/machine-id || true
ln -sf /etc/machine-id /var/lib/dbus/machine-id || true

rm -f /etc/NetworkManager/system-connections/*.nmconnection || true

journalctl --rotate || true
journalctl --vacuum-time=1s || true
rm -rf /var/log/journal/* || true
apt-get clean || true
sync

echo "Goldenize done. Power off and image the SD card."
