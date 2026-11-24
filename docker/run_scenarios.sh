#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_DIR="${WORKSPACE_PATH:-/workspace}"
DATA_DIR="${AGENTSOCIETY_HOME_DIR:-/data/agentsociety_data}"
MAP_FILE="${DATA_DIR}/beijing.pb"
MAP_URL="https://cloud.tsinghua.edu.cn/f/f5c777485d2748fa8535/?dl=1"

H1_INIT_DIR="${WORKSPACE_DIR}/hypothesis_1/experiment_1/init"
H1_RUN_DIR="${WORKSPACE_DIR}/hypothesis_1/experiment_1/run"
H2_RUN_DIR="${WORKSPACE_DIR}/hypothesis_2/experiment_1/run"

echo "[sim-runner] Workspace: ${WORKSPACE_DIR}"
echo "[sim-runner] Data dir:  ${DATA_DIR}"
echo "[sim-runner] Model:     ${AGENTSOCIETY_LLM_MODEL:-unset}"

if [ ! -d "${WORKSPACE_DIR}/.agentsociety" ]; then
    echo "[sim-runner] Initializing workspace..."
    python -m agentsociety2.society.workspace init --target-dir "${WORKSPACE_DIR}" --skip-map
fi

mkdir -p "${DATA_DIR}" "${H1_INIT_DIR}" "${H1_RUN_DIR}" "${H2_RUN_DIR}"

if [ ! -f "${MAP_FILE}" ] || [ "$(wc -c < "${MAP_FILE}")" -lt 100000000 ]; then
    echo "[sim-runner] Downloading Beijing map to ${MAP_FILE}..."
    rm -f "${MAP_FILE}.tmp"
    curl -fSL --retry 3 --connect-timeout 30 "${MAP_URL}" -o "${MAP_FILE}.tmp"
    mv "${MAP_FILE}.tmp" "${MAP_FILE}"
    echo "[sim-runner] Map downloaded: $(wc -c < "${MAP_FILE}") bytes"
else
    echo "[sim-runner] Reusing existing Beijing map: $(wc -c < "${MAP_FILE}") bytes"
fi

echo "[sim-runner] Preparing clean run directories..."
find "${H1_INIT_DIR}" -mindepth 1 -delete
find "${H1_RUN_DIR}" -mindepth 1 -delete
find "${H2_RUN_DIR}" -mindepth 1 -delete

echo "============================================================"
echo "[Scenario 1] Daily Mobility (3 agents, 6 hours: 07:00 -> 13:00)"
echo "============================================================"

export DAILY_MOBILITY_PRESET="benchmark"
export DAILY_MOBILITY_NUM_AGENTS="3"
export DAILY_MOBILITY_START_T="2018-06-13T07:00:00"
export DAILY_MOBILITY_DURATION_HOURS="6"
export DAILY_MOBILITY_SLOT_MINUTES="30"
export DAILY_MOBILITY_TICK_SEC="1800"
export DAILY_MOBILITY_MAX_TOOL_ROUNDS="6"
export DAILY_MOBILITY_MAP_PATH="${MAP_FILE}"
export DAILY_MOBILITY_PROFILES_PATH="/app/packages/agentsociety2/profiles.json"
export DAILY_MOBILITY_INIT_DIR="${H1_INIT_DIR}"
export DAILY_MOBILITY_RUN_DIR="${H1_RUN_DIR}"

python /app/examples/v2/daily_mobility/init/config_params.py

python -m agentsociety2.society.cli \
    --config "${H1_INIT_DIR}/init_config.json" \
    --steps "${H1_INIT_DIR}/steps.yaml" \
    --run-dir "${H1_RUN_DIR}" \
    --experiment-id "1_1" \
    --log-level INFO \
    --log-file "${H1_RUN_DIR}/output.log"

echo "============================================================"
echo "[Scenario 2] Prisoner's Dilemma (2 agents x 2 rounds)"
echo "============================================================"

python /app/docker/run_prisoners_dilemma.py \
    --run-dir "${H2_RUN_DIR}" \
    --experiment-id "2_1"

echo "============================================================"
echo "[sim-runner] Both real scenarios completed successfully!"
echo "============================================================"
