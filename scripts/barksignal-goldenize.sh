#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/barksignal/barksignal"
DATA_DIR="/home/barksignal/barksignal-data"
CFG="${DATA_DIR}/config.ini"
if [[ ! -f "${CFG}" ]]; then
  CFG="${APP_DIR}/config.ini"
fi

systemctl stop barksignal-detector.service || true
systemctl stop barksignal-portal.service || true
systemctl stop barksignal-guard.service || true
systemctl stop barksignal-update.timer || true
systemctl stop barksignal-update.service || true

if [[ -d "${DATA_DIR}" ]]; then
  rm -f \
    "${DATA_DIR}/.wifi_configured" \
    "${DATA_DIR}/.dog_configured" \
    "${DATA_DIR}/.configured" \
    "${DATA_DIR}/.pairing_state.json" \
    "${DATA_DIR}/.rescue" \
    || true
else
  rm -f \
    "${APP_DIR}/.wifi_configured" \
    "${APP_DIR}/.dog_configured" \
    "${APP_DIR}/.configured" \
    "${APP_DIR}/.pairing_state.json" \
    "${APP_DIR}/.rescue" \
    || true
fi

CFG_PATH="${CFG}" python3 - <<'PY'
import configparser
p = __import__("os").environ["CFG_PATH"]
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
