#!/usr/bin/env bash
# 在 demo 目录下执行: ./run_demo.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
source "${SCRIPT_DIR}/../../../bin/env.sh"
cd "$SCRIPT_DIR"
cellflow run run_config.yaml
