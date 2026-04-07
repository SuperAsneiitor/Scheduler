#!/usr/bin/env bash
# EDA Scheduler / GDS-to-K 运行环境：由项目根 bin 提供统一入口。
_FLOW_ENV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
export FLOW_ROOT="$(cd "${_FLOW_ENV_DIR}/.." && pwd)"
unset _FLOW_ENV_DIR
export PATH="${FLOW_ROOT}/bin:${PATH}"
export PYTHONPATH="${FLOW_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
echo "[eda-scheduler] 环境已加载: FLOW_ROOT=${FLOW_ROOT}"
