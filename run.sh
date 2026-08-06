#!/usr/bin/env bash
set -e
set -o pipefail

CLR_RESET="\033[0m"
CLR_DARK_GRAY="\033[90m"
CLR_CYAN="\033[36m"
CLR_GREEN="\033[32m"
CLR_BLUE="\033[34m"
CLR_YELLOW="\033[33m"
CLR_RED="\033[31m"
CLR_MAGENTA="\033[35m"

CONFIG_FILE="/data/options.json"
DATA_DIR="/share/factorio"
CATALOG_RUNTIME_DIR="/tmp/factorio-assistant"
CONFIG_DIR="/config"
TEMPLATE_DIR="/app/factorio-templates"
LOGS_DIR="${DATA_DIR}/logs"
SERVER_SETTINGS="${CONFIG_DIR}/server-settings.json"
MAP_GEN_SETTINGS="${CONFIG_DIR}/map-gen-settings.json"
MAP_SETTINGS="${CONFIG_DIR}/map-settings.json"
SERVER_ADMINLIST="${CONFIG_DIR}/server-adminlist.json"
SERVER_WHITELIST="${CONFIG_DIR}/server-whitelist.json"
SAVES_DIR="${DATA_DIR}/saves"
MODS_DIR="${DATA_DIR}/mods"
SCRIPT_OUTPUT_DIR="${DATA_DIR}/script-output"
DATA_OUTPUT_DIR="${CATALOG_RUNTIME_DIR}"
RUNTIME_DIR="${CONFIG_DIR}/runtime"
LOG_FILE="${LOGS_DIR}/factorio-current.log"
RCON_PORT=27015
GAME_PORT=34197
REST_API_PORT=8100
FACTORIO_VERSION="2.0.77"
FACTORIO_BINARY="/opt/factorio/bin/x64/factorio"

LOG_LEVEL="info"
API_TOKEN=""
if [ -f "$CONFIG_FILE" ]; then
    LOG_LEVEL=$(jq -r '.log_level // "info"' "$CONFIG_FILE" | tr '[:upper:]' '[:lower:]')
    API_TOKEN=$(jq -r '.api_token // ""' "$CONFIG_FILE")
fi

case "$LOG_LEVEL" in
    trace|debug|info|notice|warning|error|fatal) ;;
    *)
        log_level_value="$LOG_LEVEL"
        LOG_LEVEL="info"
        ;;
esac

log_msg() {
    # Emit a colorized log line for startup and runtime diagnostics.
    local level="$1"
    local message="$2"
    local source="${3:-Factorio Assistant}"
    local color="$CLR_RESET"

    case "$LOG_LEVEL" in
        trace)       minimum=0 ;;
        debug)       minimum=1 ;;
        info)        minimum=2 ;;
        notice)      minimum=3 ;;
        warning)     minimum=4 ;;
        error)       minimum=5 ;;
        fatal)       minimum=6 ;;
        *)           minimum=2 ;;
    esac
    case "$level" in
        TRACE)    current=0 ;;
        DEBUG)    current=1 ;;
        INFO)     current=2 ;;
        NOTICE)   current=3 ;;
        WARNING)  current=4 ;;
        ERROR)    current=5 ;;
        FATAL)    current=6 ;;
        CRITICAL) current=6 ;;
        *)        current=2 ;;
    esac
    [ "$current" -lt "$minimum" ] && return 0

    case "$level" in
        TRACE)    color="$CLR_DARK_GRAY" ;;
        DEBUG)    color="$CLR_CYAN" ;;
        INFO)     color="$CLR_GREEN" ;;
        NOTICE)   color="$CLR_BLUE" ;;
        WARNING)  color="$CLR_YELLOW" ;;
        ERROR)    color="$CLR_RED" ;;
        FATAL|CRITICAL) color="$CLR_MAGENTA" ;;
    esac

    echo -e "${color}[${level}]${CLR_RESET} $(date +'%H:%M:%S') [${source}] - ${message}"
}

