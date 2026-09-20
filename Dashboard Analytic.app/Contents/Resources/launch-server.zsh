#!/bin/zsh

# Opening the app starts the local Dashboard Analytic server. Quitting the
# application sends a signal to this process and stops the server cleanly.
set -u
launcher_pid="$PPID"

show_message() {
    /usr/bin/osascript - "$1" "$2" <<'APPLESCRIPT'
on run argv
    display dialog (item 2 of argv) with title (item 1 of argv) buttons {"OK"} default button "OK"
end run
APPLESCRIPT
}

notify() {
    /usr/bin/osascript - "$1" "$2" <<'APPLESCRIPT' >/dev/null 2>&1 &
on run argv
    display notification (item 2 of argv) with title (item 1 of argv)
end run
APPLESCRIPT
}

launcher_dir="${0:A:h}"
project_root="${launcher_dir:h:h:h}"
project_location_file="${HOME}/Library/Application Support/Dashboard Analytic/project-path"

if [[ ! -f "${project_root}/src/main.py" ]]; then
    if [[ -f "$project_location_file" ]]; then
        project_root="$(<"$project_location_file")"
    fi
    if [[ ! -f "${project_root}/src/main.py" ]]; then
        selected_project="$(/usr/bin/osascript <<'APPLESCRIPT'
set selectedFolder to choose folder with prompt "Select the Dashboard Analytic project folder"
POSIX path of selectedFolder
APPLESCRIPT
)" || exit 0
        project_root="${selected_project%/}"
    fi
fi

if [[ ! -f "${project_root}/src/main.py" ]]; then
    show_message "Dashboard Analytic" "The selected folder is not a Dashboard Analytic project."
    exit 1
fi

/bin/mkdir -p "${HOME}/Library/Application Support/Dashboard Analytic"
print -r -- "$project_root" > "$project_location_file"

runtime_dir="${project_root}/.dashboard-analytic-runtime"
pid_file="${runtime_dir}/server.pid"
log_file="${runtime_dir}/server.log"
port="${APP_PORT:-7278}"
url="http://127.0.0.1:${port}"

is_running() {
    [[ -f "$pid_file" ]] || return 1
    local pid
    pid="$(<"$pid_file")"
    [[ "$pid" == <-> ]] && /bin/kill -0 "$pid" 2>/dev/null && /bin/ps -p "$pid" -o command= | /usr/bin/grep -Fq -- "${project_root}/src/main.py"
}

stop_server() {
    local pid
    pid="$(<"$pid_file")"
    /bin/kill "$pid" 2>/dev/null || true
    local attempt=0
    while /bin/kill -0 "$pid" 2>/dev/null && (( attempt < 30 )); do
        /bin/sleep 0.1
        ((attempt++))
    done
    if /bin/kill -0 "$pid" 2>/dev/null; then
        /bin/kill -9 "$pid" 2>/dev/null || true
    fi
    /bin/rm -f "$pid_file"
    notify "Dashboard Analytic" "Server stopped."
}

cleanup_done=0
cleanup() {
    (( cleanup_done )) && return
    cleanup_done=1
    if is_running; then
        stop_server
    else
        /bin/rm -f "$pid_file"
    fi
}

trap cleanup EXIT INT TERM HUP

if is_running; then
    stop_server
    exit 0
fi

/bin/rm -f "$pid_file"
/bin/mkdir -p "$runtime_dir"

if /usr/sbin/lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    show_message "Dashboard Analytic" "Port ${port} is already in use. Stop the process using it or set APP_PORT to a different port."
    exit 1
fi

project_venv_python="${project_root}/.venv/bin/python"
managed_venv="${project_root}/.dashboard-analytic-venv"
managed_venv_python="${managed_venv}/bin/python"
python_bin=""

if [[ -x "$project_venv_python" ]] && "$project_venv_python" -c 'import numpy, pandas' >/dev/null 2>&1; then
    python_bin="$project_venv_python"
elif [[ -x "$managed_venv_python" ]] && "$managed_venv_python" -c 'import numpy, pandas' >/dev/null 2>&1; then
    python_bin="$managed_venv_python"
fi

if [[ -z "$python_bin" ]]; then
    bootstrap_python=""
    for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
        if [[ -x "$candidate" ]] && "$candidate" -c 'import sys; raise SystemExit(not (sys.version_info >= (3, 11)))' 2>/dev/null; then
            bootstrap_python="$candidate"
            break
        fi
    done

    if [[ -z "$bootstrap_python" ]]; then
        show_message "Dashboard Analytic" "Python 3.11 or later is required. Install it and open this application again."
        exit 1
    fi

    /bin/rm -rf "$managed_venv"
    "$bootstrap_python" -m venv "$managed_venv" || {
        show_message "Dashboard Analytic" "The native virtual environment could not be created. Check the project folder permissions."
        exit 1
    }
    python_bin="$managed_venv_python"
    "$python_bin" -m pip install --upgrade pip >>"$log_file" 2>&1
    "$python_bin" -m pip install -r "${project_root}/requirements.txt" >>"$log_file" 2>&1 || {
        show_message "Dashboard Analytic" "Dependencies could not be installed. Check ${log_file}."
        exit 1
    }
fi

/usr/bin/nohup "$python_bin" "${project_root}/src/main.py" >>"$log_file" 2>&1 &
server_pid=$!
print -r -- "$server_pid" > "$pid_file"

# A normal quit signals this script, while macOS Force Quit cannot run any
# application cleanup code. Keep supervising the native launcher as well so an
# orphaned script still stops the server and removes its PID file.
supervise_server() {
    while /bin/kill -0 "$server_pid" 2>/dev/null; do
        if ! /bin/kill -0 "$launcher_pid" 2>/dev/null; then
            return 0
        fi
        /bin/sleep 0.25
    done
    wait "$server_pid"
}

local_attempt=0
while (( local_attempt < 50 )); do
    if ! /bin/kill -0 "$launcher_pid" 2>/dev/null; then
        exit 0
    fi
    if ! /bin/kill -0 "$server_pid" 2>/dev/null; then
        /bin/rm -f "$pid_file"
        show_message "Dashboard Analytic" "The server could not start. Check ${log_file}."
        exit 1
    fi
    if /usr/bin/curl --silent --output /dev/null --max-time 1 "$url"; then
        /usr/bin/open "$url"
        notify "Dashboard Analytic" "Server started at ${url}. Quit this app to stop it."
        supervise_server
        exit 0
    fi
    /bin/sleep 0.2
    ((local_attempt++))
done

/usr/bin/open "$url"
notify "Dashboard Analytic" "The server is still starting at ${url}. Quit this app to stop it."
supervise_server
