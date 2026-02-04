#!/usr/bin/env bash
set -euo pipefail

APP_USER="barksignal"
APP_HOME="/home/${APP_USER}"
APP_DIR="${APP_HOME}/barksignal"
PORTAL_DIR="${APP_DIR}/portal"
VENV="${APP_HOME}/venv-barksignal"

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

need_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Run: sudo bash install.sh"
    exit 1
  fi
}

ensure_user() {
  if ! id -u "${APP_USER}" >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" "${APP_USER}"
  fi
  mkdir -p "${APP_DIR}" "${PORTAL_DIR}"
  chown -R "${APP_USER}:${APP_USER}" "${APP_HOME}"
}

apt_install() {
  apt-get update
  apt-get install -y     git rsync curl ca-certificates     python3 python3-venv python3-pip     libportaudio2 alsa-utils     iptables iw     openssh-server sudo     avahi-daemon     network-manager dnsmasq
}

configure_networkmanager() {
  systemctl enable --now NetworkManager
  systemctl enable --now avahi-daemon

  # avoid dhcpcd fighting NetworkManager
  systemctl disable --now dhcpcd 2>/dev/null || true

  # Captive DNS for hotspot: resolve all to 10.42.0.1
  mkdir -p /etc/NetworkManager/dnsmasq.d
  cat > /etc/NetworkManager/dnsmasq.d/99-barksignal-captive.conf <<'CONF'
address=/#/10.42.0.1
CONF
}

setup_venv() {
  sudo -u "${APP_USER}" python3 -m venv "${VENV}"
  sudo -u "${APP_USER}" "${VENV}/bin/pip" install --upgrade pip setuptools wheel
  sudo -u "${APP_USER}" "${VENV}/bin/pip" install -r "${SRC_DIR}/requirements.txt"
}

install_app_files() {
  # Copy detector + portal
  install -o "${APP_USER}" -g "${APP_USER}" -m 0755 "${SRC_DIR}/bark_detector.py" "${APP_DIR}/bark_detector.py"
  mkdir -p "${PORTAL_DIR}"
  install -o "${APP_USER}" -g "${APP_USER}" -m 0755 "${SRC_DIR}/portal/app.py" "${PORTAL_DIR}/app.py"

  # config.ini (only if not existing)
  if [[ ! -f "${APP_DIR}/config.ini" ]]; then
    install -o "${APP_USER}" -g "${APP_USER}" -m 0644 "${SRC_DIR}/config.ini" "${APP_DIR}/config.ini"
  fi
}

download_yamnet() {
  if [[ ! -f "${APP_DIR}/yamnet.tflite" ]]; then
    sudo -u "${APP_USER}" curl -L "https://storage.googleapis.com/audioset/yamnet.tflite" -o "${APP_DIR}/yamnet.tflite"
  fi
}

install_scripts_services() {
  install -m 0755 "${SRC_DIR}/scripts/barksignal-guard.sh" /usr/local/sbin/barksignal-guard.sh
  install -m 0755 "${SRC_DIR}/scripts/barksignal-update.sh" /usr/local/sbin/barksignal-update.sh
  install -m 0755 "${SRC_DIR}/scripts/barksignal-firstboot.sh" /usr/local/sbin/barksignal-firstboot.sh
  install -m 0755 "${SRC_DIR}/scripts/barksignal-goldenize.sh" /usr/local/sbin/barksignal-goldenize.sh
  install -m 0755 "${SRC_DIR}/scripts/barksignal-reboot.sh" /usr/local/sbin/barksignal-reboot.sh
  install -m 0755 "${SRC_DIR}/scripts/barksignal-healthcheck.sh" /usr/local/sbin/barksignal-healthcheck.sh

  install -m 0644 "${SRC_DIR}/systemd/barksignal-detector.service" /etc/systemd/system/barksignal-detector.service
  install -m 0644 "${SRC_DIR}/systemd/barksignal-portal.service" /etc/systemd/system/barksignal-portal.service
  install -m 0644 "${SRC_DIR}/systemd/barksignal-guard.service" /etc/systemd/system/barksignal-guard.service
  install -m 0644 "${SRC_DIR}/systemd/barksignal-update.service" /etc/systemd/system/barksignal-update.service
  install -m 0644 "${SRC_DIR}/systemd/barksignal-update.timer" /etc/systemd/system/barksignal-update.timer
  install -m 0644 "${SRC_DIR}/systemd/barksignal-firstboot.service" /etc/systemd/system/barksignal-firstboot.service
}

install_polkit_rules() {
  mkdir -p /etc/polkit-1/rules.d
  install -m 0644 "${SRC_DIR}/polkit/10-barksignal-nm.rules" /etc/polkit-1/rules.d/10-barksignal-nm.rules
  systemctl restart polkit || true
}

install_sudoers_rules() {
  mkdir -p /etc/sudoers.d
  install -m 0440 "${SRC_DIR}/sudoers/10-barksignal-reboot" /etc/sudoers.d/10-barksignal-reboot
}

enable_services() {
  systemctl daemon-reload
  systemctl enable --now barksignal-firstboot.service
  systemctl enable barksignal-detector.service
  systemctl enable barksignal-portal.service
  systemctl enable --now barksignal-guard.service
  systemctl enable --now barksignal-update.timer
}

main() {
  need_root
  apt_install
  configure_networkmanager
  ensure_user
  setup_venv
  install_app_files
  download_yamnet
  install_scripts_services
  install_polkit_rules
  install_sudoers_rules
  enable_services

  echo
  echo "✅ Installed."
  echo "Portal (when running): http://barksignal.local:8080  (or http://10.42.0.1 on hotspot)"
  echo "Logs:"
  echo "  journalctl -u barksignal-guard -f"
  echo "  journalctl -u barksignal-portal -f"
  echo "  journalctl -u barksignal-detector -f"
  echo
}

main "$@"
