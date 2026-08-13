#!/usr/bin/env bash
set -euo pipefail

# Configurable execution defaults.
SCRIPT_PATH=$(readlink -f "${BASH_SOURCE[0]}")
ROOT_DIR=${ROOT_DIR:-$(dirname "$(dirname "$SCRIPT_PATH")")}
PLAN_DIR=${PLAN_DIR:-"$ROOT_DIR/plans/seed1_hypothesis_test_v3"}
PROMPT_TEMPLATE=${PROMPT_TEMPLATE:-"$ROOT_DIR/prompt_templates/codex_1shot_execution.txt"}
DESCRIPTIVE_ID=${DESCRIPTIVE_ID:-}

MODEL=${MODEL:-gpt-5.6-luna}
REASONING=${REASONING:-medium}
TIME=${TIME:-12:00:00}
MEM=${MEM:-16G}
CPUS=${CPUS:-4}
QOS=${QOS:-small}
JOB_NAME=${JOB_NAME:-codex_1shot${DESCRIPTIVE_ID:+_${DESCRIPTIVE_ID}}}

CODEX_BIN=${CODEX_BIN:-"$HOME/.conda/envs/codex/bin/codex"}
SANDBOX_MODE=${SANDBOX_MODE:-danger-full-access}
APPROVAL_POLICY=${APPROVAL_POLICY:-never}
PARTITION=${PARTITION:-}
ACCOUNT=${ACCOUNT:-}
EXTRA_SBATCH_ARGS=${EXTRA_SBATCH_ARGS:-}
DRY_RUN=${DRY_RUN:-0}

resolve_output_dir() {
  if [[ -n "${OUTPUT_DIR:-}" ]]; then
    OUTPUT_DIR=$(readlink -m "$OUTPUT_DIR")
    return
  fi

  local timestamp run_name candidate
  timestamp=${RUN_DATETIME:-$(date +%Y%m%d_%H%M%S)}
  if [[ ! "$timestamp" =~ ^[0-9]{8}_[0-9]{6}$ ]]; then
    printf 'RUN_DATETIME must use YYYYMMDD_HHMMSS, got: %s\n' "$timestamp" >&2
    exit 2
  fi
  if [[ -n "$DESCRIPTIVE_ID" && ! "$DESCRIPTIVE_ID" =~ ^[a-z0-9]+(_[a-z0-9]+)*$ ]]; then
    printf 'DESCRIPTIVE_ID must be lowercase snake case, got: %s\n' \
      "$DESCRIPTIVE_ID" >&2
    exit 2
  fi

  run_name=$timestamp
  [[ -n "$DESCRIPTIVE_ID" ]] && run_name+="_$DESCRIPTIVE_ID"
  candidate="$ROOT_DIR/hypothesis_tests/$run_name"
  if [[ -e "$candidate" ]]; then
    printf 'Generated OUTPUT_DIR already exists: %s\n' "$candidate" >&2
    exit 2
  fi
  OUTPUT_DIR=$candidate
}

resolve_output_dir

# DRY_RUN must take precedence even when invoked from a shell that already has
# SLURM_JOB_ID set (for example, an interactive allocation).
if [[ "$DRY_RUN" == "1" ]]; then
  printf 'DRY_RUN\n'
  printf 'PLAN_DIR=%s\n' "$PLAN_DIR"
  printf 'OUTPUT_DIR=%s\n' "$OUTPUT_DIR"
  printf 'DESCRIPTIVE_ID=%s\n' "$DESCRIPTIVE_ID"
  printf 'MODEL=%s\nREASONING=%s\nTIME=%s\nMEM=%s\nCPUS=%s\nQOS=%s\n' \
    "$MODEL" "$REASONING" "$TIME" "$MEM" "$CPUS" "$QOS"
  if [[ -z "${SLURM_JOB_ID:-}" ]]; then
    printf 'ACTION=submit\n'
  else
    printf 'ACTION=execute-within-slurm-job\n'
  fi
  exit 0
fi

mkdir -p "$OUTPUT_DIR"

