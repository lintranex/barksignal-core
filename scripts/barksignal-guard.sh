#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/barksignal/barksignal"
FLAG_WIFI="${APP_DIR}/.wifi_configured"
FLAG_DOG="${APP_DIR}/.dog_configured"
CONFIG_INI="${APP_DIR}/config.ini"
SSID="BarkSignal"
IFACE="wlan0"

internet_ok() {
  curl -s --max-time 3 -I https://www.barksignal.com >/dev/null 2>&1
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

add_redirect() {
  iptables -t nat -C PREROUTING -i "${IFACE}" -p tcp --dport 80 -j REDIRECT --to-ports 8080 2>/dev/null     || iptables -t nat -A PREROUTING -i "${IFACE}" -p tcp --dport 80 -j REDIRECT --to-ports 8080
}

del_redirect() {
  while iptables -t nat -C PREROUTING -i "${IFACE}" -p tcp --dport 80 -j REDIRECT --to-ports 8080 2>/dev/null; do
    iptables -t nat -D PREROUTING -i "${IFACE}" -p tcp --dport 80 -j REDIRECT --to-ports 8080
  done
}

start_hotspot() {
  nmcli radio wifi on || true
  nmcli con down "${SSID}" >/dev/null 2>&1 || true
  nmcli con delete "${SSID}" >/dev/null 2>&1 || true
  nmcli dev wifi hotspot ifname "${IFACE}" ssid "${SSID}" || true
  add_redirect
  systemctl start barksignal-portal.service || true
  systemctl stop barksignal-detector.service || true
}

stop_hotspot() {
  del_redirect
  systemctl stop barksignal-portal.service || true
  nmcli con down "${SSID}" >/dev/null 2>&1 || true
}

start_portal() {
  systemctl start barksignal-portal.service || true
}

stop_portal() {
  systemctl stop barksignal-portal.service || true
}

start_detector() {
  systemctl start barksignal-detector.service || true
}

stop_detector() {
  systemctl stop barksignal-detector.service || true
}

while true; do
  WIFI_OK=0
  DOG_OK=0
  [[ -f "${FLAG_WIFI}" ]] && WIFI_OK=1
  [[ -f "${FLAG_DOG}" ]] && DOG_OK=1

  if [[ "${DOG_OK}" -eq 0 ]]; then
    if [[ "$(dog_id_is_set)" == "1" ]]; then
      DOG_OK=1
      touch "${FLAG_DOG}" || true
    fi
  fi

  if [[ "${WIFI_OK}" -eq 0 ]]; then
    stop_detector
    start_hotspot
  else
    if internet_ok; then
      stop_hotspot
      if [[ "${DOG_OK}" -eq 0 ]]; then
        stop_detector
        start_portal
      else
        stop_portal
        start_detector
      fi
    else
      stop_detector
      start_hotspot
    fi
  fi

  sleep 10
done
