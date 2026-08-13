#!/usr/bin/env bash
set -euo pipefail

# Runtime state machine for codex_worker_reviewer_execution.sh. The launcher
# prepares and submits the initial allocation; this module owns persistent
# worker sessions, review iterations, SLURM yields, and resumptions.

for required_name in \
  SCRIPT_PATH ROOT_DIR RUNTIME_SCRIPT OUTPUT_DIR PLAN_JSON WORKER_TEMPLATE \
  WORKER_SCHEMA REVIEWER_TEMPLATE REVIEW_SCHEMA CODEX_BIN RUNNER_MODE \
  PHASE_COUNT SELECTED_PHASE_COUNT SELECTED_PHASE_IDS_CSV \
  IMPORTED_PHASE_COUNT IMPORTED_PHASE_IDS_CSV; do
  if [[ ! -v "$required_name" ]]; then
    printf 'Runtime environment variable is missing: %s\n' "$required_name" >&2
    exit 2
  fi
done

if [[ ! -x "$CODEX_BIN" ]]; then
  printf 'Codex executable is unavailable: %s\n' "$CODEX_BIN" >&2
  exit 2
fi

ORCHESTRATION_DIR="$OUTPUT_DIR/orchestration"
RUN_STATUS="$OUTPUT_DIR/run_status.json"
CHECKPOINT="$ORCHESTRATION_DIR/worker_checkpoint.json"
GENERATION_FILE="$ORCHESTRATION_DIR/resume_generation.txt"
RESUME_LOCK="$ORCHESTRATION_DIR/resume.lock"
FROZEN_RUNNER="$ORCHESTRATION_DIR/codex_worker_reviewer_execution.sh"
FROZEN_RUNTIME="$ORCHESTRATION_DIR/codex_worker_reviewer_runtime.sh"

ACTIVE_PLAN_JSON="$ORCHESTRATION_DIR/plan.json"
ACTIVE_WORKER_TEMPLATE="$ORCHESTRATION_DIR/worker_template.txt"
ACTIVE_WORKER_SCHEMA="$ORCHESTRATION_DIR/worker_turn.schema.json"
ACTIVE_REVIEWER_TEMPLATE="$ORCHESTRATION_DIR/reviewer_template.txt"
ACTIVE_REVIEW_SCHEMA="$ORCHESTRATION_DIR/reviewer_decision.schema.json"

atomic_jq() {
  local target=$1
  shift
  local target_dir tmp
  target_dir=$(dirname "$target")
  mkdir -p "$target_dir"
  tmp=$(mktemp "$target_dir/.tmp.$(basename "$target").XXXXXX")
  if jq "$@" > "$tmp"; then
    mv "$tmp" "$target"
  else
    rm -f "$tmp"
    return 1
  fi
}

atomic_text() {
  local target=$1 value=$2
  local target_dir tmp
  target_dir=$(dirname "$target")
  mkdir -p "$target_dir"
  tmp=$(mktemp "$target_dir/.tmp.$(basename "$target").XXXXXX")
  printf '%s\n' "$value" > "$tmp"
  mv "$tmp" "$target"
}

initialize_orchestration() {
  if [[ -e "$RUN_STATUS" ]]; then
    printf 'Refusing to initialize over an existing run status: %s\n' \
      "$RUN_STATUS" >&2
    exit 2
  fi

  mkdir -p "$ORCHESTRATION_DIR"
  cp "$PLAN_JSON" "$ACTIVE_PLAN_JSON"
  if [[ "$AUTHORITATIVE_PLAN_KIND" == "plan.md" ]]; then
    cp "$PLAN_MD" "$ORCHESTRATION_DIR/plan.md"
  fi
  cp "$WORKER_TEMPLATE" "$ACTIVE_WORKER_TEMPLATE"
  cp "$WORKER_SCHEMA" "$ACTIVE_WORKER_SCHEMA"
  cp "$REVIEWER_TEMPLATE" "$ACTIVE_REVIEWER_TEMPLATE"
  cp "$REVIEW_SCHEMA" "$ACTIVE_REVIEW_SCHEMA"
  cp "$SCRIPT_PATH" "$FROZEN_RUNNER"
  cp "$RUNTIME_SCRIPT" "$FROZEN_RUNTIME"

  local -a hash_inputs=(
    "$ACTIVE_PLAN_JSON"
    "$ACTIVE_WORKER_TEMPLATE"
    "$ACTIVE_WORKER_SCHEMA"
    "$ACTIVE_REVIEWER_TEMPLATE"
    "$ACTIVE_REVIEW_SCHEMA"
    "$FROZEN_RUNNER"
    "$FROZEN_RUNTIME"
  )
  if [[ "$AUTHORITATIVE_PLAN_KIND" == "plan.md" ]]; then
    hash_inputs=("$ORCHESTRATION_DIR/plan.md" "${hash_inputs[@]}")
  fi
  sha256sum "${hash_inputs[@]}" \
    > "$ORCHESTRATION_DIR/orchestration_hashes.sha256"
  atomic_text "$GENERATION_FILE" 0

  if [[ "$AUTHORITATIVE_PLAN_KIND" == "plan.md" ]]; then
    ACTIVE_PLAN_DOCUMENT="$ORCHESTRATION_DIR/plan.md"
  else
    ACTIVE_PLAN_DOCUMENT="$ACTIVE_PLAN_JSON"
  fi

  {
    printf 'slurm_job_id=%s\n' "$SLURM_JOB_ID"
    printf 'started_at=%s\n' "$(date --iso-8601=seconds)"
    printf 'root_dir=%s\nauthoritative_plan=%s\nplan_json=%s\n' \
      "$ROOT_DIR" "$ACTIVE_PLAN_DOCUMENT" "$ACTIVE_PLAN_JSON"
    printf 'output_dir=%s\nphase_count=%s\n' "$OUTPUT_DIR" "$PHASE_COUNT"
    printf 'descriptive_id=%s\n' "$DESCRIPTIVE_ID"
    printf 'context_bundle=%s\n' "$CONTEXT_BUNDLE"
    printf 'selected_phase_count=%s\nselected_phase_ids=%s\n' \
      "$SELECTED_PHASE_COUNT" "$SELECTED_PHASE_IDS_CSV"
    printf 'imported_phase_count=%s\nimported_phase_ids=%s\n' \
      "$IMPORTED_PHASE_COUNT" "$IMPORTED_PHASE_IDS_CSV"
    [[ -n "$START_PHASE_ID" ]] && printf 'start_phase_id=%s\n' "$START_PHASE_ID"
    printf 'review_policy=%s\nmax_review_loops=%s\nfixed_review_loops=%s\n' \
      "$REVIEW_POLICY" "$MAX_REVIEW_LOOPS" "$FIXED_REVIEW_LOOPS"
    printf 'worker_model=%s\nworker_reasoning=%s\n' \
      "$WORKER_MODEL" "$WORKER_REASONING"
    printf 'reviewer_model=%s\nreviewer_reasoning=%s\n' \
      "$REVIEWER_MODEL" "$REVIEWER_REASONING"
    printf 'time=%s\nmemory=%s\ncpus=%s\nqos=%s\n' \
      "$TIME" "$MEM" "$CPUS" "$QOS"
    printf 'watchdog_interval_minutes=%s\nmax_slurm_wait_hours=%s\n' \
      "$WATCHDOG_INTERVAL_MINUTES" "$MAX_SLURM_WAIT_HOURS"
    "$CODEX_BIN" --version
  } > "$OUTPUT_DIR/run_metadata.txt"

  atomic_jq "$RUN_STATUS" -n \
    --arg status "RUNNING" \
    --arg started_at "$(date --iso-8601=seconds)" \
    --arg selected_csv "$SELECTED_PHASE_IDS_CSV" \
    --arg imported_csv "$IMPORTED_PHASE_IDS_CSV" \
    --argjson phase_count "$PHASE_COUNT" \
    --argjson selected_phase_count "$SELECTED_PHASE_COUNT" \
    --argjson imported_phase_count "$IMPORTED_PHASE_COUNT" \
    '{
      status: $status,
      started_at: $started_at,
      updated_at: $started_at,
      phase_count: $phase_count,
      selected_phase_count: $selected_phase_count,
      selected_phase_ids:
        (if $selected_csv == "" then [] else ($selected_csv | split(",")) end),
      imported_phase_count: $imported_phase_count,
      imported_phase_ids:
        (if $imported_csv == "" then [] else ($imported_csv | split(",")) end),
      completed_phases: $imported_phase_count,
      completed_selected_phases: 0
    }'
}

