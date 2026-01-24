#!/usr/bin/env bash
set -euo pipefail

FLAG="/etc/barksignal-firstboot.done"

get_mac_suffix() {
  local mac
  mac="$(cat /sys/class/net/wlan0/address 2>/dev/null || true)"
  if [[ -z "$mac" ]]; then
    mac="$(cat /sys/class/net/eth0/address 2>/dev/null || true)"
  fi
  mac="${mac//:/}"
  echo "${mac: -4}" | tr '[:lower:]' '[:upper:]'
}

set_hostname_unique() {
  local suffix newhost oldhost
  suffix="$(get_mac_suffix)"
  newhost="barksignal-${suffix}"
  oldhost="$(hostname)"
  if [[ "$oldhost" == "$newhost" ]]; then return; fi
  hostnamectl set-hostname "$newhost"
  if grep -qE '^127\.0\.1\.1' /etc/hosts; then
    sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t${newhost}/" /etc/hosts
  else
    echo -e "127.0.1.1\t${newhost}" >> /etc/hosts
  fi
}

regen_ssh_hostkeys() {
  rm -f /etc/ssh/ssh_host_* || true
  dpkg-reconfigure openssh-server >/dev/null 2>&1 || true
  systemctl restart ssh || true
}

regen_machine_id() {
  truncate -s 0 /etc/machine-id || true
  rm -f /var/lib/dbus/machine-id || true
  ln -sf /etc/machine-id /var/lib/dbus/machine-id || true
  systemd-machine-id-setup >/dev/null 2>&1 || true
}

main() {
  [[ -f "$FLAG" ]] && exit 0
  set_hostname_unique
  regen_machine_id
  regen_ssh_hostkeys
  touch "$FLAG"
}
main "$@"
