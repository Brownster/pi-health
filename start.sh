#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $EUID -ne 0 ]]; then
  exec sudo -E bash "${REPO_DIR}/setup.sh" "$@"
fi

exec bash "${REPO_DIR}/setup.sh" "$@"
