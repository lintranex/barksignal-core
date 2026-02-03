#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/barksignal/barksignal"
FLAG_DOG="${APP_DIR}/.dog_configured"
CONFIG="${APP_DIR}/config.ini"

IFACE="wlan0"
HOTSPOT_NAME="Hotspot"   # NetworkManager internal hotspot name
DEFAULT_HOTSPOT_SSID="BarkSignal"
DEFAULT_HOTSPOT_PSK="BarkSignal1234"

ensure_http_redirect() {
  # Redirect all HTTP on the hotspot interface to the portal (8080).
  if ! iptables -t nat -C PREROUTING -i "${IFACE}" -p tcp --dport 80 -j REDIRECT --to-ports 8080 >/dev/null 2>&1; then
    iptables -t nat -A PREROUTING -i "${IFACE}" -p tcp --dport 80 -j REDIRECT --to-ports 8080 || true
  fi
}

remove_http_redirect() {
  iptables -t nat -D PREROUTING -i "${IFACE}" -p tcp --dport 80 -j REDIRECT --to-ports 8080 >/dev/null 2>&1 || true
}

get_hotspot_cfg() {
  python3 - <<'PY'
import configparser
cp=configparser.ConfigParser()
cp.read("/home/barksignal/barksignal/config.ini")
ssid=cp.get("hotspot","ssid",fallback="BarkSignal").strip()
psk=cp.get("hotspot","psk",fallback="BarkSignal1234").strip()
print(ssid)
print(psk)
PY
}

ensure_hotspot_profile() {
  local ssid psk
  mapfile -t _cfg < <(get_hotspot_cfg)
  ssid="${_cfg[0]}"
  psk="${_cfg[1]}"

  [[ -z "${ssid}" ]] && ssid="${DEFAULT_HOTSPOT_SSID}"
  if [[ -z "${psk}" || "${#psk}" -lt 8 ]]; then
    psk="${DEFAULT_HOTSPOT_PSK}"
  fi

  if ! nmcli -t -f NAME con show | grep -Fxq "${HOTSPOT_NAME}"; then
    nmcli dev wifi hotspot ifname "${IFACE}" con-name "${HOTSPOT_NAME}" ssid "${ssid}" password "${psk}" || true
  else
    nmcli con modify "${HOTSPOT_NAME}" 802-11-wireless.ssid "${ssid}" >/dev/null 2>&1 || true
    nmcli con modify "${HOTSPOT_NAME}" 802-11-wireless-security.key-mgmt wpa-psk >/dev/null 2>&1 || true
    nmcli con modify "${HOTSPOT_NAME}" 802-11-wireless-security.psk "${psk}" >/dev/null 2>&1 || true
  fi
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
  # Treat the Hotspot connection as "not connected" so we don't flap it.
  nmcli -t -f DEVICE,TYPE,STATE,CONNECTION dev status \
    | grep -E '^wlan0:wifi:connected:' \
    | grep -v ":${HOTSPOT_NAME}$" \
    >/dev/null 2>&1
}

start_hotspot() {
  nmcli radio wifi on || true
  ensure_hotspot_profile
  nmcli con up "${HOTSPOT_NAME}" || true
  ensure_http_redirect
  systemctl start barksignal-portal.service || true
}

stop_hotspot() {
  systemctl stop barksignal-portal.service || true
  remove_http_redirect
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
