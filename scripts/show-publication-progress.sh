#!/usr/bin/env bash
# Monitor governed Exposure publication without exposing credentials.
set -uo pipefail

RESOURCE_GROUP="${AIOPS_PUBLICATION_RESOURCE_GROUP:-aiops-dev-rg}"
JOB_NAME="${AIOPS_PUBLICATION_JOB:-aiops-dev-exposure-publication}"
EXECUTION_NAME="${AIOPS_PUBLICATION_EXECUTION:-}"
INTERVAL_SECONDS="${AIOPS_PUBLICATION_PROGRESS_INTERVAL:-30}"
TAIL_LINES="${AIOPS_PUBLICATION_PROGRESS_TAIL:-300}"
ONCE=0

usage() {
  cat <<'EOF'
Usage: show-publication-progress.sh [options]

Continuously displays detailed Azure Container Apps Job publication progress.
The display refreshes every 30 seconds by default and exits after the selected
execution reaches a terminal state.

Options:
  --resource-group NAME  Resource group (default: aiops-dev-rg)
  --job NAME             Container Apps Job (default: aiops-dev-exposure-publication)
  --execution NAME       Exact execution; defaults to active, otherwise latest
  --interval SECONDS     Refresh interval (default: 30)
  --tail LINES           Log lines inspected each refresh (1-300; default: 300)
  --once                 Print one snapshot and exit
  -h, --help             Show this help

Environment variables:
  AIOPS_PUBLICATION_RESOURCE_GROUP
  AIOPS_PUBLICATION_JOB
  AIOPS_PUBLICATION_EXECUTION
  AIOPS_PUBLICATION_PROGRESS_INTERVAL
  AIOPS_PUBLICATION_PROGRESS_TAIL
EOF
}

while (($#)); do
  case "$1" in
    --resource-group)
      RESOURCE_GROUP="${2:?missing value for --resource-group}"
      shift 2
      ;;
    --job)
      JOB_NAME="${2:?missing value for --job}"
      shift 2
      ;;
    --execution)
      EXECUTION_NAME="${2:?missing value for --execution}"
      shift 2
      ;;
    --interval)
      INTERVAL_SECONDS="${2:?missing value for --interval}"
      shift 2
      ;;
    --tail)
      TAIL_LINES="${2:?missing value for --tail}"
      shift 2
      ;;
    --once)
      ONCE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$INTERVAL_SECONDS" in
  ''|*[!0-9]*)
    printf 'Interval must be a positive integer.\n' >&2
    exit 2
    ;;
esac
case "$TAIL_LINES" in
  ''|*[!0-9]*)
    printf 'Tail count must be a positive integer.\n' >&2
    exit 2
    ;;
esac
if [ "$INTERVAL_SECONDS" -lt 1 ] || [ "$TAIL_LINES" -lt 1 ] || [ "$TAIL_LINES" -gt 300 ]; then
  printf 'Interval must be positive and tail count must be between 1 and 300.\n' >&2
  exit 2
fi

for command in az python3; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf 'Required command is unavailable: %s\n' "$command" >&2
    exit 1
  fi
