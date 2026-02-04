#!/usr/bin/env bash
set -euo pipefail

fail=0

if ! systemctl is-active --quiet barksignal-guard; then
  echo "[health] barksignal-guard not active"
  fail=1
fi

for unit in barksignal-portal barksignal-detector; do
  if systemctl is-failed --quiet "${unit}"; then
    echo "[health] ${unit} failed"
    fail=1
  fi
done

if [[ "${fail}" -ne 0 ]]; then
  exit 1
fi

echo "[health] ok"