log_debug() { log_msg "DEBUG" "$1" "Factorio Assistant"; }
log_info()  { log_msg "INFO" "$1" "Factorio Assistant"; }
log_notice() { log_msg "NOTICE" "$1" "Factorio Assistant"; }
log_warn()  { log_msg "WARNING" "$1" "Factorio Assistant"; }
log_error() { log_msg "ERROR" "$1" "Factorio Assistant"; }
log_fatal() { log_msg "FATAL" "$1" "Factorio Assistant"; }
log_factorio_debug() { log_msg "DEBUG" "$1" "Factorio Assistant] [Factorio Executable"; }
log_factorio_info() { log_msg "INFO" "$1" "Factorio Assistant] [Factorio Executable"; }
log_factorio_notice() { log_msg "NOTICE" "$1" "Factorio Assistant] [Factorio Executable"; }
log_factorio_warn() { log_msg "WARNING" "$1" "Factorio Assistant] [Factorio Executable"; }
log_factorio_error() { log_msg "ERROR" "$1" "Factorio Assistant] [Factorio Executable"; }
log_factorio_fatal() { log_msg "FATAL" "$1" "Factorio Assistant] [Factorio Executable"; }
log_component() { log_msg "$1" "$2" "Factorio Assistant] [$3"; }

format_factorio_output() {
    python3 -u -c 'import re, sys
record_start = re.compile(r"(?<!\d)(?:\d+\.\d{3}\s+(?:Trace|Debug|Info|Notice|Warning|Error|Fatal)\s+[^:\r\n]+:\d+:|\d+\.\d{3}\s+Goodbye\b)")
buffer = ""
def emit_complete_records(final=False):
    global buffer
    matches = list(record_start.finditer(buffer))
    if not matches:
        if final:
            buffer = ""
        return
    first = matches[0].start()
    if first:
        buffer = buffer[first:]
        matches = list(record_start.finditer(buffer))
    end = len(matches) if final else max(0, len(matches) - 1)
    for index in range(end):
        start = matches[index].start()
        stop = matches[index + 1].start() if index + 1 < len(matches) else len(buffer)
        parts = [part.strip() for part in buffer[start:stop].splitlines() if part.strip() and not part.strip().isdigit()]
        line = " ".join(parts)
        if line:
            print(line, flush=True)
    if end:
        buffer = buffer[matches[end].start():] if end < len(matches) else ""
while True:
    chunk = sys.stdin.buffer.read1(4096)
    if not chunk:
        break
    buffer += chunk.decode("utf-8", errors="replace")
    emit_complete_records()
emit_complete_records(final=True)'
}

forward_factorio_output() {
    local component="${1:-Factorio Executable}"
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            *" Trace "*) log_component "DEBUG" "${line#* Trace }" "$component" ;;
            *" Debug "*) log_component "DEBUG" "${line#* Debug }" "$component" ;;
            *" Info "*) log_component "INFO" "${line#* Info }" "$component" ;;
            *" Notice "*) log_component "NOTICE" "${line#* Notice }" "$component" ;;
            *" Warning "*) log_component "WARNING" "${line#* Warning }" "$component" ;;
            *" Error "*) log_component "ERROR" "${line#* Error }" "$component" ;;
            *" Fatal "*) log_component "FATAL" "${line#* Fatal }" "$component" ;;
            ''|*[!0-9]*) log_component "INFO" "$line" "$component" ;;
            *) log_component "DEBUG" "Ignoring numeric Factorio output fragment: $line" "$component" ;;
        esac
    done
}

if [ -n "${log_level_value:-}" ]; then
    log_warn "Unknown log level '${log_level_value}'; defaulting to info"
fi

# Initialize the container runtime and prepare persistent storage for the server.
log_info "Initializing Factorio Assistant container..."
log_debug "Container startup script launched with log level ${LOG_LEVEL}"

mkdir -p "${CONFIG_DIR}" "${LOGS_DIR}" "${SAVES_DIR}" \
    "${MODS_DIR}" "${SCRIPT_OUTPUT_DIR}"
mkdir -p "${DATA_OUTPUT_DIR}" "${RUNTIME_DIR}"
PLAYER_PROFILES_PATH="${CONFIG_DIR}/player_profiles.json"

install_factorio_template() {
    local active_path="$1"
    local template_name="$2"
    local template_path="${TEMPLATE_DIR}/${template_name}"
    if [ ! -f "${template_path}" ]; then
        log_fatal "Factorio default template was not found: ${template_name}"
        exit 1
    fi
    if [ ! -f "${active_path}" ]; then
        cp "${template_path}" "${active_path}"
        log_info "Created Factorio configuration ${active_path}"
    fi
}

