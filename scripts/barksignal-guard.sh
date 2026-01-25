#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/barksignal/barksignal"
FLAG_WIFI="${APP_DIR}/.wifi_configured"
FLAG_DOG="${APP_DIR}/.dog_configured"
CONFIG_INI="${APP_DIR}/config.ini"

SSID="BarkSignal"
IFACE="wlan0"

# Redirect captive HTTP -> portal (8080) while in hotspot mode
add_redirect() {
  iptables -t nat -C PREROUTING -i "${IFACE}" -p tcp --dport 80 -j REDIRECT --to-ports 8080 2>/dev/null \
    || iptables -t nat -A PREROUTING -i "${IFACE}" -p tcp --dport 80 -j REDIRECT --to-ports 8080
}

del_redirect() {
  while iptables -t nat -C PREROUTING -i "${IFACE}" -p tcp --dport 80 -j REDIRECT --to-ports 8080 2>/dev/null; do
    iptables -t nat -D PREROUTING -i "${IFACE}" -p tcp --dport 80 -j REDIRECT --to-ports 8080
  done
}

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
  # returns 0 (true) if wlan0 is connected via NetworkManager
  nmcli -t -f DEVICE,TYPE,STATE dev status | grep '^wlan0:wifi:connected' >/dev/null 2>&1
}

start_hotspot() {
  echo "[guard] start_hotspot"
  nmcli radio wifi on || true

  # Tear down any previous hotspot
  nmcli con down "${SSID}" >/dev/null 2>&1 || true
  nmcli con delete "${SSID}" >/dev/null 2>&1 || true

  # Start OPEN hotspot (no password)
  nmcli dev wifi hotspot ifname "${IFACE}" ssid "${SSID}" || true

  add_redirect
  systemctl start barksignal-portal.service || true
}

stop_hotspot() {
  echo "[guard] stop_hotspot"
  del_redirect
  systemctl stop barksignal-portal.service || true
  nmcli con down "${SSID}" >/dev/null 2>&1 || true
}

start_detector() {
  systemctl start barksignal-detector.service || true
}

stop_detector() {
  systemctl stop barksignal-detector.service || true
}

start_portal() {
  systemctl start barksignal-portal.service || true
}

stop_portal() {
  systemctl stop barksignal-portal.service || true
}

# Main loop:
# - If wlan0 not connected => setup mode (open AP + portal)
# - If wlan0 connected:
#     - If DOG_ID set => run detector (portal off)
#     - Else => run portal (for login/dog selection) but no hotspot
while true; do
  DOG_OK=0
  [[ -f "${FLAG_DOG}" ]] && DOG_OK=1

  if [[ "${DOG_OK}" -eq 0 ]]; then
    if [[ "$(dog_id_is_set)" == "1" ]]; then
      DOG_OK=1
      touch "${FLAG_DOG}" >/dev/null 2>&1 || true
    fi
  fi

  if wifi_connected; then
    # Normal mode (Wi-Fi connected)
    stop_hotspot

    if [[ "${DOG_OK}" -eq 1 ]]; then
      stop_portal
      start_detector
    else
      stop_detector
      start_portal
    fi
  else
    # Setup mode (Wi-Fi NOT connected)
    stop_detector
    start_hotspot
  fi

  sleep 5
done
