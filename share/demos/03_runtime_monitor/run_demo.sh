#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
source "${SCRIPT_DIR}/../../../bin/env.sh"
cd "$SCRIPT_DIR"

cellflow run run_config.yaml

echo ""
echo "你可以检查工作目录下 jobs/monitored_task/:"
echo "  - .running（运行期间存在）"
echo "  - status.json（结束后生成）"