load_orchestration() {
  local path
  for path in \
    "$RUN_STATUS" "$CHECKPOINT" "$GENERATION_FILE" "$FROZEN_RUNNER" \
    "$FROZEN_RUNTIME" "$ACTIVE_PLAN_JSON" "$ACTIVE_WORKER_TEMPLATE" \
    "$ACTIVE_WORKER_SCHEMA" "$ACTIVE_REVIEWER_TEMPLATE" "$ACTIVE_REVIEW_SCHEMA"; do
    if [[ ! -f "$path" ]]; then
      printf 'Resumption artifact is missing: %s\n' "$path" >&2
      exit 2
    fi
  done
  if [[ "$AUTHORITATIVE_PLAN_KIND" == "plan.md" ]]; then
    ACTIVE_PLAN_DOCUMENT="$ORCHESTRATION_DIR/plan.md"
  else
    ACTIVE_PLAN_DOCUMENT="$ACTIVE_PLAN_JSON"
  fi
}

if [[ "$RUNNER_MODE" == "run" ]]; then
  initialize_orchestration
else
  load_orchestration
fi

# Follow-up jobs use the immutable snapshots created by the initial allocation.
export PLAN_JSON="$ACTIVE_PLAN_JSON"
if [[ "$AUTHORITATIVE_PLAN_KIND" == "plan.md" ]]; then
  export PLAN_MD="$ACTIVE_PLAN_DOCUMENT"
fi
export WORKER_TEMPLATE="$ACTIVE_WORKER_TEMPLATE"
export WORKER_SCHEMA="$ACTIVE_WORKER_SCHEMA"
export REVIEWER_TEMPLATE="$ACTIVE_REVIEWER_TEMPLATE"
export REVIEW_SCHEMA="$ACTIVE_REVIEW_SCHEMA"
export RUNTIME_SCRIPT="$FROZEN_RUNTIME"

declare -a SELECTED_PHASE_IDS=()
IFS=',' read -r -a SELECTED_PHASE_IDS <<< "$SELECTED_PHASE_IDS_CSV"

LOCK_HELD=0
ensure_resume_lock() {
  local wait_seconds=${1:-120}
  if [[ "$LOCK_HELD" == "1" ]]; then
    return 0
  fi
  exec 9> "$RESUME_LOCK"
  if ! flock -w "$wait_seconds" 9; then
    return 1
  fi
  LOCK_HELD=1
}

next_resume_generation() {
  ensure_resume_lock 120
  local generation=0
  if [[ -f "$GENERATION_FILE" ]]; then
    read -r generation < "$GENERATION_FILE"
  fi
  if [[ ! "$generation" =~ ^[0-9]+$ ]]; then
    printf 'Invalid resume generation counter: %s\n' "$generation" >&2
    exit 2
  fi
  generation=$((generation + 1))
  atomic_text "$GENERATION_FILE" "$generation"
  NEXT_RESUME_GENERATION=$generation
}

set_run_running() {
  local phase_id=$1 iteration=$2 detail=${3:-}
  atomic_jq "$RUN_STATUS" \
    --arg status "RUNNING" \
    --arg updated_at "$(date --iso-8601=seconds)" \
    --arg current_phase "$phase_id" \
    --arg detail "$detail" \
    --argjson iteration "$iteration" \
    '
      .status = $status
      | .updated_at = $updated_at
      | .current_phase = $current_phase
      | .current_iteration = $iteration
      | .detail = $detail
      | del(.waiting_for_slurm, .failure)
    ' "$RUN_STATUS"
}

mark_failed() {
  local reason=$1 phase_id=${2:-} iteration=${3:-0} exit_status=${4:-1}
  local finished_at
  finished_at=$(date --iso-8601=seconds)
  if [[ -f "$CHECKPOINT" ]]; then
    atomic_jq "$CHECKPOINT" \
      --arg state "FAILED" \
      --arg reason "$reason" \
      --arg failed_at "$finished_at" \
      '.state = $state | .failure_reason = $reason | .failed_at = $failed_at' \
      "$CHECKPOINT"
  fi
  if [[ -n "$phase_id" ]]; then
    atomic_jq "$OUTPUT_DIR/$phase_id/phase_status.json" -n \
      --arg status "FAILED" \
      --arg phase_id "$phase_id" \
      --arg reason "$reason" \
      --argjson iteration "$iteration" \
      --argjson exit_status "$exit_status" \
      '{
        status: $status,
        phase_id: $phase_id,
        iteration: $iteration,
        reason: $reason,
        exit_status: $exit_status
      }'
  fi
  atomic_jq "$RUN_STATUS" \
    --arg status "FAILED" \
    --arg reason "$reason" \
    --arg phase_id "$phase_id" \
    --arg finished_at "$finished_at" \
    --argjson exit_status "$exit_status" \
    '
      .status = $status
      | .finished_at = $finished_at
      | .updated_at = $finished_at
      | .failure = {
          reason: $reason,
          phase_id: $phase_id,
          exit_status: $exit_status
        }
    ' "$RUN_STATUS"
}

initialize_phase_checkpoint() {
  local phase_index=$1 phase_id=$2 phase_name=$3
  atomic_jq "$CHECKPOINT" -n \
    --arg state "READY_FOR_WORKER" \
    --arg phase_id "$phase_id" \
    --arg phase_name "$phase_name" \
    --arg created_at "$(date --iso-8601=seconds)" \
    --argjson phase_index "$phase_index" \
    '{
      schema_version: 1,
      state: $state,
      phase_index: $phase_index,
      phase_id: $phase_id,
      phase_name: $phase_name,
      iteration: 1,
      worker_turn: 0,
      worker_session_id: null,
      prior_review: null,
      last_worker_result: null,
      resume_generation: 0,
      slurm_jobs: [],
      created_at: $created_at,
      updated_at: $created_at
    }'
}

