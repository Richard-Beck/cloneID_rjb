#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH=$(readlink -f "${BASH_SOURCE[0]}")
CONFIG_PATH=${1:-${INGEST_CONFIG_PATH:-}}
DRY_RUN=${DRY_RUN:-0}

if [[ -z "$CONFIG_PATH" ]]; then
  printf 'Usage: %s DEPLOY_CONFIG_JSON\n' "$0" >&2
  exit 2
fi
CONFIG_PATH=$(readlink -f "$CONFIG_PATH")
if [[ ! -f "$CONFIG_PATH" ]]; then
  printf 'Deployment config is not a file: %s\n' "$CONFIG_PATH" >&2
  exit 2
fi
if ! jq -e '.schema_version == 1' "$CONFIG_PATH" >/dev/null; then
  printf 'Deployment config must be JSON with schema_version 1: %s\n' "$CONFIG_PATH" >&2
  exit 2
fi

CONFIG_DIR=$(dirname "$CONFIG_PATH")
json_required() {
  local query=$1 label=$2 value
  value=$(jq -er "$query | select(type == \"string\" and length > 0)" "$CONFIG_PATH") || {
    printf 'Missing or invalid config value: %s\n' "$label" >&2
    exit 2
  }
  printf '%s' "$value"
}
resolve_path() {
  local value=$1
  if [[ "$value" == /* ]]; then
    readlink -m "$value"
  else
    readlink -m "$CONFIG_DIR/$value"
  fi
}

PROJECT_ROOT=$(resolve_path "$(json_required '.project_root' project_root)")
RUN_DIR=$(resolve_path "$(json_required '.run_dir' run_dir)")
TASKS_JSONL=$(resolve_path "$(json_required '.tasks_jsonl' tasks_jsonl)")
PROMPT_TEMPLATE=$(resolve_path "$(json_required '.prompt_template' prompt_template)")
PROMPT_RENDERER=$(resolve_path "$(json_required '.prompt_renderer' prompt_renderer)")
OUTPUT_SCHEMA_RAW=$(jq -r '.output_schema // empty' "$CONFIG_PATH")
OUTPUT_SCHEMA=
[[ -n "$OUTPUT_SCHEMA_RAW" ]] && OUTPUT_SCHEMA=$(resolve_path "$OUTPUT_SCHEMA_RAW")

CODEX_BIN=$(json_required '.agent.codex_bin' agent.codex_bin)
MODEL=$(json_required '.agent.model' agent.model)
REASONING=$(json_required '.agent.reasoning' agent.reasoning)
SANDBOX_MODE=$(json_required '.agent.sandbox' agent.sandbox)
APPROVAL_POLICY=$(json_required '.agent.approval_policy' agent.approval_policy)

JOB_NAME=$(json_required '.slurm.job_name' slurm.job_name)
TIME_LIMIT=$(json_required '.slurm.time' slurm.time)
MEMORY=$(json_required '.slurm.memory' slurm.memory)
CPUS=$(jq -er '.slurm.cpus | select(type == "number" and . >= 1 and floor == .)' "$CONFIG_PATH")
QOS=$(json_required '.slurm.qos' slurm.qos)
PARTITION=$(jq -r '.slurm.partition // empty' "$CONFIG_PATH")
ACCOUNT=$(jq -r '.slurm.account // empty' "$CONFIG_PATH")
ARRAY_CONCURRENCY=$(jq -r '.slurm.array_concurrency // empty' "$CONFIG_PATH")

for required_path in "$TASKS_JSONL" "$PROMPT_TEMPLATE" "$PROMPT_RENDERER"; do
  if [[ ! -f "$required_path" ]]; then
    printf 'Configured input is not a file: %s\n' "$required_path" >&2
    exit 2
  fi
done
if [[ -n "$OUTPUT_SCHEMA" && ! -f "$OUTPUT_SCHEMA" ]]; then
  printf 'Configured output schema is not a file: %s\n' "$OUTPUT_SCHEMA" >&2
  exit 2
fi
if [[ ! -d "$PROJECT_ROOT" ]]; then
  printf 'Configured project root is not a directory: %s\n' "$PROJECT_ROOT" >&2
  exit 2
fi
if [[ ! "$CPUS" =~ ^[1-9][0-9]*$ ]]; then
  printf 'slurm.cpus must be a positive integer.\n' >&2
  exit 2
fi
if [[ -n "$ARRAY_CONCURRENCY" && ! "$ARRAY_CONCURRENCY" =~ ^[1-9][0-9]*$ ]]; then
  printf 'slurm.array_concurrency must be null or a positive integer.\n' >&2
  exit 2
fi
if [[ ! "$JOB_NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then
  printf 'slurm.job_name contains unsafe characters: %s\n' "$JOB_NAME" >&2
  exit 2
fi
if [[ "$SANDBOX_MODE" != "read-only" && "$SANDBOX_MODE" != "workspace-write" && "$SANDBOX_MODE" != "danger-full-access" ]]; then
  printf 'agent.sandbox is invalid: %s\n' "$SANDBOX_MODE" >&2
  exit 2
fi

if ! jq -s -e '
  length > 0
  and all(.[]; type == "object" and (.task_id | type == "string" and test("^[A-Za-z0-9][A-Za-z0-9._-]*$")))
  and ((map(.task_id) | length) == (map(.task_id) | unique | length))
' "$TASKS_JSONL" >/dev/null; then
  printf 'Task manifest must contain nonempty objects with unique filesystem-safe task_id values.\n' >&2
  exit 2
fi
TASK_COUNT=$(jq -s 'length' "$TASKS_JSONL")
ARRAY_SPEC="1-$TASK_COUNT"
[[ -n "$ARRAY_CONCURRENCY" ]] && ARRAY_SPEC+="%$ARRAY_CONCURRENCY"

if [[ "$DRY_RUN" == "1" ]]; then
  printf 'DRY_RUN\n'
  printf 'CONFIG_PATH=%s\nPROJECT_ROOT=%s\nRUN_DIR=%s\nTASKS=%s\nARRAY=%s\n' \
    "$CONFIG_PATH" "$PROJECT_ROOT" "$RUN_DIR" "$TASK_COUNT" "$ARRAY_SPEC"
  printf 'MODEL=%s\nREASONING=%s\nSANDBOX=%s\n' "$MODEL" "$REASONING" "$SANDBOX_MODE"
  printf 'TIME=%s\nMEMORY=%s\nCPUS=%s\nQOS=%s\n' "$TIME_LIMIT" "$MEMORY" "$CPUS" "$QOS"
  exit 0
fi

if [[ -z "${SLURM_ARRAY_TASK_ID:-}" ]]; then
  mkdir -p "$RUN_DIR/logs"
  sbatch_args=(
    --parsable
    --job-name="$JOB_NAME"
    --array="$ARRAY_SPEC"
    --time="$TIME_LIMIT"
    --nodes=1
    --ntasks=1
    --cpus-per-task="$CPUS"
    --mem="$MEMORY"
    --qos="$QOS"
    --chdir="$PROJECT_ROOT"
    --output="$RUN_DIR/logs/slurm-%A_%a.out"
    --error="$RUN_DIR/logs/slurm-%A_%a.err"
    --export=ALL
  )
  [[ -n "$PARTITION" ]] && sbatch_args+=(--partition="$PARTITION")
  [[ -n "$ACCOUNT" ]] && sbatch_args+=(--account="$ACCOUNT")
  while IFS= read -r extra_arg; do
    [[ -n "$extra_arg" ]] && sbatch_args+=("$extra_arg")
  done < <(jq -r '.slurm.extra_args[]?' "$CONFIG_PATH")

  printf 'Submitting %s tasks as array %s.\n' "$TASK_COUNT" "$ARRAY_SPEC"
  exec sbatch "${sbatch_args[@]}" "$SCRIPT_PATH" "$CONFIG_PATH"
fi

if [[ ! "$SLURM_ARRAY_TASK_ID" =~ ^[1-9][0-9]*$ || "$SLURM_ARRAY_TASK_ID" -gt "$TASK_COUNT" ]]; then
  printf 'SLURM_ARRAY_TASK_ID is outside the task manifest: %s\n' "$SLURM_ARRAY_TASK_ID" >&2
  exit 2
fi
TASK_JSON=$(jq -c -s ".[$((SLURM_ARRAY_TASK_ID - 1))]" "$TASKS_JSONL")
TASK_ID=$(jq -r '.task_id' <<< "$TASK_JSON")
TASK_OUTPUT_DIR="$RUN_DIR/tasks/$TASK_ID"
if [[ -e "$TASK_OUTPUT_DIR" ]]; then
  printf 'Refusing to overwrite task output directory: %s\n' "$TASK_OUTPUT_DIR" >&2
  exit 2
fi
mkdir -p "$TASK_OUTPUT_DIR"

if [[ "$CODEX_BIN" == */* ]]; then
  CODEX_BIN=$(resolve_path "$CODEX_BIN")
  if [[ ! -x "$CODEX_BIN" ]]; then
    printf 'Configured Codex executable is unavailable: %s\n' "$CODEX_BIN" >&2
    exit 2
  fi
elif ! CODEX_BIN=$(command -v "$CODEX_BIN"); then
  printf 'Configured Codex command is unavailable.\n' >&2
  exit 2
fi

python3 "$PROMPT_RENDERER" \
  --template "$PROMPT_TEMPLATE" \
  --task-json "$TASK_JSON" \
  --task-index "$SLURM_ARRAY_TASK_ID" \
  --project-root "$PROJECT_ROOT" \
  --task-output-dir "$TASK_OUTPUT_DIR" \
  --output "$TASK_OUTPUT_DIR/prompt.txt"

{
  printf 'slurm_job_id=%s\n' "${SLURM_JOB_ID:-}"
  printf 'slurm_array_task_id=%s\n' "$SLURM_ARRAY_TASK_ID"
  printf 'task_id=%s\n' "$TASK_ID"
  printf 'started_at=%s\n' "$(date --iso-8601=seconds)"
  printf 'config_path=%s\n' "$CONFIG_PATH"
  printf 'model=%s\nreasoning=%s\nsandbox=%s\n' "$MODEL" "$REASONING" "$SANDBOX_MODE"
  "$CODEX_BIN" --version
} > "$TASK_OUTPUT_DIR/run_metadata.txt"

codex_args=(
  exec
  --cd "$PROJECT_ROOT"
  --model "$MODEL"
  --config "model_reasoning_effort=\"$REASONING\""
  --config "approval_policy=\"$APPROVAL_POLICY\""
  --sandbox "$SANDBOX_MODE"
  --json
  --output-last-message "$TASK_OUTPUT_DIR/final_message.json"
)
[[ -n "$OUTPUT_SCHEMA" ]] && codex_args+=(--output-schema "$OUTPUT_SCHEMA")
codex_args+=(-)

set +e
"$CODEX_BIN" "${codex_args[@]}" < "$TASK_OUTPUT_DIR/prompt.txt" | tee "$TASK_OUTPUT_DIR/codex_events.jsonl"
codex_status=${PIPESTATUS[0]}
set -e

{
  printf 'finished_at=%s\n' "$(date --iso-8601=seconds)"
  printf 'codex_exit_status=%s\n' "$codex_status"
} >> "$TASK_OUTPUT_DIR/run_metadata.txt"
exit "$codex_status"