install_factorio_template "${SERVER_SETTINGS}" "server-settings.example.json"
install_factorio_template "${MAP_GEN_SETTINGS}" "map-gen-settings.example.json"
install_factorio_template "${MAP_SETTINGS}" "map-settings.example.json"
install_factorio_template "${SERVER_ADMINLIST}" "server-adminlist.example.json"
install_factorio_template "${SERVER_WHITELIST}" "server-whitelist.example.json"
if [ ! -f "${SERVER_ADMINLIST}" ]; then
    printf "[]\n" > "${SERVER_ADMINLIST}"
    log_info "Created empty Factorio admin list ${SERVER_ADMINLIST}"
fi
rm -f "${RUNTIME_DIR}/web.pid" "${RUNTIME_DIR}/web-api.pid" "${RUNTIME_DIR}/bridge.pid" "${RUNTIME_DIR}/factorio.pid"
log_debug "Ensured organized data directories exist under ${DATA_DIR}"
log_debug "Using config directory ${CONFIG_DIR} and script output ${SCRIPT_OUTPUT_DIR}"

# Apply the custom Factorio config-path override so persistent storage resolves correctly.
if [ -f "/etc/factorio/config-path.cfg" ]; then
    log_debug "Applying custom config-path override for Factorio runtime"
    mkdir -p /opt/factorio/bin/x64
    cp /etc/factorio/config-path.cfg /opt/factorio/bin/x64/config-path.cfg
fi

mkdir -p /opt/factorio && ln -sfn "${SCRIPT_OUTPUT_DIR}" /opt/factorio/script-output
mkdir -p /factorio && ln -sfn "${SCRIPT_OUTPUT_DIR}" /factorio/script-output

# Load add-on configuration from Home Assistant options and normalize the values for runtime use.
if [ -f "$CONFIG_FILE" ]; then
    log_debug "Loading Home Assistant add-on options from ${CONFIG_FILE}"
    log_notice "Loaded Home Assistant add-on configuration values for server startup"
    FACTORIO_USER=$(jq -r '.factorio_user // .factorio_username // empty' "$CONFIG_FILE")
    FACTORIO_TOKEN=$(jq -r '.factorio_token // .factorio_service_token // empty' "$CONFIG_FILE")
    SAVE_NAME=$(jq -r '.save_name // "world.zip"' "$CONFIG_FILE")
    ENABLE_MOD_UPDATES_RAW=$(jq -r '.enable_mod_updates // .options.enable_mod_updates // "false"' "$CONFIG_FILE" | tr '[:upper:]' '[:lower:]')
    ENABLE_TELEMETRY_MOD_RAW=$(jq -r '.enable_telemetry_mod // false' "$CONFIG_FILE" | tr '[:upper:]' '[:lower:]')
    case "$ENABLE_MOD_UPDATES_RAW" in
        true|1|yes|on)
            ENABLE_MOD_UPDATES="true"
            ;;
        *)
            ENABLE_MOD_UPDATES="false"
            ;;
    esac
    GAME_PORT=$(jq -r '.server_port // 34197' "$CONFIG_FILE")
    RCON_PORT=$(jq -r '.rcon_port // 27015' "$CONFIG_FILE")
    REST_API_PORT=$(jq -r '.rest_api_port // 8100' "$CONFIG_FILE")
else
    FACTORIO_USER=""
    FACTORIO_TOKEN=""
    SAVE_NAME="world.zip"
    ENABLE_MOD_UPDATES="false"
    ENABLE_TELEMETRY_MOD_RAW="false"
    GAME_PORT=34197
    RCON_PORT=27015
    REST_API_PORT=8100
fi

case "$ENABLE_TELEMETRY_MOD_RAW" in
    true|1|yes|on) ENABLE_TELEMETRY_MOD="true" ;;
    *) ENABLE_TELEMETRY_MOD="false" ;;
esac

if [ -d "/app/factorio_assistant" ]; then
    ENABLE_TELEMETRY_MOD="${ENABLE_TELEMETRY_MOD}" python3 - <<'PY'
import json
import os

path = "/share/factorio/mods/mod-list.json"
name = "factorio_assistant"
enabled = os.environ.get("ENABLE_TELEMETRY_MOD") == "true"
try:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
except FileNotFoundError:
    data = {"mods": []}
except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
    raise SystemExit(f"Could not read {path} without risking other mod entries: {exc}")