export ROOT_DIR PLAN_DIR PROMPT_TEMPLATE DESCRIPTIVE_ID
export MODEL REASONING TIME MEM CPUS QOS JOB_NAME
export CODEX_BIN SANDBOX_MODE APPROVAL_POLICY OUTPUT_DIR

if [[ -z "${SLURM_JOB_ID:-}" ]]; then
  sbatch_args=(
    --job-name="$JOB_NAME"
    --time="$TIME"
    --nodes=1
    --ntasks=1
    --cpus-per-task="$CPUS"
    --mem="$MEM"
    --qos="$QOS"
    --chdir="$ROOT_DIR"
    --output="$OUTPUT_DIR/slurm-%j.out"
    --error="$OUTPUT_DIR/slurm-%j.err"
    --export=ALL
  )

  [[ -n "$PARTITION" ]] && sbatch_args+=(--partition="$PARTITION")
  [[ -n "$ACCOUNT" ]] && sbatch_args+=(--account="$ACCOUNT")

  if [[ -n "$EXTRA_SBATCH_ARGS" ]]; then
    # Intentional word splitting permits additional independent sbatch flags.
    # shellcheck disable=SC2206
    extra_args=( $EXTRA_SBATCH_ARGS )
    sbatch_args+=("${extra_args[@]}")
  fi

  printf 'PLAN_DIR=%s\nOUTPUT_DIR=%s\n' "$PLAN_DIR" "$OUTPUT_DIR"
  exec sbatch "${sbatch_args[@]}" "$SCRIPT_PATH"
fi

if [[ ! -d "$PLAN_DIR" ]]; then
  printf 'PLAN_DIR does not exist: %s\n' "$PLAN_DIR" >&2
  exit 2
fi
if [[ ! -f "$PROMPT_TEMPLATE" ]]; then
  printf 'Prompt template does not exist: %s\n' "$PROMPT_TEMPLATE" >&2
  exit 2
fi
if [[ ! -x "$CODEX_BIN" ]]; then
  printf 'Codex executable is unavailable: %s\n' "$CODEX_BIN" >&2
  exit 2
fi

RUN_PROMPT="$OUTPUT_DIR/run_prompt.txt"
{
  cat "$PROMPT_TEMPLATE"
  printf '\n\nPLAN_DIR: %s\nOUTPUT_DIR: %s\n' "$PLAN_DIR" "$OUTPUT_DIR"
} > "$RUN_PROMPT"

{
  printf 'slurm_job_id=%s\n' "$SLURM_JOB_ID"
  printf 'started_at=%s\n' "$(date --iso-8601=seconds)"
  printf 'root_dir=%s\n' "$ROOT_DIR"
  printf 'plan_dir=%s\n' "$PLAN_DIR"
  printf 'output_dir=%s\n' "$OUTPUT_DIR"
  printf 'descriptive_id=%s\n' "$DESCRIPTIVE_ID"
  printf 'prompt_template=%s\n' "$PROMPT_TEMPLATE"
  printf 'model=%s\n' "$MODEL"
  printf 'reasoning=%s\n' "$REASONING"
  printf 'time=%s\n' "$TIME"
  printf 'memory=%s\n' "$MEM"
  printf 'cpus=%s\n' "$CPUS"
  printf 'qos=%s\n' "$QOS"
  "$CODEX_BIN" --version
} > "$OUTPUT_DIR/run_metadata.txt"

set +e
"$CODEX_BIN" exec \
  --cd "$ROOT_DIR" \
  --model "$MODEL" \
  --config "model_reasoning_effort=\"$REASONING\"" \
  --config "approval_policy=\"$APPROVAL_POLICY\"" \
  --sandbox "$SANDBOX_MODE" \
  --json \
  --output-last-message "$OUTPUT_DIR/final_message.md" \
  - < "$RUN_PROMPT" | tee "$OUTPUT_DIR/codex_events.jsonl"
codex_status=${PIPESTATUS[0]}
set -e

{
  printf 'finished_at=%s\n' "$(date --iso-8601=seconds)"
  printf 'codex_exit_status=%s\n' "$codex_status"
} >> "$OUTPUT_DIR/run_metadata.txt"

exit "$codex_status"
