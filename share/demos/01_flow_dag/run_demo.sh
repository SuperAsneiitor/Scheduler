#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
source "${SCRIPT_DIR}/../../../bin/env.sh"
cd "$SCRIPT_DIR"
cellflow run run_config.yaml

