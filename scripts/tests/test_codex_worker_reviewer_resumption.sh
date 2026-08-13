#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(readlink -f "$(dirname "${BASH_SOURCE[0]}")/../..")
TEST_ROOT=$(mktemp -d)
trap 'rm -rf "$TEST_ROOT"' EXIT

jq -e '
  .type == "object"
  and (.properties.action.enum == ["COMPLETE", "WAIT_FOR_SLURM"])
  and (has("allOf") | not)
  and (has("if") | not)
  and (has("then") | not)
  and (has("else") | not)
  and ([.. | objects | select(has("uniqueItems"))] | length == 0)
' "$ROOT_DIR/prompt_templates/codex_worker_turn.schema.json" >/dev/null

mkdir -p \
  "$TEST_ROOT/bin" \
  "$TEST_ROOT/plan" \
  "$TEST_ROOT/skill" \
  "$TEST_ROOT/run"

cat > "$TEST_ROOT/plan/plan.json" <<'JSON'
{
  "schema_version": 2,
  "plan_id": "runner_resume_smoke",
  "authoritative_plan": "plan.json",
  "objective": "Exercise worker yield, watchdog recovery, session resume, and review.",
  "phases": [
    {
      "id": "phase_1_smoke",
      "order": 1,
      "name": "Smoke phase",
      "objective": "Exercise the runner state machine.",
      "output_contract": {
        "result": "A smoke-test result."
      },
      "review_focus": [
        "Did the persistent worker resume?"
      ]
    }
  ]
}
JSON

cat > "$TEST_ROOT/bin/codex" <<'BASH'
#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--version" ]]; then
  printf 'codex-cli fake-test\n'
  exit 0
fi

output_file=""
ephemeral=0
resume=0
previous=""
for argument in "$@"; do
  if [[ "$previous" == "--output-last-message" ]]; then
    output_file=$argument
  fi
  [[ "$argument" == "--ephemeral" ]] && ephemeral=1
  [[ "$argument" == "resume" ]] && resume=1
  previous=$argument
done
if [[ -z "$output_file" ]]; then
  printf 'Fake Codex did not receive --output-last-message.\n' >&2
  exit 2
fi

prompt=$(cat)
printf '%s\n' "$*" >> "$FAKE_CODEX_CALLS"
if [[ "$ephemeral" == "1" ]]; then
  review_count=0
  if [[ -f "$FAKE_REVIEW_COUNT" ]]; then
    read -r review_count < "$FAKE_REVIEW_COUNT"
  fi
  review_count=$((review_count + 1))
  printf '%s\n' "$review_count" > "$FAKE_REVIEW_COUNT"
  if [[ "$review_count" == "1" ]]; then
    cat > "$output_file" <<'JSON'
{
  "phase_id": "phase_1_smoke",
  "iteration": 1,
  "decision": "FAIL",
  "summary": "Exercise the same-session reviewer revision path.",
  "scientific_credibility_score": 4,
  "scope_completeness_score": 4,
  "data_integrity_score": 5,
  "hypothesis_alignment_score": 5,
  "artifact_quality_score": 4,
  "file_organization_hygiene_score": 5,
  "evidence_inspected": ["worker result"],
  "strengths": ["Persistent session resumed after SLURM."],
  "blocking_issues": ["A bounded smoke revision remains."],
  "required_revisions": ["Acknowledge the bounded smoke revision."],
  "nonblocking_suggestions": [],
  "lazy_or_superficial_work_detected": false
}
JSON
  else
    cat > "$output_file" <<'JSON'
{
  "phase_id": "phase_1_smoke",
  "iteration": 2,
  "decision": "PASS",
  "summary": "The same worker completed the reviewer revision.",
  "scientific_credibility_score": 5,
  "scope_completeness_score": 5,
  "data_integrity_score": 5,
  "hypothesis_alignment_score": 5,
  "artifact_quality_score": 5,
  "file_organization_hygiene_score": 5,
  "evidence_inspected": ["worker result"],
  "strengths": ["Persistent session resumed."],
  "blocking_issues": [],
  "required_revisions": [],
  "nonblocking_suggestions": [],
  "lazy_or_superficial_work_detected": false
}
JSON
  fi
  printf '{"type":"thread.started","thread_id":"reviewer-thread"}\n'
