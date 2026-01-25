#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/barksignal/barksignal"
FLAG_DOG="${APP_DIR}/.dog_configured"

IFACE="wlan0"
HOTSPOT_NAME="Hotspot"   # NetworkManager internal hotspot name

dog_id_is_set() {
  python3 - <<'PY'
import configparser
cp=configparser.ConfigParser()
cp.read("/home/barksignal/barksignal/config.ini")
dog=cp.get("barksignal","dog_id",fallback="DEMO").strip()
print("1" if dog and dog.upper()!="DEMO" else "0")
PY
}

wifi_connected() {
  nmcli -t -f DEVICE,TYPE,STATE dev status | grep '^wlan0:wifi:connected' >/dev/null 2>&1
}

start_hotspot() {
  nmcli radio wifi on || true
  nmcli con up "${HOTSPOT_NAME}" || true
  systemctl start barksignal-portal.service || true
}

stop_hotspot() {
  systemctl stop barksignal-portal.service || true
  nmcli con down "${HOTSPOT_NAME}" >/dev/null 2>&1 || true
}

start_detector() {
  systemctl start barksignal-detector.service || true
}

stop_detector() {
  systemctl stop barksignal-detector.service || true
}

while true; do
  DOG_OK=0
  [[ -f "${FLAG_DOG}" ]] && DOG_OK=1

  if [[ "${DOG_OK}" -eq 0 ]]; then
    if [[ "$(dog_id_is_set)" == "1" ]]; then
      DOG_OK=1
      touch "${FLAG_DOG}" || true
    fi
  fi

  if wifi_connected; then
    stop_hotspot
    if [[ "${DOG_OK}" -eq 1 ]]; then
      stop_detector
      start_detector
    else
      stop_detector
      systemctl start barksignal-portal.service || true
    fi
  else
    stop_detector
    start_hotspot
  fi

  sleep 5
done
