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

get_hotspot_delay_sec() {
  python3 - <<'PY'
import configparser
cp=configparser.ConfigParser()
cp.read("/home/barksignal/barksignal/config.ini")
try:
  val = cp.getint("hotspot","start_delay_sec",fallback=60)
except Exception:
  val = 60
print(max(0, val))
PY
}

uptime_seconds() {
  local up
  up="$(cut -d' ' -f1 /proc/uptime 2>/dev/null || echo 0)"
  printf '%.0f\n' "${up}"
}

hotspot_delay_passed() {
  local delay now
  delay="$(get_hotspot_delay_sec)"
  now="$(uptime_seconds)"
  [[ "${now}" -ge "${delay}" ]]
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

active_wifi_conn_name() {
  nmcli -t -f NAME,DEVICE,TYPE con show --active 2>/dev/null \
    | awk -F: -v dev="${IFACE}" '($2==dev && ($3=="wifi" || $3=="802-11-wireless")) {print $1; exit}'
}

wifi_connected() {
  # Treat wlan0 as connected only if an active *wifi* connection exists
  # and it's not our Hotspot.
  local name
  name="$(active_wifi_conn_name)"
  [[ -n "${name}" && "${name}" != "${HOTSPOT_NAME}" ]]
}

hotspot_active() {
  local name
  name="$(active_wifi_conn_name)"
  [[ "${name}" == "${HOTSPOT_NAME}" ]]
}

wifi_radio_enabled() {
  nmcli -t -f WIFI radio 2>/dev/null | grep -qi "^enabled$"
}

ensure_wifi_radio_on() {
  if ! wifi_radio_enabled; then
    nmcli radio wifi on || true
  fi
}

start_hotspot() {
  ensure_wifi_radio_on
  if ! hotspot_active; then
    ensure_hotspot_profile
    nmcli con up "${HOTSPOT_NAME}" || true
  fi
  ensure_http_redirect
  systemctl start barksignal-portal.service || true
}

stop_hotspot() {
  remove_http_redirect
  if hotspot_active; then
    nmcli con down "${HOTSPOT_NAME}" >/dev/null 2>&1 || true
  fi
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
    systemctl start barksignal-portal.service || true
    if [[ "${DOG_OK}" -eq 1 ]]; then
      stop_detector
      start_detector
    else
      stop_detector
    fi
  else
    stop_detector
    if hotspot_delay_passed; then
      start_hotspot
    else
      # Give Wi-Fi a fair chance to connect before starting AP.
      systemctl stop barksignal-portal.service || true
    fi
  fi

  sleep 5
done