if not isinstance(data, dict) or not isinstance(data.get("mods", []), list):
    raise SystemExit(f"Could not update {path} without risking other mod entries: invalid mod list")
mods = data["mods"]

entry = next((item for item in mods if isinstance(item, dict) and item.get("name") == name), None)
if entry is None:
    mods.append({"name": name, "enabled": enabled})
else:
    entry["enabled"] = enabled

temporary_path = f"{path}.tmp"
with open(temporary_path, "w", encoding="utf-8") as handle:
    json.dump(data, handle, indent=2)
os.replace(temporary_path, path)
PY
    log_info "Factorio Assistant mod registered for Mod Portal retrieval (enabled=${ENABLE_TELEMETRY_MOD})"
fi

validate_port() {
    local name="$1"
    local value="$2"
    case "$value" in
        ''|*[!0-9]*)
            log_fatal "${name} must be a TCP or UDP port number between 1 and 65535"
            exit 1
            ;;
    esac
    if [ "$value" -lt 1 ] || [ "$value" -gt 65535 ]; then
        log_fatal "${name} must be a TCP or UDP port number between 1 and 65535"
        exit 1
    fi
}

validate_port "server_port" "$GAME_PORT"
validate_port "rcon_port" "$RCON_PORT"
validate_port "rest_api_port" "$REST_API_PORT"

# Reuse the configured API token for RCON when available. Otherwise generate a
# process-local password so all services share RCON credentials without
# persisting a secret in the SMB-visible data directory.
if [ -n "$API_TOKEN" ]; then
    RCON_PASS="$API_TOKEN"
    log_info "Using the configured API token for RCON authentication"
else
    log_info "Generating a new in-memory RCON password"
    RCON_PASS=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
fi

export LOG_LEVEL
export CONFIG_DIR
export RCON_PASS
export FACTORIO_API_TOKEN="$API_TOKEN"
export FACTORIO_USER
export FACTORIO_TOKEN
export ENABLE_MOD_UPDATES
export ENABLE_TELEMETRY_MOD
export RCON_PORT
export GAME_PORT
export REST_API_PORT
export FACTORIO_RUNTIME_DIR="${RUNTIME_DIR}"
export FACTORIO_CATALOG_DIR="${DATA_OUTPUT_DIR}"
export FACTORIO_PLAYER_PROFILES_PATH="${PLAYER_PROFILES_PATH}"

# Respect enable_mod_updates setting explicitly
# Sync enabled mods from the Factorio Mod Portal when the add-on is configured to do so.
if [ "$ENABLE_MOD_UPDATES" = "true" ]; then
    log_info "Initiating Mod Portal auto-update synchronization for current game version..."
    python3 - << 'EOF'
import json, os, sys, subprocess, urllib.request, urllib.parse, logging
from concurrent.futures import ThreadPoolExecutor, as_completed

log_level_name = os.environ.get("LOG_LEVEL", "info").strip().lower()
if log_level_name == "trace":
    log_level_name = "debug"
python_log_level = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "notice": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "fatal": logging.CRITICAL,
}.get(log_level_name, logging.INFO)

logging.basicConfig(level=python_log_level, format="[%(levelname)s] %(asctime)s [ModSync] - %(message)s", datefmt="%H:%M:%S")

user = os.environ.get("FACTORIO_USER", "").strip()
token = os.environ.get("FACTORIO_TOKEN", "").strip()

if not user or not token:
    logging.info("Mod sync skipped: missing Factorio Mod Portal credentials.")
    sys.exit(0)
logging.debug("Mod Portal credentials found; preparing authenticated requests")

game_version = "2.0"
try:
    output = subprocess.check_output(["/opt/factorio/bin/x64/factorio", "--version"], universal_newlines=True)
    for line in output.splitlines():
        if "Version:" in line:
            parts = line.split("Version:")[1].strip().split(".")
            if len(parts) >= 2:
                game_version = f"{parts[0]}.{parts[1]}"
                break
except Exception:
    logging.debug("Could not detect Factorio binary version; defaulting compatibility to %s", game_version)
    pass

logging.debug("Running mod sync with compatibility target Factorio %s", game_version)
logging.info("Mod sync compatibility target: Factorio %s", game_version)

class AuthenticatedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed_new = urllib.parse.urlparse(newurl)
        params = urllib.parse.parse_qs(parsed_new.query)
        params["username"] = [user]
        params["token"] = [token]
        new_query = urllib.parse.urlencode(params, doseq=True)
        return urllib.request.Request(
            urllib.parse.urlunparse((
                parsed_new.scheme, parsed_new.netloc, parsed_new.path,
                parsed_new.params, new_query, parsed_new.fragment
            )),
            headers=req.headers
        )

opener = urllib.request.build_opener(AuthenticatedRedirectHandler)
opener.addheaders = [("User-Agent", "Home Assistant Factorio Integration/4.2")]
urllib.request.install_opener(opener)
logging.debug("Configured Mod Portal request opener and redirect authentication")

mod_list_path = "/share/factorio/mods/mod-list.json"
if not os.path.exists(mod_list_path):
    logging.info("Mod sync skipped: %s not found.", mod_list_path)
    sys.exit(0)

mod_dir = os.path.dirname(mod_list_path)
MOD_API_TIMEOUT = 20
MOD_DOWNLOAD_TIMEOUT = 120
MOD_METADATA_WORKERS = 4
CORE_MODS = {"base", "space-age", "quality", "elevated-rails"}

try:
    with open(mod_list_path, "r") as f:
        mod_data = json.load(f)
        mods = mod_data.get("mods", [])
    logging.info("Loaded %d mod entries from %s", len(mods), mod_list_path)
except Exception as exc:
    logging.error("Failed to parse %s: %s", mod_list_path, exc)
    sys.exit(1)

def compatible_release(name):
    try:
        encoded_name = urllib.parse.quote(name)
        req = urllib.request.Request(f"https://mods.factorio.com/api/mods/{encoded_name}")
        logging.debug("Requesting release metadata for %s (timeout %ss)", name, MOD_API_TIMEOUT)
        with urllib.request.urlopen(req, timeout=MOD_API_TIMEOUT) as resp:
            releases = json.loads(resp.read().decode("utf-8")).get("releases", [])
            logging.debug("Received %d releases for %s", len(releases), name)
            if not releases:
                logging.debug("No releases returned by Mod Portal for %s", name)
                return name, None
            compatible_releases = []
            for rel in releases:
                info = rel.get("info_json", {})
                f_ver = info.get("factorio_version", "0.12")
                if (
                    f_ver == game_version
                    or f_ver.startswith(game_version + ".")
                    or game_version.startswith(f_ver + ".")
                ):
                    compatible_releases.append(rel)
            if not compatible_releases:
                logging.debug("No compatible releases for %s (target %s)", name, game_version)
                return name, None
            latest = compatible_releases[-1]
            logging.debug("Selected compatible release %s for %s", latest.get("file_name", "unknown"), name)
            return name, latest
    except Exception as exc:
        logging.warning("Failed to process update check for %s: %s", name, exc)
        logging.debug("Continuing mod sync after failure for %s", name, exc_info=True)
        return name, None

enabled_mod_names = []
for mod in mods:
    name = mod.get("name")
    if not mod.get("enabled", True):
        logging.debug("Skipping disabled mod %s", name)
    elif name in CORE_MODS:
        logging.debug("Skipping core mod %s", name)
    elif name:
        enabled_mod_names.append(name)

metadata_results = []
worker_count = min(MOD_METADATA_WORKERS, max(1, len(enabled_mod_names)))
logging.info("Checking metadata for %d mods with %d concurrent workers", len(enabled_mod_names), worker_count)
with ThreadPoolExecutor(max_workers=worker_count) as executor:
    futures = [executor.submit(compatible_release, name) for name in enabled_mod_names]
    for future in as_completed(futures):
        metadata_results.append(future.result())