done

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/publication-progress.XXXXXX")"
cleanup() {
  rm -f "$WORK_DIR"/*
  rmdir "$WORK_DIR" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

availability_notice() {
  local query_name="$1"
  local marker="$WORK_DIR/${query_name}-query-unavailable"
  if [ ! -e "$marker" ]; then
    printf 'Notice: Log Analytics %s progress is temporarily unavailable; continuing without it.\n' \
      "$query_name" >&2
    : >"$marker"
  fi
}

run_required_az_query() {
  local description="$1"
  shift

  "$@"
  local status=$?
  if [ "$status" -ne 0 ]; then
    printf 'Error: required Azure CLI query failed (%s); publication monitoring cannot continue.\n' \
      "$description" >&2
    return "$status"
  fi
}

select_execution() {
  if [ -n "$EXECUTION_NAME" ]; then
    printf '%s\n' "$EXECUTION_NAME"
    return
  fi

  local selected
  if ! selected="$(
    run_required_az_query "listing active executions for job '$JOB_NAME' in resource group '$RESOURCE_GROUP'" \
      az containerapp job execution list \
      --name "$JOB_NAME" \
      --resource-group "$RESOURCE_GROUP" \
      --query "[?properties.status=='Running' || properties.status=='Processing' || properties.status=='Pending' || properties.status=='Starting'] | sort_by(@, &properties.startTime)[-1].name" \
      --output tsv
  )"; then
    return 1
  fi
  if [ -z "$selected" ]; then
    if ! selected="$(
      run_required_az_query "listing latest execution for job '$JOB_NAME' in resource group '$RESOURCE_GROUP'" \
        az containerapp job execution list \
        --name "$JOB_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --query "sort_by(@, &properties.startTime)[-1].name" \
        --output tsv
    )"; then
      return 1
    fi
  fi
  printf '%s\n' "$selected"
}

render_logs() {
  local log_file="$1"
  local table_state_file="$2"
  python3 - "$log_file" "$table_state_file" <<'PY'
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime

path, table_state_path = sys.argv[1:]
events = []
diagnostics = []

def activation_progress_event(message):
    try:
        decoded = json.loads(message)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, dict) and decoded.get("event") == "activation_progress":
        return decoded

    if '"event"' not in message or "activation_progress" not in message:
        return None
    decoder = json.JSONDecoder()
    offset = 0
    while True:
        start = message.find("{", offset)
        if start < 0:
            return None
        try:
            candidate, consumed = decoder.raw_decode(message[start:])
        except json.JSONDecodeError:
            offset = start + 1
            continue
        if (
            isinstance(candidate, dict)
            and candidate.get("event") == "activation_progress"
        ):
            return candidate
        offset = start + max(consumed, 1)


with open(path, encoding="utf-8", errors="replace") as stream:
    for raw_line in stream:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            outer = json.loads(raw_line)
            timestamp = str(outer.get("TimeStamp") or "")
            message = str(outer.get("Log") or "")
        except json.JSONDecodeError:
            match = re.match(r'^\{"TimeStamp":"([^"]+)","Log":"(.*)"\}$', raw_line)
            timestamp = match.group(1) if match else ""
            message = match.group(2) if match else raw_line

        event = activation_progress_event(message)
        if event is not None:
            event["_timestamp"] = timestamp
            events.append(event)
            continue

        lowered = message.casefold()
        if any(
            token in lowered
            for token in (
                "warning",
                "failed",
                "error",
                "traceback",
                "out of memory",
                "oom",
                "killed",
            )
        ):
            diagnostics.append((timestamp, message))

if events:
    events.sort(key=lambda event: str(event.get("_timestamp") or ""))
    latest = events[-1]
    print("\nLatest structured progress")
    print("--------------------------")
    fields = (
        "stage",
        "status",
        "elapsed_seconds",
        "completed",
        "total",
        "dataset_count",
        "table_name",
        "row_count",
        "entity_count",
        "relationship_count",
        "failure_count",
        "generation_id",
        "publication_id",
        "checkpoint_id",
        "checkpoint_state",
        "checkpoint_rows_written",
        "checkpoint_bytes_written",
        "current_phase",
        "resumed_tables",
        "skipped_tables",
        "remaining_tables",
        "run_id",
        "source_run_id",
        "error_code",
    )
    for field in fields:
        if field in latest:
            print(f"{field:20} {latest[field]}")
    if latest.get("_timestamp"):
        print(f"{'log_timestamp':20} {latest['_timestamp']}")
        try:
            timestamp = datetime.fromisoformat(
                str(latest["_timestamp"]).replace("Z", "+00:00")
            )
            age = max(0, int((datetime.now(UTC) - timestamp.astimezone(UTC)).total_seconds()))
            print(f"{'heartbeat_age':20} {age}s")
        except ValueError:
            pass

    stage_descriptions = {
        "temporal_projection": (
            "Loading retained exposure observations, filtering them to the "
            "source projection time, and materializing current/history/SLA tables. "
            "This implementation emits no row-level counter until completion."
        ),
        "container_projection": (
            "Materializing digest-qualified container exposure and workload impact."
        ),
        "ontology_construction": (
            "Building ontology entities and relationships from mapped datasets."
        ),
        "table_publication": (
            "Writing mapped Bronze/Silver/Gold tables to Fabric Delta storage."
        ),
        "checkpoint_persistence": (
            "Persisting integrity-bound prepared projection artifacts for exact replay."
        ),
        "checkpoint_restore": (
            "Restoring and verifying prepared projection artifacts for exact replay."
        ),
        "publication_resume": (
            "Validating persisted Delta versions and skipping only unchanged completed tables."
        ),
        "checkpoint_finalization": (
            "Recording the terminal publication result after pointer activation."
        ),
        "gold_staging": (
            "Staging and validating generation-pinned Exposure Gold tables."
        ),
        "pointer_activation": (
            "Activating the validated Exposure generation pointer."
        ),
    }
    description = stage_descriptions.get(str(latest.get("stage") or ""))
    if description:
        print(f"{'stage_detail':20} {description}")

    stage_states = {}
    for event in events:
        stage_states[str(event.get("stage") or "unknown")] = event
    table_event = next(
        (
            event
            for event in reversed(events)
            if event.get("stage") == "table_publication"
            and event.get("completed") is not None
            and event.get("total") is not None
        ),
        None,
    )
    try:
        with open(table_state_path, encoding="utf-8") as stream:
            saved_table_event = json.load(stream)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        saved_table_event = None
    if saved_table_event and (
        not table_event
        or int(saved_table_event.get("completed") or 0)
        > int(table_event.get("completed") or 0)
    ):
        table_event = saved_table_event
    if table_event:
        with open(table_state_path, "w", encoding="utf-8") as stream:
            json.dump(table_event, stream, sort_keys=True)
    if table_event:
        completed = int(table_event.get("completed") or 0)
        total = int(table_event.get("total") or 0)
        remaining = max(0, total - completed)
        percent = completed / total * 100 if total else 0.0
        print("\nTable publication progress")
        print("--------------------------")
        print(f"{'tables completed':20} {completed}")
        print(f"{'tables total':20} {total}")
        print(f"{'tables remaining':20} {remaining}")
        print(f"{'percent complete':20} {percent:.1f}%")
        print(f"{'latest table':20} {table_event.get('table_name') or '-'}")
        print(f"{'latest table rows':20} {table_event.get('row_count', '-')}")

    print("\nStage summary")
    print("-------------")
    for stage, event in stage_states.items():
        elapsed = event.get("elapsed_seconds")
        detail = []
        if event.get("completed") is not None or event.get("total") is not None:
            detail.append(f"{event.get('completed', '?')}/{event.get('total', '?')}")
        if event.get("dataset_count") is not None:
            detail.append(f"datasets={event['dataset_count']}")
        if event.get("checkpoint_rows_written") is not None:
            detail.append(f"rows={event['checkpoint_rows_written']}")
        if event.get("checkpoint_bytes_written") is not None:
            detail.append(f"bytes={event['checkpoint_bytes_written']}")
        if event.get("failure_count") is not None:
            detail.append(f"failures={event['failure_count']}")
        suffix = f" ({', '.join(detail)})" if detail else ""
        print(
            f"{stage:28} {str(event.get('status') or ''):10} "
            f"elapsed={elapsed}s{suffix}"
        )

    counts = Counter(str(event.get("status") or "") for event in events)
    print(
        "\nObserved progress events: "
        + ", ".join(f"{key or 'unknown'}={value}" for key, value in sorted(counts.items()))
    )
else:
    print("\nNo structured activation_progress records are available yet.")

print("\nRecent warnings/errors")
print("----------------------")
if diagnostics:
    for timestamp, message in diagnostics[-8:]:
        prefix = f"{timestamp} " if timestamp else ""
        print(prefix + message[:500])
else:
    print("None in inspected log tail.")
PY
}

refresh_checkpoint_state() {
  local workspace_id="$1"
  local execution_name="$2"
  local state_file="$3"
  local query_file="$WORK_DIR/checkpoint-query.json"
  [ -n "$workspace_id" ] || return 0

  if ! az monitor log-analytics query \
      --workspace "$workspace_id" \
      --analytics-query "ContainerAppConsoleLogs_CL | where TimeGenerated > ago(6h) | where ContainerGroupName_s contains '$execution_name' | where Log_s contains '\"checkpoint_id\"' | top 1 by TimeGenerated desc | project Log_s" \
      --output json >"$query_file" 2>/dev/null; then
    availability_notice "checkpoint"
    return 0
  fi

  if ! python3 - "$query_file" "$state_file" <<'PY'
import json
import sys

query_path, state_path = sys.argv[1:]
try:
    rows = json.load(open(query_path))
    if not rows:
        raise SystemExit(0)
    event = json.loads(rows[0]["Log_s"])
except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)
with open(state_path, "w", encoding="utf-8") as stream:
    json.dump(event, stream, sort_keys=True)
PY
  then
    availability_notice "checkpoint"
    return 0
  fi
  rm -f "$WORK_DIR/checkpoint-query-unavailable"
}

render_checkpoint_state() {
  local state_file="$1"
  python3 - "$state_file" <<'PY'
import json
import sys

try:
    event = json.load(open(sys.argv[1]))
except (FileNotFoundError, OSError, json.JSONDecodeError):
    raise SystemExit

print("\nPublication checkpoint")
print("----------------------")
for field, label in (
    ("checkpoint_id", "checkpoint"),
    ("checkpoint_state", "state"),
    ("checkpoint_rows_written", "rows persisted"),
    ("checkpoint_bytes_written", "bytes persisted"),
    ("publication_id", "publication"),
    ("current_phase", "current phase"),
    ("resumed_tables", "resumed tables"),
    ("skipped_tables", "skipped tables"),
    ("completed", "tables completed"),
    ("total", "tables total"),
    ("remaining_tables", "tables remaining"),
):
    if event.get(field) is not None:
        print(f"{label:20} {event[field]}")
PY
}

refresh_table_state() {
  local workspace_id="$1"
  local execution_name="$2"
  local state_file="$3"
  local query_file="$WORK_DIR/table-query.json"
  [ -n "$workspace_id" ] || return 0

  if ! az monitor log-analytics query \
      --workspace "$workspace_id" \
      --analytics-query "ContainerAppConsoleLogs_CL | where TimeGenerated > ago(3h) | where ContainerGroupName_s contains '$execution_name' | where Log_s contains '\"stage\":\"table_publication\"' and Log_s contains '\"completed\":' | top 1 by TimeGenerated desc | project Log_s" \
      --output json >"$query_file" 2>/dev/null; then
    availability_notice "table"
    return 0
  fi

  if ! python3 - "$query_file" "$state_file" <<'PY'
import json
import sys

query_path, state_path = sys.argv[1:]
try:
    rows = json.load(open(query_path))
    if not rows:
        raise SystemExit(0)
    event = json.loads(rows[0]["Log_s"])
except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)
if event.get("completed") is None or event.get("total") is None:
    raise SystemExit(1)
try:
    saved = json.load(open(state_path))
except (FileNotFoundError, OSError, json.JSONDecodeError):
    saved = {}
if int(event.get("completed") or 0) >= int(saved.get("completed") or 0):
    with open(state_path, "w", encoding="utf-8") as stream:
        json.dump(event, stream, sort_keys=True)
PY
  then
    availability_notice "table"
    return 0
  fi
  rm -f "$WORK_DIR/table-query-unavailable"
}

render_metrics() {
  local metrics_file="$1"
  local allocated_cpu="$2"
  local allocated_memory="$3"
  python3 - "$metrics_file" "$allocated_cpu" "$allocated_memory" <<'PY'
import json
import re
import sys

path, allocated_cpu_text, allocated_memory_text = sys.argv[1:]
try:
    payload = json.load(open(path))
except Exception:
    print("\nLive Azure Monitor metrics\n--------------------------\nUnavailable")
    raise SystemExit

def latest(metric):
    rows = []
    for series in metric.get("timeseries") or []:
        rows.extend(series.get("data") or [])
    rows = [
        row for row in rows
        if any(row.get(field) is not None for field in ("average", "maximum", "total"))
    ]
    return rows[-1] if rows else {}

metrics = {
    str(item.get("name", {}).get("value") or ""): latest(item)
    for item in payload.get("value") or []
}
cpu = metrics.get("UsageNanoCores", {})
memory = metrics.get("UsageBytes", {})
tx = metrics.get("TxBytes", {})
rx = metrics.get("RxBytes", {})

try:
    allocated_cpu = float(allocated_cpu_text)
except ValueError:
    allocated_cpu = 0.0
memory_match = re.fullmatch(r"([0-9.]+)Gi", allocated_memory_text)
allocated_memory = float(memory_match.group(1)) if memory_match else 0.0

cpu_cores = float(cpu.get("average") or 0.0) / 1_000_000_000
memory_gib = float(memory.get("average") or 0.0) / (1024 ** 3)
cpu_percent = cpu_cores / allocated_cpu * 100 if allocated_cpu else 0.0
memory_percent = memory_gib / allocated_memory * 100 if allocated_memory else 0.0
tx_kib = float(tx.get("total") or 0.0) / 1024
rx_kib = float(rx.get("total") or 0.0) / 1024
timestamp = (
    cpu.get("timeStamp")
    or memory.get("timeStamp")
    or tx.get("timeStamp")
    or rx.get("timeStamp")
    or "-"
)

print("\nLive Azure Monitor metrics")
print("--------------------------")
print(f"{'metric_timestamp':20} {timestamp}")
print(f"{'CPU average':20} {cpu_cores:.2f} cores ({cpu_percent:.1f}% of {allocated_cpu:g})")
print(f"{'Memory average':20} {memory_gib:.2f} GiB ({memory_percent:.1f}% of {allocated_memory:g} GiB)")
print(f"{'Network out/min':20} {tx_kib:.1f} KiB")
print(f"{'Network in/min':20} {rx_kib:.1f} KiB")
PY
}

is_terminal() {
  case "$1" in
    Succeeded|Failed|Stopped|Cancelled|Canceled) return 0 ;;
    *) return 1 ;;
  esac
}

if ! EXECUTION_NAME="$(select_execution)"; then
  exit 1
fi
if [ -z "$EXECUTION_NAME" ]; then
  printf 'No publication execution was found for %s.\n' "$JOB_NAME" >&2
  exit 1
fi

while true; do
  execution_file="$WORK_DIR/execution.json"
  job_file="$WORK_DIR/job.json"
  replica_file="$WORK_DIR/replicas.json"
  log_file="$WORK_DIR/logs.jsonl"
  metrics_file="$WORK_DIR/metrics.json"
  table_state_file="$WORK_DIR/table-progress.json"
  checkpoint_state_file="$WORK_DIR/checkpoint-progress.json"

  if ! run_required_az_query \
    "reading job '$JOB_NAME' in resource group '$RESOURCE_GROUP'" \
    az containerapp job show \
      --name "$JOB_NAME" \
      --resource-group "$RESOURCE_GROUP" \
      --output json >"$job_file"; then
    exit 1
  fi
  if ! run_required_az_query \
    "reading execution '$EXECUTION_NAME' for job '$JOB_NAME' in resource group '$RESOURCE_GROUP'" \
    az containerapp job execution show \
      --name "$JOB_NAME" \
      --resource-group "$RESOURCE_GROUP" \
      --job-execution-name "$EXECUTION_NAME" \
      --output json >"$execution_file"; then
    exit 1
  fi
  az containerapp job replica list \
    --name "$JOB_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --execution "$EXECUTION_NAME" \
    --output json >"$replica_file" 2>/dev/null || printf '[]\n' >"$replica_file"

  if ! environment_id="$(
    python3 - "$job_file" <<'PY'
import json
import sys
try:
    job = json.load(open(sys.argv[1]))
    if not isinstance(job, dict):
        raise TypeError("job payload is not an object")
except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
    print(f"Error: malformed job JSON: {exc}", file=sys.stderr)
    raise SystemExit(1)
print((job.get("properties") or {}).get("environmentId") or "")
PY
  )"; then
    exit 1
  fi
  workspace_id=""
  if [ -n "$environment_id" ]; then
    workspace_id="$(
      az resource show \
        --ids "$environment_id" \
        --api-version 2024-03-01 \
        --query properties.appLogsConfiguration.logAnalyticsConfiguration.customerId \
        --output tsv 2>/dev/null || true
    )"
  fi
  refresh_table_state "$workspace_id" "$EXECUTION_NAME" "$table_state_file"
  refresh_checkpoint_state "$workspace_id" "$EXECUTION_NAME" "$checkpoint_state_file"

  details_file="$WORK_DIR/execution-details.txt"
  if ! python3 - "$job_file" "$execution_file" "$replica_file" >"$details_file" <<'PY'
import json
import sys

try:
    job = json.load(open(sys.argv[1]))
    execution = json.load(open(sys.argv[2]))
    replicas = json.load(open(sys.argv[3]))
    if not isinstance(job, dict) or not isinstance(execution, dict):
        raise TypeError("job and execution payloads must be objects")
    if not isinstance(replicas, list):
        raise TypeError("replica payload must be an array")
except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
    print(f"Error: malformed job/execution JSON: {exc}", file=sys.stderr)
    raise SystemExit(1)

job_properties = job.get("properties") or {}
execution_properties = execution.get("properties") or {}
template = execution_properties.get("template") or {}
containers = template.get("containers") or [{}]
container = containers[0] if containers else {}
resources = container.get("resources") or {}
configuration = job_properties.get("configuration") or {}

replica = replicas[0] if replicas else {}
replica_properties = replica.get("properties") or {}
replica_containers = replica_properties.get("containers") or [{}]
replica_container = replica_containers[0] if replica_containers else {}

values = [
    execution_properties.get("status") or "Unknown",
    execution_properties.get("startTime") or "-",
    container.get("image") or "-",
    resources.get("cpu") or "-",
    resources.get("memory") or "-",
    job_properties.get("workloadProfileName") or "-",
    configuration.get("replicaTimeout") or "-",
    replica.get("name") or "-",
    replica_container.get("name") or "-",
    replica_container.get("runningState") or replica_properties.get("runningState") or "-",
    replica_container.get("ready") if "ready" in replica_container else "-",
    replica_container.get("restartCount") if "restartCount" in replica_container else "-",
    replica_properties.get("createdTime") or "-",
]
print(" ".join(str(value).replace(" ", "_") for value in values))
PY
  then
    exit 1
  fi
  if ! read -r status start_time image cpu memory profile timeout replica container \
      container_state ready restart_count created_time <"$details_file"; then
    printf 'Error: Azure job/execution JSON produced no monitorable fields.\n' >&2
    exit 1
  fi

  if [ -t 1 ] && [ -n "${TERM:-}" ]; then
    printf '\033[2J\033[H'
  fi
  printf 'Azure Container Apps publication progress\n'
  printf '=========================================\n'
  printf '%-22s %s\n' 'Refreshed (UTC):' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '%-22s %s\n' 'Resource group:' "$RESOURCE_GROUP"
  printf '%-22s %s\n' 'Job:' "$JOB_NAME"
  printf '%-22s %s\n' 'Execution:' "$EXECUTION_NAME"
  printf '%-22s %s\n' 'Execution status:' "$status"
  printf '%-22s %s\n' 'Started:' "${start_time//_/ }"
  printf '%-22s %s\n' 'Workload profile:' "$profile"
  printf '%-22s %s\n' 'Resources:' "${cpu} CPU / ${memory}"
  printf '%-22s %s seconds\n' 'Replica timeout:' "$timeout"
  printf '%-22s %s\n' 'Image:' "$image"
  printf '%-22s %s\n' 'Replica:' "$replica"
  printf '%-22s %s\n' 'Replica created:' "${created_time//_/ }"
  printf '%-22s %s\n' 'Container:' "$container"
  printf '%-22s %s\n' 'Container state:' "$container_state"
  printf '%-22s %s\n' 'Ready:' "$ready"
  printf '%-22s %s\n' 'Restart count:' "$restart_count"

  : >"$log_file"
  if [ "$replica" != "-" ] && [ "$container" != "-" ]; then
    az containerapp job logs show \
      --name "$JOB_NAME" \
      --resource-group "$RESOURCE_GROUP" \
      --execution "$EXECUTION_NAME" \
      --replica "$replica" \
      --container "$container" \
      --tail "$TAIL_LINES" \
      --format json >"$log_file" 2>/dev/null || true
  fi
  render_logs "$log_file" "$table_state_file"
  render_checkpoint_state "$checkpoint_state_file"

  if ! job_id="$(
    python3 - "$job_file" <<'PY'
import json
import sys
try:
    job = json.load(open(sys.argv[1]))
    if not isinstance(job, dict):
        raise TypeError("job payload is not an object")
except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
    print(f"Error: malformed job JSON: {exc}", file=sys.stderr)
    raise SystemExit(1)
print(job.get("id") or "")
PY
  )"; then
    exit 1
  fi
  : >"$metrics_file"
  if [ -n "$job_id" ]; then
    az monitor metrics list \
      --resource "$job_id" \
      --metrics UsageNanoCores UsageBytes TxBytes RxBytes \
      --interval PT1M \
      --aggregation Average Total \
      --offset 5m \
      --output json >"$metrics_file" 2>/dev/null || true
  fi
  render_metrics "$metrics_file" "$cpu" "$memory"

  if [ "$ONCE" -eq 1 ] || is_terminal "$status"; then
    break
  fi
  printf '\nRefreshing in %s seconds... (Ctrl-C to stop)\n' "$INTERVAL_SECONDS"
  sleep "$INTERVAL_SECONDS"
done