elif [[ "$resume" == "1" ]]; then
  if grep -Fq 'review iteration 2' <<< "$prompt"; then
    worker_iteration=2
  else
    worker_iteration=1
  fi
  jq -n \
    --argjson iteration "$worker_iteration" \
    '{
      phase_id: "phase_1_smoke",
      iteration: $iteration,
      action: "COMPLETE",
      summary: "Resumed the same worker and inspected the available context.",
      slurm_jobs: []
    }' > "$output_file"
  printf '{"type":"thread.started","thread_id":"worker-session-1"}\n'
else
  cat > "$output_file" <<'JSON'
{
  "phase_id": "phase_1_smoke",
  "iteration": 1,
  "action": "WAIT_FOR_SLURM",
  "summary": "Submitted the smoke compute job.",
  "slurm_jobs": [
    {
      "job_id": "9001",
      "purpose": "Smoke compute",
      "log_paths": ["job.log"],
      "expected_outputs": ["result.txt"]
    }
  ]
}
JSON
  printf '{"type":"thread.started","thread_id":"worker-session-1"}\n'
fi
printf '{"type":"turn.completed"}\n'
BASH

cat > "$TEST_ROOT/bin/sbatch" <<'BASH'
#!/usr/bin/env bash
set -euo pipefail
counter=7000
if [[ -f "$FAKE_SBATCH_COUNTER" ]]; then
  read -r counter < "$FAKE_SBATCH_COUNTER"
fi
counter=$((counter + 1))
printf '%s\n' "$counter" > "$FAKE_SBATCH_COUNTER"
printf '%s\t%s\n' "$counter" "$*" >> "$FAKE_SBATCH_CALLS"
printf '%s\n' "$counter"
BASH

cat > "$TEST_ROOT/bin/squeue" <<'BASH'
#!/usr/bin/env bash
set -euo pipefail
# Empty output means the fake jobs are no longer in the live controller view.
exit 0
BASH

cat > "$TEST_ROOT/bin/sacct" <<'BASH'
#!/usr/bin/env bash
set -euo pipefail
job_id=""
state_reason_only=0
previous=""
for argument in "$@"; do
  if [[ "$previous" == "-j" || "$previous" == "--jobs" ]]; then
    job_id=$argument
  fi
  [[ "$argument" == "--format=State,Reason" ]] && state_reason_only=1
  previous=$argument
done
case "$job_id" in
  9001)
    if [[ "${FAKE_COMPUTE_TERMINAL:-0}" == "1" ]]; then
      printf '9001|FAILED|1:0|NonZeroExitCode\n'
    else
      printf '9001|PENDING|0:0|Dependency\n'
    fi
    ;;
  7001)
    if [[ "$state_reason_only" == "1" ]]; then
      printf 'CANCELLED|DependencyNeverSatisfied\n'
    else
      printf '7001|CANCELLED|0:0|DependencyNeverSatisfied\n'
    fi
    ;;
  *)
    printf '%s|COMPLETED|0:0|None\n' "${job_id:-0}"
    ;;
esac
BASH

chmod +x \
  "$TEST_ROOT/bin/codex" \
  "$TEST_ROOT/bin/sbatch" \
  "$TEST_ROOT/bin/squeue" \
  "$TEST_ROOT/bin/sacct"

export PATH="$TEST_ROOT/bin:$PATH"
export FAKE_CODEX_CALLS="$TEST_ROOT/codex_calls.txt"
export FAKE_SBATCH_CALLS="$TEST_ROOT/sbatch_calls.txt"
export FAKE_SBATCH_COUNTER="$TEST_ROOT/sbatch_counter.txt"
export FAKE_REVIEW_COUNT="$TEST_ROOT/review_count.txt"