mod_list_modified = False
for name, latest in sorted(metadata_results, key=lambda result: enabled_mod_names.index(result[0])):
    if latest is None:
        continue
    file_name = latest["file_name"]
    target_path = os.path.join(mod_dir, file_name)
    if os.path.exists(target_path):
        logging.debug("%s is already up to date (%s present)", name, file_name)
        continue

    base_dl_url = f"https://mods.factorio.com{latest['download_url']}"
    parsed_dl = urllib.parse.urlparse(base_dl_url)
    query_params = urllib.parse.parse_qs(parsed_dl.query)
    query_params["username"] = [user]
    query_params["token"] = [token]
    new_query = urllib.parse.urlencode(query_params, doseq=True)
    dl_url = urllib.parse.urlunparse((
        parsed_dl.scheme, parsed_dl.netloc, parsed_dl.path,
        parsed_dl.params, new_query, parsed_dl.fragment
    ))

    try:
        logging.info("Downloading update for %s -> %s", name, file_name)
        logging.debug("Mod download timeout for %s is %ss", name, MOD_DOWNLOAD_TIMEOUT)
        with urllib.request.urlopen(urllib.request.Request(dl_url), timeout=MOD_DOWNLOAD_TIMEOUT) as dl_resp, open(target_path, "wb") as out:
            out.write(dl_resp.read())
        logging.info("Downloaded update for %s -> %s", name, file_name)
        for mod in mods:
            if mod.get("name") == name:
                mod["enabled"] = True
                break
        mod_list_modified = True
    except Exception as exc:
        logging.warning("Failed to download update for %s: %s", name, exc)
        logging.debug("Continuing mod sync after download failure for %s", name, exc_info=True)

if mod_list_modified:
    logging.info("Writing updated mod list after downloads")
    mod_data["mods"] = mods
    with open(mod_list_path, "w") as f:
        json.dump(mod_data, f, indent=2)
    logging.info("Updated mod-list.json after syncing mod updates.")
else:
    logging.info("No compatible mod updates were downloaded.")
logging.info("Mod Portal synchronization complete")
EOF
else
    log_info "Mod updates are disabled in configuration. Skipping Mod Portal sync."
fi
log_debug "Mod synchronization phase complete; continuing with save validation"

# Create the initial world from the editable map settings when the configured save does not exist.
if [ -z "${SAVE_NAME}" ] || [ "${SAVE_NAME}" = "null" ]; then
    log_fatal "The save_name configuration must contain a filename."
    exit 1
