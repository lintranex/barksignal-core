#!/usr/bin/env bash
set -euo pipefail

CFG="/home/barksignal/barksignal/config.ini"
APP_DIR="/home/barksignal/barksignal"
REPO_DIR="/home/barksignal/barksignal-repo"

python3 - <<'PY'
import configparser, os, subprocess, sys
cp=configparser.ConfigParser()
cp.read("/home/barksignal/barksignal/config.ini")
repo=cp.get("barksignal","repo_url",fallback="").strip()
branch=cp.get("barksignal","repo_branch",fallback="main").strip()
auto=cp.getboolean("barksignal","auto_update",fallback=True)
print(repo)
print(branch)
print("1" if auto else "0")
PY > /tmp/bs_upd.txt

REPO_URL="$(sed -n '1p' /tmp/bs_upd.txt)"
BRANCH="$(sed -n '2p' /tmp/bs_upd.txt)"
AUTO="$(sed -n '3p' /tmp/bs_upd.txt)"

if [[ "${AUTO}" != "1" ]]; then
  echo "[update] auto_update disabled"
  exit 0
fi

if [[ -z "${REPO_URL}" || "${REPO_URL}" == *"CHANGE-ME"* ]]; then
  echo "[update] repo_url not set; skip"
  exit 0
fi

# Clone or pull
if [[ ! -d "${REPO_DIR}/.git" ]]; then
  rm -rf "${REPO_DIR}"
  sudo -u barksignal git clone --depth 1 --branch "${BRANCH}" "${REPO_URL}" "${REPO_DIR}"
else
  sudo -u barksignal bash -lc "cd '${REPO_DIR}' && git fetch --all --prune && git reset --hard 'origin/${BRANCH}'"
fi

# Copy only code files; NEVER overwrite config.ini
rsync -a --delete   --exclude "config.ini"   --exclude ".wifi_configured" --exclude ".dog_configured" --exclude ".configured"   "${REPO_DIR}/" "${APP_DIR}/"

systemctl restart barksignal-detector.service || true
systemctl restart barksignal-portal.service || true
echo "[update] done"
