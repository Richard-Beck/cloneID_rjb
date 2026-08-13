#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH=$(readlink -f "${BASH_SOURCE[0]}")
ROOT_DIR=${ROOT_DIR:-$(dirname "$(dirname "$SCRIPT_PATH")")}
RUNTIME_SCRIPT=${RUNTIME_SCRIPT:-"$ROOT_DIR/scripts/codex_worker_reviewer_runtime.sh"}
PLAN_DIR=${PLAN_DIR:-"$ROOT_DIR/plans/seed1_hypothesis_test_v3"}
PLAN_JSON=${PLAN_JSON:-"$PLAN_DIR/plan.json"}
PLAN_MD=${PLAN_MD:-"$PLAN_DIR/plan.md"}
WORKER_TEMPLATE=${WORKER_TEMPLATE:-"$ROOT_DIR/prompt_templates/codex_worker_phase.txt"}
WORKER_SCHEMA=${WORKER_SCHEMA:-"$ROOT_DIR/prompt_templates/codex_worker_turn.schema.json"}
REVIEWER_TEMPLATE=${REVIEWER_TEMPLATE:-"$ROOT_DIR/prompt_templates/codex_reviewer_phase.txt"}
REVIEW_SCHEMA=${REVIEW_SCHEMA:-"$ROOT_DIR/prompt_templates/codex_reviewer_decision.schema.json"}
PROMPT_TEMPLATES_DIR=${PROMPT_TEMPLATES_DIR:-"$ROOT_DIR/prompt_templates"}
CLONEID_SKILL_DIR=${CLONEID_SKILL_DIR:-"$ROOT_DIR/.codex/skills/cloneid-database-data"}
CONTEXT_BUNDLE_NAME=${CONTEXT_BUNDLE_NAME:-context-reproducibility}
DESCRIPTIVE_ID=${DESCRIPTIVE_ID:-}

WORKER_MODEL=${WORKER_MODEL:-gpt-5.6-terra}
REVIEWER_MODEL=${REVIEWER_MODEL:-gpt-5.6-terra}
WORKER_REASONING=${WORKER_REASONING:-high}
REVIEWER_REASONING=${REVIEWER_REASONING:-xhigh}
REVIEW_POLICY=${REVIEW_POLICY:-until_pass}
MAX_REVIEW_LOOPS=${MAX_REVIEW_LOOPS:-5}
FIXED_REVIEW_LOOPS=${FIXED_REVIEW_LOOPS:-2}
REVIEWER_RETRIES=${REVIEWER_RETRIES:-2}

TIME=${TIME:-12:00:00}
MEM=${MEM:-16G}
CPUS=${CPUS:-4}
QOS=${QOS:-small}
JOB_NAME=${JOB_NAME:-codex_wr${DESCRIPTIVE_ID:+_${DESCRIPTIVE_ID}}}
PARTITION=${PARTITION:-}
ACCOUNT=${ACCOUNT:-}
EXTRA_SBATCH_ARGS=${EXTRA_SBATCH_ARGS:-}

# A worker can yield after submitting compute jobs. The runner exits, resumes
# the same saved Codex session from a dependency job, and uses an independent
# watchdog to recover invalid dependencies or excessively long waits.
RUNNER_MODE=${RUNNER_MODE:-run}
RESUME_GENERATION=${RESUME_GENERATION:-}
RESUME_TRIGGER=${RESUME_TRIGGER:-}
WATCHDOG_INTERVAL_MINUTES=${WATCHDOG_INTERVAL_MINUTES:-30}
MAX_SLURM_WAIT_HOURS=${MAX_SLURM_WAIT_HOURS:-168}
WATCHDOG_TIME=${WATCHDOG_TIME:-00:10:00}
WATCHDOG_MEM=${WATCHDOG_MEM:-1G}
WATCHDOG_QOS=${WATCHDOG_QOS:-small}
WATCHDOG_JOB_NAME=${WATCHDOG_JOB_NAME:-${JOB_NAME}_watch}

CODEX_BIN=${CODEX_BIN:-"$HOME/.conda/envs/codex/bin/codex"}
WORKER_SANDBOX=${WORKER_SANDBOX:-danger-full-access}
REVIEWER_SANDBOX=${REVIEWER_SANDBOX:-read-only}
APPROVAL_POLICY=${APPROVAL_POLICY:-never}
DRY_RUN=${DRY_RUN:-0}