fi
case "${SAVE_NAME}" in
    */*|*\\*)
        log_fatal "save_name must be a filename in ${SAVES_DIR}, not a path: ${SAVE_NAME}"
        exit 1
        ;;
esac
SAVE_PATH="${SAVES_DIR}/${SAVE_NAME}"
if [ ! -f "${SAVE_PATH}" ]; then
    log_info "No save found; creating ${SAVE_PATH} from the persistent map settings"
    if ! "${FACTORIO_BINARY}" --create "${SAVE_PATH}" \
        --map-gen-settings "${MAP_GEN_SETTINGS}" \
        --map-settings "${MAP_SETTINGS}" \
        --mod-directory "${MODS_DIR}" \
        > "${LOGS_DIR}/world-create.log" 2>&1; then
        log_fatal "Factorio could not create the initial world; see ${LOGS_DIR}/world-create.log"
        exit 1
    fi
fi
log_debug "Using save file at ${SAVE_PATH}"

# Refresh the read-only catalog from Factorio's boot data dump for REST searches.
CATALOG_PATH="${DATA_OUTPUT_DIR}/catalog.json"
rm -f "${CATALOG_PATH}"
log_info "Generating searchable game-data catalog"
if "${FACTORIO_BINARY}" --dump-data --mod-directory "${MODS_DIR}" > "${LOGS_DIR}/catalog-dump.log" 2>&1; then
    if ! "${FACTORIO_BINARY}" --dump-prototype-locale --mod-directory "${MODS_DIR}" >> "${LOGS_DIR}/catalog-dump.log" 2>&1; then
        log_warn "Factorio prototype locale dump failed; catalog will use available localization data"
    fi
    if python3 -u /app/catalog_builder.py; then
        log_notice "Searchable game-data catalog is ready at ${CATALOG_PATH}"
    else
        log_warn "Factorio data dump completed, but no readable JSON dump was found under ${SCRIPT_OUTPUT_DIR}"
        log_warn "Unable to parse the Factorio data dump; /api/catalog will remain unavailable"
    fi
else
    log_warn "Factorio data dump failed; /api/catalog will remain unavailable"
fi

# Stop the server and bridge gracefully on container shutdown.
wait_for_process() {
    local pid="$1"
    local name="$2"
    local timeout_seconds="${3:-10}"
    local deadline=$((SECONDS + timeout_seconds))

    while kill -0 "$pid" 2>/dev/null; do
        if [ "$SECONDS" -ge "$deadline" ]; then
            log_warn "${name} did not stop within ${timeout_seconds}s; sending SIGKILL"
            kill -KILL "$pid" 2>/dev/null || true
            break
        fi
        sleep 0.2
    done
    wait "$pid" 2>/dev/null || true
}

request_stop() {
    local pid="$1"
    local name="$2"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        log_debug "Stopping ${name} process with PID ${pid}..."
        kill -TERM "$pid" 2>/dev/null || true
    fi
}

stop_server() {
    trap - SIGTERM SIGINT
    log_info "Stopping Factorio, bridge, and web processes..."
    request_stop "${FACTORIO_PID:-}" "Factorio"
    request_stop "${BRIDGE_PID:-}" "RCON bridge"
    request_stop "${WEB_PID:-}" "web console"
    request_stop "${WEB_API_PID:-}" "REST API"
    wait_for_process "${FACTORIO_PID:-}" "Factorio" 8
    wait_for_process "${BRIDGE_PID:-}" "RCON bridge" 5
    wait_for_process "${WEB_PID:-}" "web console" 5
    wait_for_process "${WEB_API_PID:-}" "REST API" 5
    exit 0
}
trap 'stop_server' SIGTERM SIGINT

# Start the ingress console and separate REST API before the game.
FACTORIO_BINARY="${FACTORIO_BINARY}" WEB_ROLE=ui WEB_PORT=8099 python3 -u /app/web_server.py &
WEB_PID=$!
printf '%s\n' "${WEB_PID}" > "${RUNTIME_DIR}/web.pid"
log_info "Started web console process with PID ${WEB_PID} on ingress port 8099"
log_debug "Web console is running independently while Factorio startup proceeds"
FACTORIO_BINARY="${FACTORIO_BINARY}" WEB_ROLE=api WEB_PORT="${REST_API_PORT}" python3 -u /app/web_server.py &
WEB_API_PID=$!
printf '%s\n' "${WEB_API_PID}" > "${RUNTIME_DIR}/web-api.pid"
log_info "Started REST API process with PID ${WEB_API_PID} on port ${REST_API_PORT}"

# Start the RCON bridge first so it can observe the server process from startup onward.
python3 -u /app/factorio-assistant-service.py &
BRIDGE_PID=$!
printf '%s\n' "${BRIDGE_PID}" > "${RUNTIME_DIR}/bridge.pid"
log_info "Started RCON bridge process with PID ${BRIDGE_PID}"
log_debug "RCON bridge startup sequence has begun"

# Launch the headless Factorio server with persisted config and logging.
log_info "Starting Factorio headless server instance..."
log_debug "Launching Factorio with game port ${GAME_PORT}, RCON port ${RCON_PORT}, and save ${SAVE_PATH}"
/opt/factorio/bin/x64/factorio \
  --start-server "${SAVE_PATH}" \
  --server-settings "${SERVER_SETTINGS}" \
    --server-adminlist "${SERVER_ADMINLIST}" \
    --server-whitelist "${SERVER_WHITELIST}" \
        --use-server-whitelist \
  --port "${GAME_PORT}" \
  --rcon-port "${RCON_PORT}" \
  --rcon-password "${RCON_PASS}" \
  --mod-directory "${MODS_DIR}" \
    --console-log "${LOG_FILE}" \
    > >(format_factorio_output | forward_factorio_output) 2>&1 &

FACTORIO_PID=$!
printf '%s\n' "${FACTORIO_PID}" > "${RUNTIME_DIR}/factorio.pid"
log_notice "Factorio process started with PID ${FACTORIO_PID}"
log_debug "Main process is waiting for Factorio PID ${FACTORIO_PID}; bridge watchdog remains active in PID ${BRIDGE_PID}"
set +e
wait "$FACTORIO_PID"
FACTORIO_EXIT_CODE=$?
set -e
if [ "$FACTORIO_EXIT_CODE" -eq 0 ]; then
    log_notice "Factorio process exited normally with code 0"
else
    log_fatal "Factorio process exited unexpectedly with code ${FACTORIO_EXIT_CODE}"
fi

request_stop "${BRIDGE_PID:-}" "RCON bridge"
request_stop "${WEB_PID:-}" "web console"
request_stop "${WEB_API_PID:-}" "REST API"
wait_for_process "${BRIDGE_PID:-}" "RCON bridge" 5
wait_for_process "${WEB_PID:-}" "web console" 5
wait_for_process "${WEB_API_PID:-}" "REST API" 5
exit "$FACTORIO_EXIT_CODE"