query_job_json() {
  local job_id=$1
  local squeue_output sacct_output squeue_status sacct_status
  local active=false known=false terminal=false all_sacct_terminal=true
  local row_id state exit_code reason normalized_state

  set +e
  squeue_output=$(squeue -h -j "$job_id" -o '%i|%T|%r' 2>&1)
  squeue_status=$?
  sacct_output=$(sacct -n -X -j "$job_id" \
    --format=JobIDRaw,State,ExitCode,Reason -P 2>&1)
  sacct_status=$?
  set -e

  if [[ "$squeue_status" -eq 0 && -n "$squeue_output" ]]; then
    active=true
    known=true
  fi

  if [[ "$sacct_status" -eq 0 && -n "$sacct_output" ]]; then
    while IFS='|' read -r row_id state exit_code reason; do
      [[ -n "$row_id" && -n "$state" ]] || continue
      known=true
      normalized_state=${state%% *}
      normalized_state=${normalized_state%%+*}
      case "$normalized_state" in
        COMPLETED|FAILED|CANCELLED|TIMEOUT|OUT_OF_MEMORY|NODE_FAIL|\
        PREEMPTED|BOOT_FAIL|DEADLINE|REVOKED|SPECIAL_EXIT)
          ;;
        *)
          all_sacct_terminal=false
          ;;
      esac
    done <<< "$sacct_output"
  else
    all_sacct_terminal=false
  fi

  if [[ "$active" == "false" \
      && "$known" == "true" \
      && "$all_sacct_terminal" == "true" ]]; then
    terminal=true
  fi

  jq -n \
    --arg job_id "$job_id" \
    --argjson known "$known" \
    --argjson active "$active" \
    --argjson terminal "$terminal" \
    --argjson squeue_exit_status "$squeue_status" \
    --argjson sacct_exit_status "$sacct_status" \
    --arg squeue "$squeue_output" \
    --arg sacct "$sacct_output" \
    '{
      job_id: $job_id,
      known: $known,
      active: $active,
      terminal: $terminal,
      squeue_exit_status: $squeue_exit_status,
      sacct_exit_status: $sacct_exit_status,
      squeue: $squeue,
      sacct: $sacct
    }'
}