run_launcher() {
  env \
    ROOT_DIR="$ROOT_DIR" \
    OUTPUT_DIR="$TEST_ROOT/run" \
    PLAN_DIR="$TEST_ROOT/plan" \
    PLAN_JSON="$TEST_ROOT/plan/plan.json" \
    CLONEID_SKILL_DIR="$TEST_ROOT/skill" \
    CODEX_BIN="$TEST_ROOT/bin/codex" \
    WORKER_MODEL="fake-worker" \
    REVIEWER_MODEL="fake-reviewer" \
    WORKER_REASONING="medium" \
    REVIEWER_REASONING="xhigh" \
    REVIEW_POLICY="until_pass" \
    WATCHDOG_INTERVAL_MINUTES=1 \
    MAX_SLURM_WAIT_HOURS=1 \
    SLURM_JOB_ID="$1" \
    RUNNER_MODE="$2" \
    RESUME_GENERATION="${3:-}" \
    RESUME_TRIGGER="${4:-}" \
    "$ROOT_DIR/scripts/codex_worker_reviewer_execution.sh"
}

# Initial worker creates a persistent session, yields, and schedules both jobs.
run_launcher 6000 run
jq -e '
  .state == "WAITING_FOR_SLURM"
  and .worker_session_id == "worker-session-1"
  and .resume_generation == 1
  and .continuation_job_id == "7001"
  and .watchdog_job_id == "7002"
' "$TEST_ROOT/run/orchestration/worker_checkpoint.json" >/dev/null
jq -e '.status == "WAITING_FOR_SLURM"' \
  "$TEST_ROOT/run/run_status.json" >/dev/null

# The dependency continuation is cancelled. The independent watchdog should
# schedule a full-sized, dependency-free recovery continuation without Codex.
run_launcher 7002 watchdog 1 watchdog
jq -e '
  .state == "WAITING_FOR_SLURM"
  and .continuation_job_id == "7003"
  and .continuation_kind == "watchdog_recovery"
  and .resume_trigger == "watchdog_continuation_terminal_cancelled"
' "$TEST_ROOT/run/orchestration/worker_checkpoint.json" >/dev/null
[[ "$(wc -l < "$FAKE_CODEX_CALLS")" -eq 1 ]]

# Recovery resumes the exact worker session, then sends completed work to a
# separate ephemeral reviewer.
export FAKE_COMPUTE_TERMINAL=1
printf 'fake log\n' > "$TEST_ROOT/run/phase_1_smoke/work/job.log"
printf 'fake result\n' > "$TEST_ROOT/run/phase_1_smoke/work/result.txt"
run_launcher \
  7003 continue 1 watchdog_continuation_terminal_cancelled

jq -e '
  .status == "PASS"
  and .worker_session_id == "worker-session-1"
  and .iterations == 2
' "$TEST_ROOT/run/phase_1_smoke/phase_status.json" >/dev/null
jq -e '.status == "COMPLETED" and .completed_selected_phases == 1' \
  "$TEST_ROOT/run/run_status.json" >/dev/null
jq -e '
  .trigger == "watchdog_continuation_terminal_cancelled"
  and .jobs[0].job_id == "9001"
  and .jobs[0].terminal == true
  and ([.path_checks[].exists] | all)
' "$TEST_ROOT/run/phase_1_smoke/iteration_01/scheduler_generation_0001.json" \
  >/dev/null

[[ "$(wc -l < "$FAKE_CODEX_CALLS")" -eq 5 ]]
sed -n '1p' "$FAKE_CODEX_CALLS" | grep -Fv -- '--ephemeral' >/dev/null
sed -n '2p' "$FAKE_CODEX_CALLS" | grep -F -- \
  'exec resume' >/dev/null
sed -n '2p' "$FAKE_CODEX_CALLS" | grep -F -- \
  'worker-session-1' >/dev/null
sed -n '3p' "$FAKE_CODEX_CALLS" | grep -F -- \
  '--ephemeral' >/dev/null
sed -n '4p' "$FAKE_CODEX_CALLS" | grep -F -- \
  'exec resume' >/dev/null
sed -n '4p' "$FAKE_CODEX_CALLS" | grep -F -- \
  'worker-session-1' >/dev/null
sed -n '5p' "$FAKE_CODEX_CALLS" | grep -F -- \
  '--ephemeral' >/dev/null

printf 'PASS: persistent worker yield/watchdog/resume/review smoke test\n'