# Optional execution scoping and accepted-phase handoff. PHASE_IDS is a
# comma-separated list of exact plan phase IDs. When HANDOFF_SOURCE and
# START_PHASE_ID are supplied, every plan phase before START_PHASE_ID is
# imported as an accepted prerequisite and is not executed again.
PHASE_IDS=${PHASE_IDS:-}
HANDOFF_SOURCE=${HANDOFF_SOURCE:-}
START_PHASE_ID=${START_PHASE_ID:-}
HANDOFF_STAGED=${HANDOFF_STAGED:-0}

declare -a SELECTED_PHASE_INDEXES=()
declare -a SELECTED_PHASE_ID_LIST=()
declare -a IMPORTED_PHASE_ID_LIST=()
SELECTED_PHASE_IDS_CSV=
IMPORTED_PHASE_IDS_CSV=
SELECTED_PHASE_COUNT=0
IMPORTED_PHASE_COUNT=0
START_PHASE_INDEX=0

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

require_positive_integer() {
  local name=$1 value=$2
  if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    printf '%s must be a positive integer, got: %s\n' "$name" "$value" >&2
    exit 2
  fi
}

join_by_comma() {
  local IFS=,
  printf '%s' "$*"
}

configure_execution_scope() {
  local phase_index phase_id requested_id
  local handoff_requested=0
  declare -A requested_ids=()

  SELECTED_PHASE_INDEXES=()
  SELECTED_PHASE_ID_LIST=()
  IMPORTED_PHASE_ID_LIST=()
  START_PHASE_INDEX=0

  if [[ -n "$HANDOFF_SOURCE" || "$HANDOFF_STAGED" == "1" || -n "$START_PHASE_ID" ]]; then
    handoff_requested=1
  fi
  if [[ "$handoff_requested" == "1" && -z "$START_PHASE_ID" ]]; then
    printf 'START_PHASE_ID is required when handoff mode is enabled.\n' >&2
    exit 2
  fi
  if [[ -n "$START_PHASE_ID" && -z "$HANDOFF_SOURCE" && "$HANDOFF_STAGED" != "1" ]]; then
    printf 'HANDOFF_SOURCE is required with START_PHASE_ID before handoff staging.\n' >&2
    exit 2
  fi
  if [[ -n "$HANDOFF_SOURCE" && "$HANDOFF_STAGED" == "1" ]]; then
    printf 'HANDOFF_SOURCE must not remain set after handoff staging.\n' >&2
    exit 2
  fi

  if [[ "$handoff_requested" == "1" ]]; then
    START_PHASE_INDEX=-1
    for ((phase_index = 0; phase_index < PHASE_COUNT; phase_index++)); do
      phase_id=$(jq -r ".phases[$phase_index].id" "$PLAN_JSON")
      if [[ "$phase_id" == "$START_PHASE_ID" ]]; then
        START_PHASE_INDEX=$phase_index
        break
      fi
    done
    if [[ "$START_PHASE_INDEX" -lt 0 ]]; then
      printf 'START_PHASE_ID is not present in the plan: %s\n' "$START_PHASE_ID" >&2
      exit 2
    fi
    if [[ "$START_PHASE_INDEX" -eq 0 ]]; then
      printf 'START_PHASE_ID must follow at least one phase for handoff import.\n' >&2
      exit 2
    fi
    for ((phase_index = 0; phase_index < START_PHASE_INDEX; phase_index++)); do
      IMPORTED_PHASE_ID_LIST+=("$(jq -r ".phases[$phase_index].id" "$PLAN_JSON")")
    done
  fi

  if [[ -n "$PHASE_IDS" ]]; then
    IFS=',' read -r -a requested_phase_ids <<< "$PHASE_IDS"
    for requested_id in "${requested_phase_ids[@]}"; do
      if [[ -z "$requested_id" ]]; then
        printf 'PHASE_IDS contains an empty phase ID.\n' >&2
        exit 2
      fi
      if [[ -n "${requested_ids[$requested_id]+x}" ]]; then
        printf 'PHASE_IDS contains a duplicate phase ID: %s\n' "$requested_id" >&2
        exit 2
      fi
      if ! jq -e --arg phase_id "$requested_id" \
        'any(.phases[]; .id == $phase_id)' "$PLAN_JSON" >/dev/null; then
        printf 'PHASE_IDS contains an ID absent from the plan: %s\n' "$requested_id" >&2
        exit 2
      fi
      requested_ids[$requested_id]=1
    done
  fi

  for ((phase_index = 0; phase_index < PHASE_COUNT; phase_index++)); do
    phase_id=$(jq -r ".phases[$phase_index].id" "$PLAN_JSON")
    if [[ -n "$PHASE_IDS" ]]; then
      [[ -n "${requested_ids[$phase_id]+x}" ]] || continue
    elif [[ "$handoff_requested" == "1" && "$phase_index" -lt "$START_PHASE_INDEX" ]]; then
      continue
    fi
    if [[ "$handoff_requested" == "1" && "$phase_index" -lt "$START_PHASE_INDEX" ]]; then
      printf 'PHASE_IDS requests imported phase %s; imported phases cannot be re-executed.\n' \
        "$phase_id" >&2
      exit 2
    fi
    SELECTED_PHASE_INDEXES+=("$phase_index")
    SELECTED_PHASE_ID_LIST+=("$phase_id")
  done

  if [[ "${#SELECTED_PHASE_INDEXES[@]}" -eq 0 ]]; then
    printf 'Execution scope selects no phases.\n' >&2
    exit 2
  fi

  IMPORTED_PHASE_COUNT=${#IMPORTED_PHASE_ID_LIST[@]}
  SELECTED_PHASE_COUNT=${#SELECTED_PHASE_ID_LIST[@]}
  IMPORTED_PHASE_IDS_CSV=$(join_by_comma "${IMPORTED_PHASE_ID_LIST[@]}")
  SELECTED_PHASE_IDS_CSV=$(join_by_comma "${SELECTED_PHASE_ID_LIST[@]}")
}

resolve_source_review_path() {
  local phase_dir=$1 review_path=$2
  if [[ "$review_path" == /* ]]; then
    printf '%s' "$review_path"
  else
    printf '%s/%s' "$phase_dir" "$review_path"
  fi
}

validate_handoff_source() {
  local source_dir source_phase phase_id phase_index status_file phase_spec
  local final_review review_path expected_spec observed_spec source_context

  source_dir=$(readlink -f "$HANDOFF_SOURCE" 2>/dev/null || true)
  if [[ -z "$source_dir" || ! -d "$source_dir" ]]; then
    printf 'HANDOFF_SOURCE is not an existing directory.\n' >&2
    exit 2
  fi
  if [[ "$source_dir" == "$OUTPUT_DIR" \
      || "$OUTPUT_DIR/" == "$source_dir/"* \
      || "$source_dir/" == "$OUTPUT_DIR/"* ]]; then
    printf 'Handoff source and destination must be separate, non-nested directories.\n' >&2
    exit 2
  fi
  source_context="$source_dir/${CONTEXT_BUNDLE_NAME}.zip"
  if [[ ! -f "$source_context" ]]; then
    printf 'Handoff source lacks its reproducibility context bundle.\n' >&2
    exit 2
  fi

  for ((phase_index = 0; phase_index < IMPORTED_PHASE_COUNT; phase_index++)); do
    phase_id=${IMPORTED_PHASE_ID_LIST[$phase_index]}
    source_phase="$source_dir/$phase_id"
    status_file="$source_phase/phase_status.json"
    phase_spec="$source_phase/phase_spec.json"
    if [[ ! -d "$source_phase" || ! -f "$status_file" || ! -f "$phase_spec" ]]; then
      printf 'Handoff source is missing required accepted-phase artifacts for %s.\n' \
        "$phase_id" >&2
      exit 2
    fi
    if ! jq -e --arg phase_id "$phase_id" \
      '.status == "PASS" and .phase_id == $phase_id and (.final_review | type == "string" and length > 0)' \
      "$status_file" >/dev/null; then
      printf 'Handoff phase is not marked PASS with a final review: %s\n' "$phase_id" >&2
      exit 2
    fi
    final_review=$(jq -r '.final_review' "$status_file")
    review_path=$(resolve_source_review_path "$source_phase" "$final_review")
    if [[ ! -f "$review_path" ]] || ! jq -e --arg phase_id "$phase_id" \
      '.decision == "PASS" and .phase_id == $phase_id' "$review_path" >/dev/null; then
      printf 'Handoff final review is absent or not PASS for phase %s.\n' "$phase_id" >&2
      exit 2
    fi
    expected_spec=$(jq -cS ".phases[$phase_index]" "$PLAN_JSON")
    observed_spec=$(jq -cS '.' "$phase_spec")
    if [[ "$expected_spec" != "$observed_spec" ]]; then
      printf 'Handoff phase specification differs from the current plan: %s\n' \
        "$phase_id" >&2
      exit 2
    fi
    if [[ -n "$(find "$source_phase" -type l -print -quit)" ]]; then
      printf 'Handoff phase contains symlinks and cannot be imported safely: %s\n' \
        "$phase_id" >&2
      exit 2
    fi
  done
}

replace_literal_in_text_tree() {
  local tree=$1 old_text=$2 new_text=$3 file
  [[ -n "$old_text" && "$old_text" != "$new_text" ]] || return
  # Rebase every text artifact. The forced-text audits in stage_handoff also
  # reject an unmodified literal embedded in a file rg classifies as binary.
  while IFS= read -r -d '' file; do
    OLD_TEXT="$old_text" NEW_TEXT="$new_text" \
      perl -0pi -e 's/\Q$ENV{OLD_TEXT}\E/$ENV{NEW_TEXT}/g' "$file"
  done < <(rg -uu -l -0 -F "$old_text" "$tree" 2>/dev/null || true)
}

stage_handoff() (
  local source_dir old_basename new_basename stage_root phase_id source_phase
  local staged_phase source_context context_audit manifest_path

  source_dir=$(readlink -f "$HANDOFF_SOURCE")
  old_basename=$(basename "$source_dir")
  new_basename=$(basename "$OUTPUT_DIR")
  if [[ "$new_basename" == *"$old_basename"* ]]; then
    printf 'Destination folder name must not contain the source folder name.\n' >&2
    exit 2
  fi
  if [[ -e "$OUTPUT_DIR/handoff_manifest.json" ]]; then
    printf 'Destination already contains a staged handoff manifest.\n' >&2
    exit 2
  fi
  for phase_id in "${IMPORTED_PHASE_ID_LIST[@]}"; do
    if [[ -e "$OUTPUT_DIR/$phase_id" ]]; then
      printf 'Destination already contains imported phase path: %s\n' "$phase_id" >&2
      exit 2
    fi
  done

  stage_root=$(mktemp -d "$OUTPUT_DIR/.handoff-stage.XXXXXX")
  trap 'rm -rf "$stage_root"' EXIT
  for phase_id in "${IMPORTED_PHASE_ID_LIST[@]}"; do
    source_phase="$source_dir/$phase_id"
    staged_phase="$stage_root/$phase_id"
    cp -a "$source_phase" "$staged_phase"
    replace_literal_in_text_tree "$staged_phase" "$source_dir" "$OUTPUT_DIR"
    replace_literal_in_text_tree "$staged_phase" "$old_basename" "$new_basename"
    if rg -a -uu -l -F "$source_dir" "$staged_phase" >/dev/null 2>&1 \
        || rg -a -uu -l -F "$old_basename" "$staged_phase" >/dev/null 2>&1; then
      printf 'Path rebasing left a source-run reference in imported phase %s.\n' \
        "$phase_id" >&2
      exit 2
    fi
  done

  source_context="$source_dir/${CONTEXT_BUNDLE_NAME}.zip"
  context_audit="$stage_root/source-context-audit"
  mkdir -p "$context_audit"
  unzip -q "$source_context" -d "$context_audit"
  if rg -a -uu -l -F "$source_dir" "$context_audit" >/dev/null 2>&1 \
      || rg -a -uu -l -F "$old_basename" "$context_audit" >/dev/null 2>&1; then
    printf 'Source context bundle contains a source-run path and cannot be embedded safely.\n' >&2
    exit 2
  fi

  for phase_id in "${IMPORTED_PHASE_ID_LIST[@]}"; do
    mv "$stage_root/$phase_id" "$OUTPUT_DIR/$phase_id"
  done

  manifest_path="$OUTPUT_DIR/handoff_manifest.json"
  jq -n \
    --arg start_phase "$START_PHASE_ID" \
    --arg imported_csv "$IMPORTED_PHASE_IDS_CSV" \
    '{handoff_type: "accepted_phase_import",
      imported_phase_ids: (if $imported_csv == "" then [] else ($imported_csv | split(",")) end),
      start_phase_id: $start_phase,
      paths_rebased_to_current_run: true,
      source_context: "embedded_in_context_reproducibility_bundle",
      imported_file_hashes: "embedded_in_context_reproducibility_bundle"}' \
    > "$manifest_path"

  cp "$source_context" "$OUTPUT_DIR/.handoff_phase_source_context.zip"
  (
    cd "$OUTPUT_DIR"
    find "${IMPORTED_PHASE_ID_LIST[@]}" -type f -print0 \
      | sort -z \
      | xargs -0 sha256sum > .handoff_imported_files.sha256
  )
)

validate_staged_handoff() {
  local phase_id phase_index phase_dir status_file phase_spec final_review
  local expected_spec observed_spec
  if [[ ! -f "$OUTPUT_DIR/handoff_manifest.json" ]]; then
    printf 'Staged handoff manifest is missing.\n' >&2
    exit 2
  fi
  if ! jq -e \
    --arg start_phase "$START_PHASE_ID" \
    --arg imported_csv "$IMPORTED_PHASE_IDS_CSV" \
    '.handoff_type == "accepted_phase_import"
     and .start_phase_id == $start_phase
     and .imported_phase_ids == (if $imported_csv == "" then [] else ($imported_csv | split(",")) end)' \
    "$OUTPUT_DIR/handoff_manifest.json" >/dev/null; then
    printf 'Staged handoff manifest does not match the requested execution scope.\n' >&2
    exit 2
  fi
  for ((phase_index = 0; phase_index < IMPORTED_PHASE_COUNT; phase_index++)); do
    phase_id=${IMPORTED_PHASE_ID_LIST[$phase_index]}
    phase_dir="$OUTPUT_DIR/$phase_id"
    status_file="$phase_dir/phase_status.json"
    phase_spec="$phase_dir/phase_spec.json"
    if [[ ! -d "$phase_dir" || ! -f "$status_file" || ! -f "$phase_spec" ]]; then
      printf 'Staged handoff is missing imported phase %s.\n' "$phase_id" >&2
      exit 2
    fi
    if ! jq -e --arg phase_id "$phase_id" \
      '.status == "PASS" and .phase_id == $phase_id' "$status_file" >/dev/null; then
      printf 'Staged imported phase is not marked PASS: %s\n' "$phase_id" >&2
      exit 2
    fi
    final_review=$(jq -r '.final_review' "$status_file")
    if [[ "$final_review" != /* ]]; then
      final_review="$phase_dir/$final_review"
    fi
    if [[ ! -f "$final_review" ]] || ! jq -e --arg phase_id "$phase_id" \
      '.decision == "PASS" and .phase_id == $phase_id' "$final_review" >/dev/null; then
      printf 'Staged imported phase lacks its accepted final review: %s\n' "$phase_id" >&2
      exit 2
    fi
    expected_spec=$(jq -cS ".phases[$phase_index]" "$PLAN_JSON")
    observed_spec=$(jq -cS '.' "$phase_spec")
    if [[ "$expected_spec" != "$observed_spec" ]]; then
      printf 'Staged imported phase specification differs from the current plan: %s\n' \
        "$phase_id" >&2
      exit 2
    fi
    if [[ -n "$(find "$phase_dir" -type l -print -quit)" ]]; then
      printf 'Staged imported phase contains a symlink: %s\n' "$phase_id" >&2
      exit 2
    fi
  done
}

capture_reproducibility_context() (
  local bundle_stage bundle_root bundle_tmp runner_name runtime_name

  if [[ -f "$CONTEXT_BUNDLE" ]]; then
    return
  fi

  bundle_stage=$(mktemp -d "$OUTPUT_DIR/.${CONTEXT_BUNDLE_NAME}.XXXXXX")
  bundle_root="$bundle_stage/$CONTEXT_BUNDLE_NAME"
  bundle_tmp="$OUTPUT_DIR/.${CONTEXT_BUNDLE_NAME}.zip.tmp.$$"
  runner_name=$(basename "$SCRIPT_PATH")
  runtime_name=$(basename "$RUNTIME_SCRIPT")
  trap 'rm -rf "$bundle_stage" "$bundle_tmp"' EXIT

  mkdir -p "$bundle_root/plan"
  mkdir -p "$bundle_root/skill/cloneid-database-data"
  mkdir -p "$bundle_root/prompt_templates"
  mkdir -p "$bundle_root/runner"
  cp -a "$PLAN_DIR/." "$bundle_root/plan/"
  cp -a "$CLONEID_SKILL_DIR/." "$bundle_root/skill/cloneid-database-data/"
  cp -a "$PROMPT_TEMPLATES_DIR/." "$bundle_root/prompt_templates/"
  cp -a "$SCRIPT_PATH" "$bundle_root/runner/$runner_name"
  cp -a "$RUNTIME_SCRIPT" "$bundle_root/runner/$runtime_name"

  if [[ "$HANDOFF_STAGED" == "1" ]]; then
    if [[ ! -f "$OUTPUT_DIR/handoff_manifest.json" \
        || ! -f "$OUTPUT_DIR/.handoff_phase_source_context.zip" \
        || ! -f "$OUTPUT_DIR/.handoff_imported_files.sha256" ]]; then
      printf 'Staged handoff provenance is incomplete before context capture.\n' >&2
      exit 2
    fi
    mkdir -p "$bundle_root/handoff"
    cp "$OUTPUT_DIR/handoff_manifest.json" \
      "$bundle_root/handoff/import_manifest.json"
    cp "$OUTPUT_DIR/.handoff_phase_source_context.zip" \
      "$bundle_root/handoff/phase_1_source_context.zip"
    cp "$OUTPUT_DIR/.handoff_imported_files.sha256" \
      "$bundle_root/handoff/imported_phase_files.sha256"
  fi

  {
    printf 'captured_at=%s\n' "$(date --iso-8601=seconds)"
    printf 'plan_dir=%s\n' "$PLAN_DIR"
    printf 'cloneid_skill_dir=%s\n' "$CLONEID_SKILL_DIR"
    printf 'prompt_templates_dir=%s\n' "$PROMPT_TEMPLATES_DIR"
    printf 'runner_script=%s\n' "$SCRIPT_PATH"
    printf 'runtime_script=%s\n' "$RUNTIME_SCRIPT"
  } > "$bundle_root/SOURCES.txt"

  (
    cd "$bundle_root"
    find . -type f ! -path './MANIFEST.sha256' -print0 \
      | sort -z \
      | xargs -0 sha256sum > MANIFEST.sha256
  )
  (
    cd "$bundle_stage"
    zip -qr "$bundle_tmp" "$CONTEXT_BUNDLE_NAME"
  )
  mv "$bundle_tmp" "$CONTEXT_BUNDLE"
)

validate_configuration() {
  local path executable
  for path in "$RUNTIME_SCRIPT" "$PLAN_JSON" "$WORKER_TEMPLATE" "$WORKER_SCHEMA" \
    "$REVIEWER_TEMPLATE" "$REVIEW_SCHEMA"; do
    if [[ ! -f "$path" ]]; then
      printf 'Required file does not exist: %s\n' "$path" >&2
      exit 2
    fi
  done
  for path in "$PLAN_DIR" "$PROMPT_TEMPLATES_DIR" "$CLONEID_SKILL_DIR"; do
    if [[ ! -d "$path" ]]; then
      printf 'Required directory does not exist: %s\n' "$path" >&2
      exit 2
    fi
  done
  if [[ "$CONTEXT_BUNDLE_NAME" == "." \
      || "$CONTEXT_BUNDLE_NAME" == ".." \
      || ! "$CONTEXT_BUNDLE_NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then
    printf 'CONTEXT_BUNDLE_NAME contains unsafe characters: %s\n' \
      "$CONTEXT_BUNDLE_NAME" >&2
    exit 2
  fi
  if ! command -v zip >/dev/null; then
    printf 'Required executable is unavailable: zip\n' >&2
    exit 2
  fi
  for executable in jq sha256sum sort xargs flock sbatch sacct squeue; do
    if ! command -v "$executable" >/dev/null; then
      printf 'Required executable is unavailable: %s\n' "$executable" >&2
      exit 2
    fi
  done
  if [[ -n "$HANDOFF_SOURCE" || "$HANDOFF_STAGED" == "1" ]]; then
    for executable in rg perl unzip; do
      if ! command -v "$executable" >/dev/null; then
        printf 'Handoff executable is unavailable: %s\n' "$executable" >&2
        exit 2
      fi
    done
  fi
  if [[ "$HANDOFF_STAGED" != "0" && "$HANDOFF_STAGED" != "1" ]]; then
    printf 'HANDOFF_STAGED must be 0 or 1.\n' >&2
    exit 2
  fi
  jq -e '
    . as $plan
    | (($plan.schema_version == 1 and $plan.authoritative_plan == "plan.md")
      or ($plan.schema_version == 2 and $plan.authoritative_plan == "plan.json"))
    and ($plan.phases | type == "array" and length > 0)
    and ([$plan.phases[].id] | length == (unique | length))
    and ([$plan.phases[].order] | length == (unique | length))
    and all($plan.phases[];
      (.id | type == "string" and test("^[A-Za-z0-9._-]+$"))
      and (.name | type == "string" and length > 0)
      and (.objective | type == "string" and length > 0)
      and (.review_focus | type == "array" and length > 0)
      and (
        if $plan.schema_version == 1 then
          (.source_section | type == "string" and length > 0)
          and (.minimum_outputs | type == "array" and length > 0)
        else
          (.output_contract | type == "object" and length > 0)
        end
      )
    )' "$PLAN_JSON" >/dev/null
  AUTHORITATIVE_PLAN_KIND=$(jq -r '.authoritative_plan' "$PLAN_JSON")
  if [[ "$AUTHORITATIVE_PLAN_KIND" == "plan.md" ]]; then
    if [[ ! -f "$PLAN_MD" ]]; then
      printf 'Required file does not exist: %s\n' "$PLAN_MD" >&2
      exit 2
    fi
    while IFS= read -r source_section; do
      if ! grep -Fqx "$source_section" "$PLAN_MD"; then
        printf 'JSON phase source section is absent from Markdown plan: %s\n' \
          "$source_section" >&2
        exit 2
      fi
    done < <(jq -r '.phases[].source_section' "$PLAN_JSON")
  fi
  jq -e '.type == "object" and (.properties.decision.enum == ["PASS", "FAIL"])' \
    "$REVIEW_SCHEMA" >/dev/null
  jq -e '
    .type == "object"
    and (.properties.action.enum == ["COMPLETE", "WAIT_FOR_SLURM"])
    and (.properties.slurm_jobs.type == "array")' \
    "$WORKER_SCHEMA" >/dev/null
  if [[ "$RUNNER_MODE" != "run" \
      && "$RUNNER_MODE" != "continue" \
      && "$RUNNER_MODE" != "watchdog" ]]; then
    printf 'RUNNER_MODE must be run, continue, or watchdog, got: %s\n' \
      "$RUNNER_MODE" >&2
    exit 2
  fi
  if [[ "$REVIEW_POLICY" != "until_pass" && "$REVIEW_POLICY" != "fixed" ]]; then
    printf 'REVIEW_POLICY must be until_pass or fixed, got: %s\n' \
      "$REVIEW_POLICY" >&2
    exit 2
  fi
  require_positive_integer MAX_REVIEW_LOOPS "$MAX_REVIEW_LOOPS"
  require_positive_integer FIXED_REVIEW_LOOPS "$FIXED_REVIEW_LOOPS"
  require_positive_integer REVIEWER_RETRIES "$REVIEWER_RETRIES"
  require_positive_integer WATCHDOG_INTERVAL_MINUTES "$WATCHDOG_INTERVAL_MINUTES"
  require_positive_integer MAX_SLURM_WAIT_HOURS "$MAX_SLURM_WAIT_HOURS"
}

resolve_output_dir
CONTEXT_BUNDLE="$OUTPUT_DIR/${CONTEXT_BUNDLE_NAME}.zip"
validate_configuration
PHASE_COUNT=$(jq '.phases | length' "$PLAN_JSON")
configure_execution_scope
if [[ -n "$HANDOFF_SOURCE" ]]; then
  validate_handoff_source
elif [[ "$HANDOFF_STAGED" == "1" ]]; then
  validate_staged_handoff
fi

if [[ "$DRY_RUN" == "1" ]]; then
  printf 'DRY_RUN\n'
  printf 'AUTHORITATIVE_PLAN=%s\nPLAN_JSON=%s\nOUTPUT_DIR=%s\n' \
    "$AUTHORITATIVE_PLAN_KIND" "$PLAN_JSON" "$OUTPUT_DIR"
  printf 'DESCRIPTIVE_ID=%s\n' "$DESCRIPTIVE_ID"
  printf 'CONTEXT_BUNDLE=%s\n' "$CONTEXT_BUNDLE"
  if [[ "$AUTHORITATIVE_PLAN_KIND" == "plan.md" ]]; then
    printf 'PLAN_MD=%s\n' "$PLAN_MD"
  fi
  printf 'PHASE_COUNT=%s\nREVIEW_POLICY=%s\n' "$PHASE_COUNT" "$REVIEW_POLICY"
  printf 'SELECTED_PHASE_COUNT=%s\nSELECTED_PHASE_IDS=%s\n' \
    "$SELECTED_PHASE_COUNT" "$SELECTED_PHASE_IDS_CSV"
  printf 'IMPORTED_PHASE_COUNT=%s\nIMPORTED_PHASE_IDS=%s\n' \
    "$IMPORTED_PHASE_COUNT" "$IMPORTED_PHASE_IDS_CSV"
  if [[ -n "$START_PHASE_ID" ]]; then
    printf 'HANDOFF_MODE=enabled\nSTART_PHASE_ID=%s\n' "$START_PHASE_ID"
  else
    printf 'HANDOFF_MODE=disabled\n'
  fi
  printf 'MAX_REVIEW_LOOPS=%s\nFIXED_REVIEW_LOOPS=%s\n' \
    "$MAX_REVIEW_LOOPS" "$FIXED_REVIEW_LOOPS"
  printf 'WORKER_MODEL=%s\nWORKER_REASONING=%s\n' \
    "$WORKER_MODEL" "$WORKER_REASONING"
  printf 'REVIEWER_MODEL=%s\nREVIEWER_REASONING=%s\n' \
    "$REVIEWER_MODEL" "$REVIEWER_REASONING"
  printf 'TIME=%s\nMEM=%s\nCPUS=%s\nQOS=%s\n' \
    "$TIME" "$MEM" "$CPUS" "$QOS"
  printf 'WATCHDOG_INTERVAL_MINUTES=%s\nMAX_SLURM_WAIT_HOURS=%s\n' \
    "$WATCHDOG_INTERVAL_MINUTES" "$MAX_SLURM_WAIT_HOURS"
  printf 'WATCHDOG_TIME=%s\nWATCHDOG_MEM=%s\nWATCHDOG_QOS=%s\n' \
    "$WATCHDOG_TIME" "$WATCHDOG_MEM" "$WATCHDOG_QOS"
  if [[ -z "${SLURM_JOB_ID:-}" ]]; then
    printf 'ACTION=submit\n'
  else
    printf 'ACTION=execute-within-slurm-job\n'
  fi
  exit 0
fi

mkdir -p "$OUTPUT_DIR"
if [[ -n "$HANDOFF_SOURCE" ]]; then
  stage_handoff
  HANDOFF_STAGED=1
  unset HANDOFF_SOURCE
  validate_staged_handoff
fi
capture_reproducibility_context
rm -f "$OUTPUT_DIR/.handoff_phase_source_context.zip" \
  "$OUTPUT_DIR/.handoff_imported_files.sha256"

export SCRIPT_PATH ROOT_DIR RUNTIME_SCRIPT PLAN_DIR PLAN_MD PLAN_JSON OUTPUT_DIR DESCRIPTIVE_ID
export AUTHORITATIVE_PLAN_KIND
export WORKER_TEMPLATE WORKER_SCHEMA REVIEWER_TEMPLATE REVIEW_SCHEMA
export PROMPT_TEMPLATES_DIR CLONEID_SKILL_DIR
export CONTEXT_BUNDLE_NAME CONTEXT_BUNDLE
export WORKER_MODEL REVIEWER_MODEL WORKER_REASONING REVIEWER_REASONING
export REVIEW_POLICY MAX_REVIEW_LOOPS FIXED_REVIEW_LOOPS REVIEWER_RETRIES
export TIME MEM CPUS QOS JOB_NAME CODEX_BIN
export WORKER_SANDBOX REVIEWER_SANDBOX APPROVAL_POLICY
export PHASE_IDS START_PHASE_ID HANDOFF_STAGED
export PHASE_COUNT SELECTED_PHASE_COUNT SELECTED_PHASE_IDS_CSV
export IMPORTED_PHASE_COUNT IMPORTED_PHASE_IDS_CSV
export PARTITION ACCOUNT EXTRA_SBATCH_ARGS
export RUNNER_MODE RESUME_GENERATION RESUME_TRIGGER
export WATCHDOG_INTERVAL_MINUTES MAX_SLURM_WAIT_HOURS
export WATCHDOG_TIME WATCHDOG_MEM WATCHDOG_QOS WATCHDOG_JOB_NAME

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
    # shellcheck disable=SC2206
    extra_args=( $EXTRA_SBATCH_ARGS )
    sbatch_args+=("${extra_args[@]}")
  fi

  printf 'PLAN_JSON=%s\nOUTPUT_DIR=%s\nCONTEXT_BUNDLE=%s\nREVIEW_POLICY=%s\n' \
    "$PLAN_JSON" "$OUTPUT_DIR" "$CONTEXT_BUNDLE" "$REVIEW_POLICY"
  printf 'SELECTED_PHASE_IDS=%s\nIMPORTED_PHASE_IDS=%s\n' \
    "$SELECTED_PHASE_IDS_CSV" "$IMPORTED_PHASE_IDS_CSV"
  exec sbatch "${sbatch_args[@]}" "$SCRIPT_PATH"
fi

if [[ "$RUNNER_MODE" != "run" \
    && -f "$OUTPUT_DIR/orchestration/codex_worker_reviewer_runtime.sh" ]]; then
  RUNTIME_SCRIPT="$OUTPUT_DIR/orchestration/codex_worker_reviewer_runtime.sh"
  export RUNTIME_SCRIPT
fi
exec bash "$RUNTIME_SCRIPT"