append_path_check() {
  local report=$1 job_id=$2 category=$3 supplied_path=$4 phase_work_dir=$5
  local resolved_path exists=false kind="missing" size_bytes=0 tmp
  if [[ "$supplied_path" == /* ]]; then
    resolved_path=$supplied_path
  else
    resolved_path="$phase_work_dir/$supplied_path"
  fi
  if [[ -e "$resolved_path" ]]; then
    exists=true
    if [[ -f "$resolved_path" ]]; then
      kind="file"
      size_bytes=$(stat -c '%s' "$resolved_path" 2>/dev/null || printf '0')
    elif [[ -d "$resolved_path" ]]; then
      kind="directory"
    else
      kind="other"
    fi
  fi
  tmp=$(mktemp "$(dirname "$report")/.tmp.scheduler-path.XXXXXX")
  jq \
    --arg job_id "$job_id" \
    --arg category "$category" \
    --arg supplied_path "$supplied_path" \
    --arg resolved_path "$resolved_path" \
    --arg kind "$kind" \
    --argjson exists "$exists" \
    --argjson size_bytes "$size_bytes" \
    '
      .path_checks += [{
        job_id: $job_id,
        category: $category,
        supplied_path: $supplied_path,
        resolved_path: $resolved_path,
        exists: $exists,
        kind: $kind,
        size_bytes: $size_bytes
      }]
    ' "$report" > "$tmp"
  mv "$tmp" "$report"
}

build_scheduler_report() {
  local report=$1 phase_work_dir=$2 trigger=$3
  local job_id purpose job_json tmp category supplied_path
  atomic_jq "$report" -n \
    --arg generated_at "$(date --iso-8601=seconds)" \
    --arg trigger "$trigger" \
    --argjson generation "$RESUME_GENERATION" \
    '{
      generated_at: $generated_at,
      resume_generation: $generation,
      trigger: $trigger,
      jobs: [],
      path_checks: []
    }'

  while IFS=$'\t' read -r job_id purpose; do
    [[ -n "$job_id" ]] || continue
    job_json=$(query_job_json "$job_id")
    tmp=$(mktemp "$(dirname "$report")/.tmp.scheduler-job.XXXXXX")
    jq \
      --arg purpose "$purpose" \
      --argjson job "$job_json" \
      '.jobs += [($job + {purpose: $purpose})]' \
      "$report" > "$tmp"
    mv "$tmp" "$report"
  done < <(jq -r '.slurm_jobs[] | [.job_id, .purpose] | @tsv' "$CHECKPOINT")

  for category in log_paths expected_outputs; do
    while IFS=$'\t' read -r job_id supplied_path; do
      [[ -n "$job_id" && -n "$supplied_path" ]] || continue
      append_path_check \
        "$report" "$job_id" "$category" "$supplied_path" "$phase_work_dir"
    done < <(
      jq -r --arg category "$category" \
        '.slurm_jobs[]
         | .job_id as $job_id
         | .[$category][]
         | [$job_id, .]
         | @tsv' \
        "$CHECKPOINT"
    )
  done
}

job_active() {
  local job_id=$1 output status
  [[ -n "$job_id" ]] || return 1
  set +e
  output=$(squeue -h -j "$job_id" -o '%T|%r' 2>/dev/null)
  status=$?
  set -e
  [[ "$status" -eq 0 && -n "$output" ]]
}

continuation_failure_reason() {
  local continuation_id=$1 output status state reason
  if [[ -z "$continuation_id" ]]; then
    printf 'continuation_submission_missing'
    return 0
  fi
  set +e
  output=$(squeue -h -j "$continuation_id" -o '%T|%r' 2>/dev/null)
  status=$?
  set -e
  if [[ "$status" -eq 0 && -n "$output" ]]; then
    IFS='|' read -r state reason <<< "${output%%$'\n'*}"
    if [[ "$reason" == "DependencyNeverSatisfied" ]]; then
      printf 'dependency_never_satisfied'
      return 0
    fi
    return 1
  fi

  set +e
  output=$(sacct -n -X -j "$continuation_id" \
    --format=State,Reason -P 2>/dev/null)
  status=$?
  set -e
  if [[ "$status" -eq 0 && -n "$output" ]]; then
    IFS='|' read -r state reason <<< "${output%%$'\n'*}"
    state=${state%% *}
    state=${state%%+*}
    case "$state" in
      COMPLETED|FAILED|CANCELLED|TIMEOUT|OUT_OF_MEMORY|NODE_FAIL|\
      PREEMPTED|BOOT_FAIL|DEADLINE|REVOKED|SPECIAL_EXIT)
        printf 'continuation_terminal_%s' "${state,,}"
        return 0
        ;;
    esac
  fi
  return 1
}

append_extra_sbatch_args() {
  local -n destination=$1
  if [[ -n "$EXTRA_SBATCH_ARGS" ]]; then
    # shellcheck disable=SC2206
    local extra_args=( $EXTRA_SBATCH_ARGS )
    destination+=("${extra_args[@]}")
  fi
}

submit_full_continuation() {
  local generation=$1 trigger=$2 dependency=${3:-}
  local -a args=(
    --parsable
    --job-name="${JOB_NAME}_cont"
    --time="$TIME"
    --nodes=1
    --ntasks=1
    --cpus-per-task="$CPUS"
    --mem="$MEM"
    --qos="$QOS"
    --chdir="$ROOT_DIR"
    --output="$OUTPUT_DIR/slurm-continuation-%j.out"
    --error="$OUTPUT_DIR/slurm-continuation-%j.err"
    --export="ALL,RUNNER_MODE=continue,RESUME_GENERATION=$generation,RESUME_TRIGGER=$trigger,RUNTIME_SCRIPT=$FROZEN_RUNTIME"
  )
  [[ -n "$PARTITION" ]] && args+=(--partition="$PARTITION")
  [[ -n "$ACCOUNT" ]] && args+=(--account="$ACCOUNT")
  if [[ -n "$dependency" ]]; then
    args+=(--dependency="$dependency" --kill-on-invalid-dep=yes)
  fi
  append_extra_sbatch_args args

  local output status
  set +e
  output=$(sbatch "${args[@]}" "$FROZEN_RUNNER" 2>&1)
  status=$?
  set -e
  if [[ "$status" -ne 0 ]]; then
    printf '%s\n' "$output" >&2
    return "$status"
  fi
  output=${output%%;*}
  if [[ ! "$output" =~ ^[0-9]+$ ]]; then
    printf 'Unexpected continuation sbatch response: %s\n' "$output" >&2
    return 2
  fi
  printf '%s' "$output"
}

submit_watchdog() {
  local generation=$1
  local -a args=(
    --parsable
    --job-name="$WATCHDOG_JOB_NAME"
    --time="$WATCHDOG_TIME"
    --nodes=1
    --ntasks=1
    --cpus-per-task=1
    --mem="$WATCHDOG_MEM"
    --qos="$WATCHDOG_QOS"
    --chdir="$ROOT_DIR"
    --begin="now+${WATCHDOG_INTERVAL_MINUTES}minutes"
    --output="$OUTPUT_DIR/slurm-watchdog-%j.out"
    --error="$OUTPUT_DIR/slurm-watchdog-%j.err"
    --export="ALL,RUNNER_MODE=watchdog,RESUME_GENERATION=$generation,RESUME_TRIGGER=watchdog,RUNTIME_SCRIPT=$FROZEN_RUNTIME"
  )
  [[ -n "$PARTITION" ]] && args+=(--partition="$PARTITION")
  [[ -n "$ACCOUNT" ]] && args+=(--account="$ACCOUNT")

  local output status
  set +e
  output=$(sbatch "${args[@]}" "$FROZEN_RUNNER" 2>&1)
  status=$?
  set -e
  if [[ "$status" -ne 0 ]]; then
    printf '%s\n' "$output" >&2
    return "$status"
  fi
  output=${output%%;*}
  if [[ ! "$output" =~ ^[0-9]+$ ]]; then
    printf 'Unexpected watchdog sbatch response: %s\n' "$output" >&2
    return 2
  fi
  printf '%s' "$output"
}

update_watchdog_id() {
  local generation=$1 watchdog_id=$2
  atomic_jq "$CHECKPOINT" \
    --argjson generation "$generation" \
    --arg watchdog_id "$watchdog_id" \
    --arg updated_at "$(date --iso-8601=seconds)" \
    '
      if .resume_generation == $generation
         and (.state == "WAITING_FOR_SLURM" or .state == "RESUMING_WORKER")
      then
        .watchdog_job_id = $watchdog_id
        | .updated_at = $updated_at
      else
        .
      end
    ' "$CHECKPOINT"
}

run_watchdog() {
  if [[ ! "$RESUME_GENERATION" =~ ^[1-9][0-9]*$ ]]; then
    printf 'Watchdog lacks a valid RESUME_GENERATION.\n' >&2
    exit 2
  fi

  if ! ensure_resume_lock 5; then
    local retry_id
    retry_id=$(submit_watchdog "$RESUME_GENERATION")
    printf 'Resume lock busy; scheduled watchdog retry %s for generation %s\n' \
      "$retry_id" "$RESUME_GENERATION"
    exit 0
  fi

  local current_generation state phase_id iteration phase_work_dir
  local active_resume_job continuation_job waiting_since now elapsed max_wait
  local report all_terminal failure_reason recovery_trigger watchdog_id recovery_id
  current_generation=$(jq -r '.resume_generation' "$CHECKPOINT")
  state=$(jq -r '.state' "$CHECKPOINT")
  if [[ "$current_generation" != "$RESUME_GENERATION" \
      || ( "$state" != "WAITING_FOR_SLURM" \
           && "$state" != "RESUMING_WORKER" ) ]]; then
    printf 'Watchdog generation %s is stale; checkpoint is generation %s state %s\n' \
      "$RESUME_GENERATION" "$current_generation" "$state"
    exit 0
  fi

  phase_id=$(jq -r '.phase_id' "$CHECKPOINT")
  iteration=$(jq -r '.iteration' "$CHECKPOINT")
  phase_work_dir="$OUTPUT_DIR/$phase_id/work"
  report=$(printf '%s/%s/iteration_%02d/scheduler_generation_%04d.json' \
    "$OUTPUT_DIR" "$phase_id" "$iteration" "$RESUME_GENERATION")
  build_scheduler_report "$report" "$phase_work_dir" "watchdog_reconciliation"

  active_resume_job=$(jq -r '.active_resume_job_id // empty' "$CHECKPOINT")
  if [[ "$state" == "RESUMING_WORKER" ]] && job_active "$active_resume_job"; then
    watchdog_id=$(submit_watchdog "$RESUME_GENERATION")
    update_watchdog_id "$RESUME_GENERATION" "$watchdog_id"
    printf 'Worker resumption job %s remains active; watchdog retry is %s\n' \
      "$active_resume_job" "$watchdog_id"
    exit 0
  fi

  all_terminal=$(jq -r \
    '(.jobs | length) > 0 and all(.jobs[]; .terminal == true)' "$report")
  continuation_job=$(jq -r '.continuation_job_id // empty' "$CHECKPOINT")
  failure_reason=""
  if failure_reason=$(continuation_failure_reason "$continuation_job"); then
    :
  else
    failure_reason=""
  fi
  waiting_since=$(jq -r '.waiting_since_epoch // 0' "$CHECKPOINT")
  now=$(date +%s)
  elapsed=$((now - waiting_since))
  max_wait=$((MAX_SLURM_WAIT_HOURS * 3600))

  recovery_trigger=""
  if [[ "$state" == "RESUMING_WORKER" ]]; then
    recovery_trigger="interrupted_worker_resumption"
  elif [[ "$all_terminal" == "true" ]]; then
    recovery_trigger="watchdog_all_jobs_terminal"
  elif [[ -n "$failure_reason" ]]; then
    recovery_trigger="watchdog_${failure_reason}"
  elif [[ "$elapsed" -ge "$max_wait" ]]; then
    recovery_trigger="watchdog_wait_timeout"
  fi

  if [[ -z "$recovery_trigger" ]]; then
    watchdog_id=$(submit_watchdog "$RESUME_GENERATION")
    update_watchdog_id "$RESUME_GENERATION" "$watchdog_id"
    printf 'SLURM jobs remain nonterminal; watchdog retry is %s\n' "$watchdog_id"
    exit 0
  fi

  recovery_id=$(submit_full_continuation \
    "$RESUME_GENERATION" "$recovery_trigger")
  atomic_jq "$CHECKPOINT" \
    --argjson generation "$RESUME_GENERATION" \
    --arg continuation_job_id "$recovery_id" \
    --arg trigger "$recovery_trigger" \
    --arg scheduler_report "$report" \
    --arg updated_at "$(date --iso-8601=seconds)" \
    '
      if .resume_generation == $generation
      then
        .state = "WAITING_FOR_SLURM"
        | .continuation_job_id = $continuation_job_id
        | .continuation_kind = "watchdog_recovery"
        | .resume_trigger = $trigger
        | .latest_scheduler_report = $scheduler_report
        | .active_resume_job_id = null
        | .updated_at = $updated_at
      else
        .
      end
    ' "$CHECKPOINT"
  printf 'Watchdog scheduled recovery continuation %s (%s)\n' \
    "$recovery_id" "$recovery_trigger"
  exit 0
}

if [[ "$RUNNER_MODE" == "watchdog" ]]; then
  run_watchdog
fi

RESUME_READY=0
SCHEDULER_REPORT=""
if [[ "$RUNNER_MODE" == "continue" ]]; then
  if [[ ! "$RESUME_GENERATION" =~ ^[1-9][0-9]*$ ]]; then
    printf 'Continuation lacks a valid RESUME_GENERATION.\n' >&2
    exit 2
  fi
  if ! ensure_resume_lock 120; then
    printf 'Could not acquire the worker resume lock.\n' >&2
    exit 11
  fi

  current_generation=$(jq -r '.resume_generation' "$CHECKPOINT")
  checkpoint_state=$(jq -r '.state' "$CHECKPOINT")
  if [[ "$current_generation" != "$RESUME_GENERATION" \
      || ( "$checkpoint_state" != "WAITING_FOR_SLURM" \
           && "$checkpoint_state" != "RESUMING_WORKER" ) ]]; then
    printf 'Continuation generation %s is stale; checkpoint is generation %s state %s\n' \
      "$RESUME_GENERATION" "$current_generation" "$checkpoint_state"
    exit 0
  fi

  resume_phase_id=$(jq -r '.phase_id' "$CHECKPOINT")
  resume_iteration=$(jq -r '.iteration' "$CHECKPOINT")
  resume_phase_work_dir="$OUTPUT_DIR/$resume_phase_id/work"
  SCHEDULER_REPORT=$(printf '%s/%s/iteration_%02d/scheduler_generation_%04d.json' \
    "$OUTPUT_DIR" "$resume_phase_id" "$resume_iteration" "$RESUME_GENERATION")
  RESUME_TRIGGER=${RESUME_TRIGGER:-dependency_afterany}
  build_scheduler_report \
    "$SCHEDULER_REPORT" "$resume_phase_work_dir" "$RESUME_TRIGGER"
  atomic_jq "$CHECKPOINT" \
    --arg state "RESUMING_WORKER" \
    --arg trigger "$RESUME_TRIGGER" \
    --arg scheduler_report "$SCHEDULER_REPORT" \
    --arg active_resume_job_id "$SLURM_JOB_ID" \
    --arg updated_at "$(date --iso-8601=seconds)" \
    '
      .state = $state
      | .resume_trigger = $trigger
      | .latest_scheduler_report = $scheduler_report
      | .active_resume_job_id = $active_resume_job_id
      | .updated_at = $updated_at
    ' "$CHECKPOINT"
  set_run_running "$resume_phase_id" "$resume_iteration" \
    "resuming persistent worker: $RESUME_TRIGGER"
  RESUME_READY=1
fi

build_initial_worker_prompt() {
  local target=$1 phase_id=$2 phase_name=$3 iteration=$4
  local phase_spec=$5 phase_work_dir=$6 prior_review=$7
  {
    cat "$ACTIVE_WORKER_TEMPLATE"
    printf '\n\nRUNTIME CONTEXT\n'
    printf 'ROOT_DIR: %s\nRUN_OUTPUT_DIR: %s\n' "$ROOT_DIR" "$OUTPUT_DIR"
    printf 'AUTHORITATIVE_PLAN: %s\nPLAN_JSON: %s\n' \
      "$ACTIVE_PLAN_DOCUMENT" "$ACTIVE_PLAN_JSON"
    printf 'PHASE_SPEC_JSON: %s\nPHASE_WORK_DIR: %s\n' \
      "$phase_spec" "$phase_work_dir"
    printf 'PHASE_ID: %s\nPHASE_NAME: %s\nITERATION: %s\n' \
      "$phase_id" "$phase_name" "$iteration"
    printf 'SELECTED_PHASE_IDS: %s\nIMPORTED_ACCEPTED_PHASE_IDS: %s\n' \
      "$SELECTED_PHASE_IDS_CSV" "$IMPORTED_PHASE_IDS_CSV"
    printf 'REVIEW_POLICY: %s\nPRIOR_REVIEW_JSON: %s\n' \
      "$REVIEW_POLICY" "$prior_review"
  } > "$target"
}

build_review_resume_prompt() {
  local target=$1 phase_id=$2 iteration=$3 prior_review=$4 phase_work_dir=$5
  {
    printf 'Continue as the same worker for phase %s.\n' "$phase_id"
    printf 'This is review iteration %s. The independent review is at: %s\n' \
      "$iteration" "$prior_review"
    printf 'The phase work directory remains: %s\n' "$phase_work_dir"
    printf '%s\n' \
      'Read the review itself, make every required revision, rerun affected analyses, and inspect the revised artifacts.'
    printf '%s\n' \
      'Use SLURM and WAIT_FOR_SLURM under the original worker contract if more long compute is needed.'
    printf '%s\n' \
      'Otherwise return COMPLETE only when this iteration is ready for another independent review.'
  } > "$target"
}

build_slurm_resume_prompt() {
  local target=$1 phase_id=$2 iteration=$3 phase_work_dir=$4
  {
    printf 'Resume your existing work as the same worker for phase %s, iteration %s.\n' \
      "$phase_id" "$iteration"
    printf 'The runner yielded after your SLURM submission and has now reconciled the scheduler.\n'
    printf 'SCHEDULER_REPORT_JSON: %s\n' "$SCHEDULER_REPORT"
    printf 'WORKER_CHECKPOINT_JSON: %s\n' "$CHECKPOINT"
    printf 'PHASE_WORK_DIR: %s\nRESUME_TRIGGER: %s\n' \
      "$phase_work_dir" "$RESUME_TRIGGER"
    printf '%s\n' \
      'Inspect the scheduler report, relevant logs, and outputs. Do not infer success merely from a terminal job state.'
    printf '%s\n' \
      'If jobs failed, were cancelled, never became runnable, or outputs are incomplete, diagnose and repair or resubmit as scientifically appropriate.'
    printf '%s\n' \
      'Return WAIT_FOR_SLURM again if new compute must finish; otherwise continue the phase and return COMPLETE only when ready for review.'
  } > "$target"
}

run_worker_turn() {
  local phase_id=$1 phase_name=$2 iteration=$3 phase_spec=$4
  local phase_work_dir=$5 prior_review=$6 prompt_kind=$7
  local worker_session worker_turn iteration_dir prefix worker_prompt
  local worker_events worker_stderr worker_result worker_status observed_session

  worker_session=$(jq -r '.worker_session_id // empty' "$CHECKPOINT")
  worker_turn=$(( $(jq -r '.worker_turn' "$CHECKPOINT") + 1 ))
  iteration_dir=$(printf '%s/%s/iteration_%02d' \
    "$OUTPUT_DIR" "$phase_id" "$iteration")
  mkdir -p "$iteration_dir"
  prefix=$(printf '%s/worker_turn_%03d' "$iteration_dir" "$worker_turn")
  worker_prompt="${prefix}_prompt.txt"
  worker_events="${prefix}_events.jsonl"
  worker_stderr="${prefix}_stderr.log"
  worker_result="${prefix}_result.json"

  case "$prompt_kind" in
    initial)
      build_initial_worker_prompt \
        "$worker_prompt" "$phase_id" "$phase_name" "$iteration" \
        "$phase_spec" "$phase_work_dir" "$prior_review"
      ;;
    review)
      build_review_resume_prompt \
        "$worker_prompt" "$phase_id" "$iteration" "$prior_review" "$phase_work_dir"
      ;;
    slurm)
      build_slurm_resume_prompt \
        "$worker_prompt" "$phase_id" "$iteration" "$phase_work_dir"
      ;;
    *)
      printf 'Unknown worker prompt kind: %s\n' "$prompt_kind" >&2
      return 2
      ;;
  esac

  atomic_jq "$CHECKPOINT" \
    --arg state "WORKER_RUNNING" \
    --arg prompt_kind "$prompt_kind" \
    --arg worker_prompt "$worker_prompt" \
    --arg active_job_id "$SLURM_JOB_ID" \
    --arg updated_at "$(date --iso-8601=seconds)" \
    --argjson worker_turn "$worker_turn" \
    '
      .state = $state
      | .worker_turn = $worker_turn
      | .active_worker_prompt_kind = $prompt_kind
      | .active_worker_prompt = $worker_prompt
      | .active_runner_job_id = $active_job_id
      | .updated_at = $updated_at
    ' "$CHECKPOINT"

  printf '  Worker iteration %s, persistent turn %s (%s)\n' \
    "$iteration" "$worker_turn" "$prompt_kind" >&2
  set +e
  if [[ -z "$worker_session" ]]; then
    "$CODEX_BIN" exec \
      --cd "$ROOT_DIR" \
      --model "$WORKER_MODEL" \
      --config "model_reasoning_effort=\"$WORKER_REASONING\"" \
      --config "approval_policy=\"$APPROVAL_POLICY\"" \
      --sandbox "$WORKER_SANDBOX" \
      --color never \
      --json \
      --output-schema "$ACTIVE_WORKER_SCHEMA" \
      --output-last-message "$worker_result" \
      - < "$worker_prompt" > "$worker_events" 2> "$worker_stderr"
    worker_status=$?
  else
    (
      cd "$ROOT_DIR"
      "$CODEX_BIN" exec resume \
        --model "$WORKER_MODEL" \
        --config "model_reasoning_effort=\"$WORKER_REASONING\"" \
        --config "approval_policy=\"$APPROVAL_POLICY\"" \
        --json \
        --output-schema "$ACTIVE_WORKER_SCHEMA" \
        --output-last-message "$worker_result" \
        "$worker_session" \
        - < "$worker_prompt" > "$worker_events" 2> "$worker_stderr"
    )
    worker_status=$?
  fi
  set -e

  observed_session=$(jq -r \
    'select(.type == "thread.started") | .thread_id' \
    "$worker_events" 2>/dev/null | sed -n '1p')
  if [[ -z "$worker_session" ]]; then
    worker_session=$observed_session
  elif [[ -n "$observed_session" && "$observed_session" != "$worker_session" ]]; then
    printf 'Resumed worker returned a different session ID: %s != %s\n' \
      "$observed_session" "$worker_session" >&2
    return 2
  fi

  if [[ "$worker_status" -ne 0 ]]; then
    printf 'Worker Codex call failed (status=%s, session=%s).\n' \
      "$worker_status" "${worker_session:-missing}" >&2
    return "$worker_status"
  fi
  if [[ -z "$worker_session" ]]; then
    printf 'Worker Codex call did not expose a persistent session ID.\n' >&2
    return 15
  fi
  if ! jq -e \
    --arg phase_id "$phase_id" \
    --argjson iteration "$iteration" \
    '
      .phase_id == $phase_id
      and .iteration == $iteration
      and (
        (.action == "COMPLETE" and (.slurm_jobs | length) == 0)
        or
        (
          .action == "WAIT_FOR_SLURM"
          and (.slurm_jobs | length) > 0
          and ([.slurm_jobs[].job_id] | length == (unique | length))
          and all(
            .slurm_jobs[];
            (.log_paths | length) == (.log_paths | unique | length)
            and
            (.expected_outputs | length) ==
              (.expected_outputs | unique | length)
          )
        )
      )
    ' "$worker_result" >/dev/null; then
    printf 'Worker result is invalid for phase %s iteration %s: %s\n' \
      "$phase_id" "$iteration" "$worker_result" >&2
    return 13
  fi

  atomic_jq "$OUTPUT_DIR/$phase_id/worker_session.json" -n \
    --arg phase_id "$phase_id" \
    --arg worker_session_id "$worker_session" \
    --arg updated_at "$(date --iso-8601=seconds)" \
    --argjson worker_turn "$worker_turn" \
    '{
      phase_id: $phase_id,
      worker_session_id: $worker_session_id,
      worker_turns_completed: $worker_turn,
      updated_at: $updated_at
    }'
  atomic_jq "$CHECKPOINT" \
    --arg state "WORKER_COMPLETE" \
    --arg worker_session_id "$worker_session" \
    --arg worker_result "$worker_result" \
    --arg worker_events "$worker_events" \
    --arg updated_at "$(date --iso-8601=seconds)" \
    '
      .state = $state
      | .worker_session_id = $worker_session_id
      | .last_worker_result = $worker_result
      | .last_worker_events = $worker_events
      | .active_resume_job_id = null
      | .updated_at = $updated_at
    ' "$CHECKPOINT"
  printf '%s' "$worker_result"
}

schedule_worker_wait() {
  local phase_id=$1 iteration=$2 worker_result=$3
  local generation dependency="" job_id continuation_id watchdog_id
  local waiting_at waiting_epoch
  next_resume_generation
  generation=$NEXT_RESUME_GENERATION
  while IFS= read -r job_id; do
    if [[ -z "$dependency" ]]; then
      dependency="afterany:$job_id"
    else
      dependency+=":$job_id"
    fi
  done < <(jq -r '.slurm_jobs[].job_id' "$worker_result")

  waiting_at=$(date --iso-8601=seconds)
  waiting_epoch=$(date +%s)
  atomic_jq "$CHECKPOINT" \
    --arg state "WAITING_FOR_SLURM" \
    --arg worker_result "$worker_result" \
    --arg waiting_at "$waiting_at" \
    --argjson waiting_epoch "$waiting_epoch" \
    --argjson generation "$generation" \
    --slurpfile result "$worker_result" \
    '
      .state = $state
      | .resume_generation = $generation
      | .slurm_jobs = $result[0].slurm_jobs
      | .last_worker_result = $worker_result
      | .waiting_since = $waiting_at
      | .waiting_since_epoch = $waiting_epoch
      | .continuation_job_id = null
      | .continuation_kind = "afterany"
      | .watchdog_job_id = null
      | .active_resume_job_id = null
      | .latest_scheduler_report = null
      | .updated_at = $waiting_at
    ' "$CHECKPOINT"

  continuation_id=""
  if continuation_id=$(submit_full_continuation \
      "$generation" "dependency_afterany" "$dependency"); then
    :
  else
    continuation_id=""
  fi
  if ! watchdog_id=$(submit_watchdog "$generation"); then
    mark_failed \
      "watchdog_submission_failed" "$phase_id" "$iteration" 14
    return 14
  fi

  atomic_jq "$CHECKPOINT" \
    --argjson generation "$generation" \
    --arg continuation_job_id "$continuation_id" \
    --arg watchdog_job_id "$watchdog_id" \
    --arg updated_at "$(date --iso-8601=seconds)" \
    '
      if .resume_generation == $generation
         and .state == "WAITING_FOR_SLURM"
      then
        .continuation_job_id =
          (if $continuation_job_id == "" then null else $continuation_job_id end)
        | .watchdog_job_id = $watchdog_job_id
        | .updated_at = $updated_at
      else
        .
      end
    ' "$CHECKPOINT"
  atomic_jq "$RUN_STATUS" \
    --arg status "WAITING_FOR_SLURM" \
    --arg updated_at "$(date --iso-8601=seconds)" \
    --arg phase_id "$phase_id" \
    --arg worker_session_id "$(jq -r '.worker_session_id' "$CHECKPOINT")" \
    --arg continuation_job_id "$continuation_id" \
    --arg watchdog_job_id "$watchdog_id" \
    --argjson iteration "$iteration" \
    --argjson generation "$generation" \
    --slurpfile result "$worker_result" \
    '
      .status = $status
      | .updated_at = $updated_at
      | .current_phase = $phase_id
      | .current_iteration = $iteration
      | .waiting_for_slurm = {
          resume_generation: $generation,
          worker_session_id: $worker_session_id,
          jobs: $result[0].slurm_jobs,
          continuation_job_id:
            (if $continuation_job_id == "" then null else $continuation_job_id end),
          watchdog_job_id: $watchdog_job_id
        }
    ' "$RUN_STATUS"
  printf '  Worker yielded. Continuation=%s watchdog=%s generation=%s\n' \
    "${continuation_id:-watchdog-recovery}" "$watchdog_id" "$generation"
}

run_reviewer() {
  local phase_id=$1 phase_name=$2 iteration=$3 phase_spec=$4
  local phase_work_dir=$5 prior_review=$6 worker_result=$7
  local iteration_dir reviewer_prompt review_json review_valid review_try
  local reviewer_events reviewer_stderr reviewer_status
  iteration_dir=$(printf '%s/%s/iteration_%02d' \
    "$OUTPUT_DIR" "$phase_id" "$iteration")
  reviewer_prompt="$iteration_dir/reviewer_prompt.txt"
  review_json="$iteration_dir/review.json"
  {
    cat "$ACTIVE_REVIEWER_TEMPLATE"
    printf '\n\nRUNTIME CONTEXT\n'
    printf 'ROOT_DIR: %s\nRUN_OUTPUT_DIR: %s\n' "$ROOT_DIR" "$OUTPUT_DIR"
    printf 'AUTHORITATIVE_PLAN: %s\nPLAN_JSON: %s\n' \
      "$ACTIVE_PLAN_DOCUMENT" "$ACTIVE_PLAN_JSON"
    printf 'PHASE_SPEC_JSON: %s\nPHASE_WORK_DIR: %s\n' \
      "$phase_spec" "$phase_work_dir"
    printf 'WORKER_FINAL_RESULT: %s\nWORKER_TURN_DIRECTORY: %s\n' \
      "$worker_result" "$iteration_dir"
    printf 'WORKER_SESSION_METADATA: %s\n' \
      "$OUTPUT_DIR/$phase_id/worker_session.json"
    printf 'PHASE_ID: %s\nPHASE_NAME: %s\nITERATION: %s\n' \
      "$phase_id" "$phase_name" "$iteration"
    printf 'SELECTED_PHASE_IDS: %s\nIMPORTED_ACCEPTED_PHASE_IDS: %s\n' \
      "$SELECTED_PHASE_IDS_CSV" "$IMPORTED_PHASE_IDS_CSV"
    printf 'REVIEW_POLICY: %s\nPRIOR_REVIEW_JSON: %s\n' \
      "$REVIEW_POLICY" "$prior_review"
  } > "$reviewer_prompt"

  printf '  Reviewer iteration %s\n' "$iteration" >&2
  review_valid=0
  for ((review_try = 1; review_try <= REVIEWER_RETRIES; review_try++)); do
    reviewer_events=$(printf '%s/reviewer_try_%02d_events.jsonl' \
      "$iteration_dir" "$review_try")
    reviewer_stderr=$(printf '%s/reviewer_try_%02d_stderr.log' \
      "$iteration_dir" "$review_try")
    set +e
    "$CODEX_BIN" exec \
      --ephemeral \
      --cd "$ROOT_DIR" \
      --model "$REVIEWER_MODEL" \
      --config "model_reasoning_effort=\"$REVIEWER_REASONING\"" \
      --config "approval_policy=\"$APPROVAL_POLICY\"" \
      --sandbox "$REVIEWER_SANDBOX" \
      --color never \
      --json \
      --output-schema "$ACTIVE_REVIEW_SCHEMA" \
      --output-last-message "$review_json" \
      - < "$reviewer_prompt" > "$reviewer_events" 2> "$reviewer_stderr"
    reviewer_status=$?
    set -e
    if [[ "$reviewer_status" -ne 0 ]]; then
      continue
    fi
    if jq -e \
      --arg phase_id "$phase_id" \
      --argjson iteration "$iteration" \
      '
        .phase_id == $phase_id
        and .iteration == $iteration
        and (
          (
            .decision == "PASS"
            and (.blocking_issues | length) == 0
            and (.required_revisions | length) == 0
          )
          or
          (
            .decision == "FAIL"
            and (.required_revisions | length) > 0
          )
        )
      ' "$review_json" >/dev/null; then
      review_valid=1
      break
    fi
  done
  if [[ "$review_valid" != "1" ]]; then
    return 12
  fi
  printf '%s' "$review_json"
}

completed_phases=$(jq -r '.completed_phases' "$RUN_STATUS")
completed_selected_phases=$(jq -r '.completed_selected_phases' "$RUN_STATUS")

for phase_id in "${SELECTED_PHASE_IDS[@]}"; do
  phase_index=$(jq -r \
    --arg phase_id "$phase_id" \
    '.phases | map(.id) | index($phase_id)' \
    "$ACTIVE_PLAN_JSON")
  if [[ "$phase_index" == "null" ]]; then
    mark_failed "selected_phase_missing_from_frozen_plan" "$phase_id" 0 2
    exit 2
  fi
  phase_name=$(jq -r ".phases[$phase_index].name" "$ACTIVE_PLAN_JSON")
  phase_dir="$OUTPUT_DIR/$phase_id"
  phase_work_dir="$phase_dir/work"
  phase_spec="$phase_dir/phase_spec.json"

  if [[ -f "$phase_dir/phase_status.json" ]] \
      && jq -e '.status == "PASS"' "$phase_dir/phase_status.json" >/dev/null; then
    continue
  fi

  mkdir -p "$phase_work_dir"
  if [[ ! -f "$phase_spec" ]]; then
    atomic_jq "$phase_spec" ".phases[$phase_index]" "$ACTIVE_PLAN_JSON"
  fi

  if [[ ! -f "$CHECKPOINT" \
      || "$(jq -r '.phase_id' "$CHECKPOINT")" != "$phase_id" ]]; then
    if [[ "$RUNNER_MODE" != "run" ]]; then
      mark_failed "resume_checkpoint_phase_mismatch" "$phase_id" 0 2
      exit 2
    fi
    initialize_phase_checkpoint \
      "$phase_index" "$phase_id" "$phase_name"
  fi

  if [[ "$REVIEW_POLICY" == "fixed" ]]; then
    loop_limit=$FIXED_REVIEW_LOOPS
  else
    loop_limit=$MAX_REVIEW_LOOPS
  fi
  iteration=$(jq -r '.iteration' "$CHECKPOINT")
  prior_review=$(jq -r '.prior_review // "NONE"' "$CHECKPOINT")
  phase_passed=0
  final_decision=$(jq -r '.final_decision // "FAIL"' "$CHECKPOINT")
  final_review=$(jq -r '.final_review // empty' "$CHECKPOINT")
  iterations_completed=0
  printf 'Starting/resuming phase %s (%s), iteration=%s, review loops=%s\n' \
    "$phase_id" "$phase_name" "$iteration" "$loop_limit"

  for ((; iteration <= loop_limit; iteration++)); do
    iterations_completed=$iteration
    set_run_running "$phase_id" "$iteration" "worker turn"
    worker_session=$(jq -r '.worker_session_id // empty' "$CHECKPOINT")
    if [[ "$RESUME_READY" == "1" ]]; then
      if [[ "$(jq -r '.phase_id' "$CHECKPOINT")" != "$phase_id" \
          || "$(jq -r '.iteration' "$CHECKPOINT")" != "$iteration" ]]; then
        mark_failed "resume_checkpoint_iteration_mismatch" \
          "$phase_id" "$iteration" 2
        exit 2
      fi
      prompt_kind="slurm"
      RESUME_READY=0
    elif [[ -z "$worker_session" ]]; then
      prompt_kind="initial"
    else
      prompt_kind="review"
    fi

    set +e
    worker_result=$(run_worker_turn \
      "$phase_id" "$phase_name" "$iteration" "$phase_spec" \
      "$phase_work_dir" "$prior_review" "$prompt_kind")
    worker_status=$?
    set -e
    if [[ "$worker_status" -ne 0 ]]; then
      mark_failed "worker_codex_or_result_error" \
        "$phase_id" "$iteration" "$worker_status"
      exit "$worker_status"
    fi

    worker_action=$(jq -r '.action' "$worker_result")
    if [[ "$worker_action" == "WAIT_FOR_SLURM" ]]; then
      if ! schedule_worker_wait "$phase_id" "$iteration" "$worker_result"; then
        exit 14
      fi
      exit 0
    fi

    set +e
    review_json=$(run_reviewer \
      "$phase_id" "$phase_name" "$iteration" "$phase_spec" \
      "$phase_work_dir" "$prior_review" "$worker_result")
    reviewer_result_status=$?
    set -e
    if [[ "$reviewer_result_status" -ne 0 ]]; then
      mark_failed "reviewer_output_invalid" \
        "$phase_id" "$iteration" "$reviewer_result_status"
      exit "$reviewer_result_status"
    fi

    final_decision=$(jq -r '.decision' "$review_json")
    final_review="$review_json"
    prior_review="$review_json"
    printf '  Review decision: %s\n' "$final_decision"
    atomic_jq "$CHECKPOINT" \
      --arg state "READY_FOR_WORKER" \
      --arg prior_review "$prior_review" \
      --arg final_decision "$final_decision" \
      --arg final_review "$final_review" \
      --arg updated_at "$(date --iso-8601=seconds)" \
      --argjson next_iteration "$((iteration + 1))" \
      '
        .state = $state
        | .iteration = $next_iteration
        | .prior_review = $prior_review
        | .final_decision = $final_decision
        | .final_review = $final_review
        | .slurm_jobs = []
        | .updated_at = $updated_at
      ' "$CHECKPOINT"

    if [[ "$REVIEW_POLICY" == "until_pass" \
        && "$final_decision" == "PASS" ]]; then
      phase_passed=1
      break
    fi
  done

  if [[ "$REVIEW_POLICY" == "fixed" \
      && "$final_decision" == "PASS" ]]; then
    phase_passed=1
  fi
  if [[ "$phase_passed" != "1" ]]; then
    mark_failed "review_loops_exhausted" "$phase_id" "$loop_limit" 10
    atomic_jq "$phase_dir/phase_status.json" \
      --arg final_decision "$final_decision" \
      --arg final_review "$final_review" \
      --argjson iterations "$loop_limit" \
      '
        .final_decision = $final_decision
        | .final_review = $final_review
        | .iterations = $iterations
      ' "$phase_dir/phase_status.json"
    exit 10
  fi

  completed_phases=$((completed_phases + 1))
  completed_selected_phases=$((completed_selected_phases + 1))
  atomic_jq "$phase_dir/phase_status.json" -n \
    --arg status "PASS" \
    --arg phase_id "$phase_id" \
    --arg final_review "$final_review" \
    --arg worker_session_id "$(jq -r '.worker_session_id' "$CHECKPOINT")" \
    --argjson iterations "$iterations_completed" \
    '{
      status: $status,
      phase_id: $phase_id,
      iterations: $iterations,
      final_review: $final_review,
      worker_session_id: $worker_session_id
    }'
  atomic_jq "$CHECKPOINT" \
    --arg state "PHASE_COMPLETE" \
    --arg completed_at "$(date --iso-8601=seconds)" \
    '.state = $state | .completed_at = $completed_at | .updated_at = $completed_at' \
    "$CHECKPOINT"
  atomic_jq "$RUN_STATUS" \
    --arg status "RUNNING" \
    --arg current_phase "$phase_id" \
    --arg updated_at "$(date --iso-8601=seconds)" \
    --argjson completed_phases "$completed_phases" \
    --argjson completed_selected_phases "$completed_selected_phases" \
    '
      .status = $status
      | .current_phase = $current_phase
      | .completed_phases = $completed_phases
      | .completed_selected_phases = $completed_selected_phases
      | .updated_at = $updated_at
      | del(.waiting_for_slurm)
    ' "$RUN_STATUS"
  RUNNER_MODE=run
done

finished_at=$(date --iso-8601=seconds)
atomic_jq "$RUN_STATUS" \
  --arg status "COMPLETED" \
  --arg finished_at "$finished_at" \
  '
    .status = $status
    | .finished_at = $finished_at
    | .updated_at = $finished_at
    | del(.waiting_for_slurm, .failure)
  ' "$RUN_STATUS"
{
  printf 'finished_at=%s\n' "$finished_at"
  printf 'run_status=COMPLETED\n'
} >> "$OUTPUT_DIR/run_metadata.txt"
printf 'Worker-reviewer run completed: %s selected phases passed (%s imported prerequisites)\n' \
  "$completed_selected_phases" "$IMPORTED_PHASE_COUNT"
