#!/usr/bin/env bash
# route-task.sh — Маршрутизатор задач IWE (DP.ROLE.059)
# routing: executor=script  deterministic=true
# see DP.SC.159, DP.ROLE.059
#
# Получает routing-tag из WP Gate или Артефактора → lookup в executor-catalog.yaml →
# запускает нужный исполнитель (script | haiku | sonnet | opus | mcp-direct).
#
# Usage:
#   route-task.sh --skill <skill-name> [--args "..."]   # strict: no fallback
#   route-task.sh --tag  <routing-tag>  [--args "..."]   # flex: fallback to Sonnet on miss
#   route-task.sh --list                                 # показать каталог
#   route-task.sh --validate                             # проверить каталог
#
# Exit: 0=OK, 1=error, 2=script_path not found, 3=unknown skill, 4=unsupported executor

set -euo pipefail

IWE_DIR="${IWE_DIR:-$HOME/IWE}"
GOV_REPO="${IWE_GOVERNANCE_REPO:-DS-strategy}"
CATALOG="${IWE_EXECUTOR_CATALOG:-${IWE_DIR}/${GOV_REPO}/scripts/executor-catalog.yaml}"
VALID_EXECUTORS=("script" "haiku" "sonnet" "opus" "mcp-direct")
AUDIT_LOG="${IWE_ROUTER_AUDIT:-${IWE_DIR}/${GOV_REPO}/logs/pilot-audit.tsv}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

die() { echo "ERROR: $*" >&2; exit 1; }
warn() { echo "WARN: $*" >&2; }

require_python() {
    if ! command -v python3 &>/dev/null; then
        die "python3 not found — required for catalog lookup"
    fi
    if ! python3 -c "import yaml" &>/dev/null; then
        die "PyYAML not found — required for catalog lookup (pip install pyyaml)"
    fi
}

require_catalog() {
    if [[ ! -f "$CATALOG" ]]; then
        die "executor-catalog.yaml not found: $CATALOG"
    fi
}

# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

log_audit() {
    local ts="$1" skill="$2" executor="$3" exit_code="$4"
    local audit_dir
    audit_dir="$(dirname "$AUDIT_LOG")"
    [[ -d "$audit_dir" ]] || mkdir -p "$audit_dir"
    printf "%s\t%s\t%s\t%s\n" "$ts" "$skill" "$executor" "$exit_code" >> "$AUDIT_LOG"
}

# ---------------------------------------------------------------------------
# Catalog lookup via Python (reliable YAML parsing)
# ---------------------------------------------------------------------------

lookup_skill() {
    local skill_name="$1"
    require_python
    require_catalog
    python3 - "$CATALOG" "$skill_name" << 'PYEOF'
import sys, yaml

catalog_path, skill_name = sys.argv[1], sys.argv[2]
with open(catalog_path) as f:
    cat = yaml.safe_load(f)

for entry in cat.get("entries", []):
    if entry["name"] == skill_name:
        r = entry["routing"]
        print(f"executor={r['executor']}")
        print(f"deterministic={r.get('deterministic', 'false')}")
        if "script_path" in r:
            print(f"script_path={r['script_path']}")
        if "optimization_priority" in r:
            print(f"optimization_priority={r['optimization_priority']}")
        sys.exit(0)

sys.exit(3)  # not found
PYEOF
}

# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------

