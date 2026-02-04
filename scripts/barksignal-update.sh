#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/barksignal/barksignal"
DATA_DIR="/home/barksignal/barksignal-data"
RELEASES_DIR="/home/barksignal/barksignal-releases"
REPO_DIR="/home/barksignal/barksignal-repo"
CFG="${APP_DIR}/config.ini"
HEALTHCHECK="/usr/local/sbin/barksignal-healthcheck.sh"
RESCUE_FLAG="${DATA_DIR}/.rescue"

PREV_TARGET=""

log() {
  echo "[update] $*"
}

prune_releases() {
  local keep=4
  local entries=()
  local sorted=()

  shopt -s nullglob
  entries=( "${RELEASES_DIR}"/release-* "${RELEASES_DIR}"/legacy-* )
  shopt -u nullglob

  if (( ${#entries[@]} <= keep )); then
    return
  fi

  mapfile -t sorted < <(ls -dt "${entries[@]}" 2>/dev/null || true)
  if (( ${#sorted[@]} <= keep )); then
    return
  fi

  for ((i=keep; i<${#sorted[@]}; i++)); do
    rm -rf "${sorted[$i]}" || true
  done
}

rollback() {
  local reason="${1:-unknown}"
  trap - ERR
  log "rollback (${reason})"
  set +e
  if [[ -n "${PREV_TARGET}" && -d "${PREV_TARGET}" ]]; then
    ln -sfn "${PREV_TARGET}" "${APP_DIR}"
  fi
  mkdir -p "${DATA_DIR}" >/dev/null 2>&1 || true
  touch "${RESCUE_FLAG}" || true
  systemctl daemon-reload || true
  systemctl restart barksignal-guard || true
  systemctl restart barksignal-portal || true
}

on_fail() {
  local code=$?
  trap - ERR
  rollback "error"
  exit "${code}"
}
trap on_fail ERR

if [[ ! -f "${CFG}" ]]; then
  log "config.ini not found at ${CFG}"
  exit 1
fi

CFG_PATH="${CFG}" python3 - <<'PY' > /tmp/bs_upd.txt
import configparser
import os
cp = configparser.ConfigParser()
cp.read(os.environ["CFG_PATH"])

repo = cp.get("barksignal", "repo_url", fallback="").strip()
branch = cp.get("barksignal", "repo_branch", fallback="main").strip()
auto = cp.getboolean("barksignal", "auto_update", fallback=True)

print(repo)
print(branch)
print("1" if auto else "0")
PY

REPO_URL="$(sed -n '1p' /tmp/bs_upd.txt)"
BRANCH="$(sed -n '2p' /tmp/bs_upd.txt)"
AUTO="$(sed -n '3p' /tmp/bs_upd.txt)"

if [[ "${AUTO}" != "1" ]]; then
  log "auto_update disabled"
  exit 0
fi

if [[ -z "${REPO_URL}" || "${REPO_URL}" == *"CHANGE-ME"* ]]; then
  log "repo_url not set; skip"
  exit 0
fi

mkdir -p "${RELEASES_DIR}" "${DATA_DIR}"

if [[ -L "${APP_DIR}" ]]; then
  PREV_TARGET="$(readlink -f "${APP_DIR}")"
elif [[ -d "${APP_DIR}" ]]; then
  ts="$(date +%Y%m%d%H%M%S)"
  PREV_TARGET="${RELEASES_DIR}/legacy-${ts}"
  mv "${APP_DIR}" "${PREV_TARGET}"
  ln -s "${PREV_TARGET}" "${APP_DIR}"
else
  log "APP_DIR missing: ${APP_DIR}"
  exit 1
fi

if [[ -z "${PREV_TARGET}" || ! -d "${PREV_TARGET}" ]]; then
  log "previous release not found"
  exit 1
fi

persist=(config.ini .wifi_configured .dog_configured .configured .pairing_state.json .rescue yamnet.tflite)
for f in "${persist[@]}"; do
  src="${PREV_TARGET}/${f}"
  dest="${DATA_DIR}/${f}"
  if [[ ! -e "${dest}" && ( -e "${src}" || -L "${src}" ) ]]; then
    if [[ -L "${src}" ]]; then
      real="$(readlink -f "${src}" || true)"
      if [[ -n "${real}" && -e "${real}" && "${real}" != "${dest}" ]]; then
        cp -a "${real}" "${dest}"
      fi
    else
      cp -a "${src}" "${dest}"
    fi
  fi
done

chown -R barksignal:barksignal "${DATA_DIR}" || true

if [[ ! -f "${DATA_DIR}/config.ini" ]]; then
  log "config.ini missing in ${DATA_DIR}"
  exit 1
fi

# Clone or pull
if [[ ! -d "${REPO_DIR}/.git" ]]; then
  rm -rf "${REPO_DIR}"
  sudo -u barksignal git clone --depth 1 --branch "${BRANCH}" "${REPO_URL}" "${REPO_DIR}"
else
  sudo -u barksignal bash -lc "cd '${REPO_DIR}' && git fetch --all --prune && git reset --hard 'origin/${BRANCH}'"
fi

# Build new release
ts="$(date +%Y%m%d%H%M%S)"
NEW_RELEASE="${RELEASES_DIR}/release-${ts}"
mkdir -p "${NEW_RELEASE}"

rsync -a --delete \
  --exclude "config.ini" \
  --exclude ".wifi_configured" \
  --exclude ".dog_configured" \
  --exclude ".configured" \
  --exclude ".pairing_state.json" \
  --exclude ".rescue" \
  --exclude "yamnet.tflite" \
  "${REPO_DIR}/" "${NEW_RELEASE}/"

for f in "${persist[@]}"; do
  ln -sfn "${DATA_DIR}/${f}" "${NEW_RELEASE}/${f}"
done

ln -sfn "${NEW_RELEASE}" "${APP_DIR}"

# Ensure venv and install deps
VENV="/home/barksignal/venv-barksignal"
if [[ ! -x "${VENV}/bin/python" ]]; then
  sudo -u barksignal python3 -m venv "${VENV}"
  sudo -u barksignal "${VENV}/bin/pip" install --upgrade pip setuptools wheel
fi
sudo -u barksignal "${VENV}/bin/pip" install -r "${APP_DIR}/requirements.txt"

# Ensure model file exists (download once into data dir)
if [[ ! -f "${DATA_DIR}/yamnet.tflite" ]]; then
  log "download yamnet.tflite"
  sudo -u barksignal curl -fL "https://storage.googleapis.com/audioset/yamnet.tflite" -o "${DATA_DIR}/yamnet.tflite"
fi

# update system scripts
install -m 0755 "${REPO_DIR}/scripts/barksignal-guard.sh" /usr/local/sbin/barksignal-guard.sh
install -m 0755 "${REPO_DIR}/scripts/barksignal-update.sh" /usr/local/sbin/barksignal-update.sh
install -m 0755 "${REPO_DIR}/scripts/barksignal-firstboot.sh" /usr/local/sbin/barksignal-firstboot.sh
install -m 0755 "${REPO_DIR}/scripts/barksignal-goldenize.sh" /usr/local/sbin/barksignal-goldenize.sh
install -m 0755 "${REPO_DIR}/scripts/barksignal-reboot.sh" /usr/local/sbin/barksignal-reboot.sh
install -m 0755 "${REPO_DIR}/scripts/barksignal-healthcheck.sh" /usr/local/sbin/barksignal-healthcheck.sh

# update systemd units
install -m 0644 "${REPO_DIR}/systemd/"*.service /etc/systemd/system/
install -m 0644 "${REPO_DIR}/systemd/"*.timer /etc/systemd/system/

# update polkit rules
mkdir -p /etc/polkit-1/rules.d
install -m 0644 "${REPO_DIR}/polkit/10-barksignal-nm.rules" /etc/polkit-1/rules.d/10-barksignal-nm.rules
systemctl restart polkit || true

# update sudoers
mkdir -p /etc/sudoers.d
install -m 0440 "${REPO_DIR}/sudoers/10-barksignal-reboot" /etc/sudoers.d/10-barksignal-reboot

systemctl daemon-reload
systemctl restart barksignal-guard || true
systemctl restart barksignal-portal || true
systemctl restart barksignal-detector || true

sleep 5
if ! "${HEALTHCHECK}"; then
  rollback "healthcheck"
  exit 1
fi

rm -f "${RESCUE_FLAG}" || true
prune_releases
log "done"