run_script() {
    local skill_name="$1"
    local script_path="$2"
    local args="${3:-}"
    local allow_fallback="${4:-true}"

    # Resolve relative path from IWE_DIR
    if [[ "$script_path" != /* ]]; then
        script_path="$IWE_DIR/$script_path"
    fi

    if [[ ! -f "$script_path" ]]; then
        if [[ "$allow_fallback" == "false" ]]; then
            warn "script not found: $script_path (skill=$skill_name)"
            log_audit "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$skill_name" "script" "2"
            exit 2
        fi
        warn "script not found: $script_path (skill=$skill_name)"
        warn "Script may be aspirational (pending Ф12 implementation)."
        warn "Falling back to Haiku LLM executor."
        run_haiku "$skill_name" "$args"
        log_audit "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$skill_name" "haiku" "0"
        return
    fi

    if [[ ! -x "$script_path" ]]; then
        chmod +x "$script_path"
    fi

    echo "[router] skill=$skill_name executor=script path=$script_path"
    local script_exit=0
    if [[ -n "$args" ]]; then
        bash "$script_path" "$args" || script_exit=$?
    else
        bash "$script_path" || script_exit=$?
    fi
    log_audit "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$skill_name" "script" "$script_exit"
    return $script_exit
}

run_llm() {
    local skill_name="$1"
    local model="$2"
    local args="${3:-}"

    echo "[router] skill=$skill_name executor=llm model=$model"
    # Claude Code dispatches to LLM — emit routing directive for the agent
    # Format consumed by Claude Code's skill dispatcher
    echo "ROUTE_TO_LLM skill=$skill_name model=$model args=$args"
}

run_haiku()  { run_llm "$1" "claude-haiku-4-5-20251001" "${2:-}"; }
run_sonnet() { run_llm "$1" "claude-sonnet-4-6"          "${2:-}"; }
run_opus()   { run_llm "$1" "claude-opus-4-7"            "${2:-}"; }

run_mcp_direct() {
    local skill_name="$1"
    local args="${2:-}"
    echo "[router] skill=$skill_name executor=mcp-direct"
    echo "ROUTE_TO_MCP skill=$skill_name args=$args"
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

dispatch_skill() {
    local skill_name="$1"
    local args="${2:-}"
    local allow_fallback="${3:-true}"
    local ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    local lookup_result lookup_exit
    lookup_result=$(lookup_skill "$skill_name") && lookup_exit=0 || lookup_exit=$?
    if [[ $lookup_exit -ne 0 ]]; then
        if [[ $lookup_exit -eq 3 ]]; then
            if [[ "$allow_fallback" == "false" ]]; then
                warn "skill '$skill_name' not in catalog."
                log_audit "$ts" "$skill_name" "unknown" "3"
                exit 3
            fi
            warn "skill '$skill_name' not in catalog. Falling back to Sonnet."
            run_sonnet "$skill_name" "$args"
            log_audit "$ts" "$skill_name" "sonnet" "0"
            return 0
        fi
        die "catalog lookup failed (exit=$lookup_exit)"
    fi

    local executor script_path=""
    executor=$(echo "$lookup_result" | grep "^executor=" | cut -d= -f2)
    script_path=$(echo "$lookup_result" | grep "^script_path=" | cut -d= -f2- || true)

    case "$executor" in
        script)
            run_script "$skill_name" "$script_path" "$args" "$allow_fallback"
            ;;
        haiku)
            run_haiku "$skill_name" "$args"
            log_audit "$ts" "$skill_name" "haiku" "0"
            ;;
        sonnet)
            run_sonnet "$skill_name" "$args"
            log_audit "$ts" "$skill_name" "sonnet" "0"
            ;;
        opus)
            run_opus "$skill_name" "$args"
            log_audit "$ts" "$skill_name" "opus" "0"
            ;;
        mcp-direct)
            run_mcp_direct "$skill_name" "$args"
            log_audit "$ts" "$skill_name" "mcp-direct" "0"
            ;;
        *)
            if [[ "$allow_fallback" == "false" ]]; then
                warn "unknown executor '$executor' for skill '$skill_name'."
                log_audit "$ts" "$skill_name" "unknown" "4"
                exit 4
            fi
            warn "unknown executor '$executor' for skill '$skill_name'. Falling back to Sonnet."
            run_sonnet "$skill_name" "$args"
            log_audit "$ts" "$skill_name" "sonnet" "0"
            ;;
    esac
}

show_list() {
    require_python
    require_catalog
    python3 - "$CATALOG" << 'PYEOF'
import sys, yaml

with open(sys.argv[1]) as f:
    cat = yaml.safe_load(f)

print(f"executor-catalog: {cat['total_entries']} entries  (generated {cat['generated_at']})")
print(f"{'SKILL':<25} {'EXECUTOR':<12} {'DET':<6} SCRIPT_PATH")
print("-" * 80)

by_exec = {}
for e in cat["entries"]:
    ex = e["routing"]["executor"]
    by_exec.setdefault(ex, []).append(e)

for ex in ["script", "haiku", "sonnet", "opus", "mcp-direct"]:
    for e in by_exec.get(ex, []):
        r = e["routing"]
        sp = r.get("script_path", "—")
        det = "✓" if r.get("deterministic") else "✗"
        prio = f" [{r['optimization_priority']}]" if "optimization_priority" in r else ""
        print(f"{e['name']:<25} {ex:<12} {det:<6} {sp}{prio}")
PYEOF
}

validate_catalog() {
    require_python
    require_catalog
    python3 - "$CATALOG" << 'PYEOF'
import sys, yaml

VALID = {"script", "haiku", "sonnet", "opus", "mcp-direct"}
errors = []

with open(sys.argv[1]) as f:
    cat = yaml.safe_load(f)

for e in cat["entries"]:
    r = e["routing"]
    name = e["name"]
    if r.get("executor") not in VALID:
        errors.append(f"{name}: invalid executor '{r.get('executor')}'")
    if "deterministic" not in r:
        errors.append(f"{name}: missing deterministic")
    if r.get("executor") == "script" and "script_path" not in r:
        errors.append(f"{name}: script executor missing script_path")

if errors:
    print("FAIL:")
    for e in errors:
        print(f"  ❌ {e}")
    sys.exit(1)
else:
    print(f"PASS: {cat['total_entries']} entries validated, no errors")
PYEOF
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    local skill_name=""
    local args=""
    local mode="dispatch"
    local allow_fallback="true"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --skill)    skill_name="$2"; allow_fallback="false"; shift 2 ;;
            --tag)      skill_name="$2"; allow_fallback="true";  shift 2 ;;
            --args)     args="$2"; shift 2 ;;
            --list)     mode="list"; shift ;;
            --validate) mode="validate"; shift ;;
            -h|--help)  mode="help"; shift ;;
            *)          die "unknown option: $1" ;;
        esac
    done

    case "$mode" in
        list)     show_list ;;
        validate) validate_catalog ;;
        help)
            grep "^# " "$0" | head -20 | sed 's/^# //'
            ;;
        dispatch)
            [[ -z "$skill_name" && "$allow_fallback" == "false" ]] && die "required: --skill <name>"
            dispatch_skill "$skill_name" "$args" "$allow_fallback"
            ;;
    esac
}

main "$@"
