#!/usr/bin/env bash
# ==============================================================================
# arkm crawler - Universal Automated Host Login & Docker Runner
# ==============================================================================
# - Detects and uses the best compatible Python 3.8+ on the host
# - Safely manages an isolated, self-contained host virtual environment (.venv)
# - Validates or performs interactive authentication on host display
# - Mounts authenticated session and runs the crawler pipeline inside Docker
# - Supports 24h cron daemon with human-like jitter
# - Supports automatic Linux systemd service installation & management
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

FORCE_LOGIN=false
CLEAN_ENV=false
INSTALL_SERVICE=false
UNINSTALL_SERVICE=false
STATUS_SERVICE=false
DAEMON_MODE=false
PASSTHROUGH_ARGS=()

for arg in "$@"; do
    case "$arg" in
        --login|--relogin)
            FORCE_LOGIN=true
            ;;
        --clean-env|--recreate-env)
            CLEAN_ENV=true
            ;;
        --install-service|--service)
            INSTALL_SERVICE=true
            ;;
        --uninstall-service)
            UNINSTALL_SERVICE=true
            ;;
        --status-service)
            STATUS_SERVICE=true
            ;;
        --daemon)
            DAEMON_MODE=true
            ;;
        *)
            PASSTHROUGH_ARGS+=("$arg")
            ;;
    esac
done

echo "======================================================================"
echo "      Iranian Exchanges Intelligence Suite - Universal Runner"
echo "======================================================================"

# Handle Service Uninstallation
if [ "$UNINSTALL_SERVICE" = true ]; then
    echo "🗑️  Uninstalling Linux Systemd Service (arkm-crawler)..."
    SERVICE_FILE="/etc/systemd/system/arkm-crawler.service"
    if command -v systemctl &>/dev/null; then
        if [ "$EUID" -ne 0 ]; then
            sudo systemctl stop arkm-crawler.service 2>/dev/null || true
            sudo systemctl disable arkm-crawler.service 2>/dev/null || true
            sudo rm -f "$SERVICE_FILE"
            sudo systemctl daemon-reload
        else
            systemctl stop arkm-crawler.service 2>/dev/null || true
            systemctl disable arkm-crawler.service 2>/dev/null || true
            rm -f "$SERVICE_FILE"
            systemctl daemon-reload
        fi
        echo "✅ Service arkm-crawler successfully removed."
    else
        echo "⚠️  systemctl not found on this system."
    fi
    exit 0
fi

# Handle Service Status
if [ "$STATUS_SERVICE" = true ]; then
    if command -v systemctl &>/dev/null; then
        systemctl status arkm-crawler.service || true
    else
        echo "⚠️  systemctl not found on this system."
    fi
    exit 0
fi

# Docker is required only to run the crawler. Login opens a browser on this
# machine and must still work when Docker is not installed or not running.
require_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        echo "❌ Error: Docker is not installed. Please install Docker."
        if check_valid_session; then
            echo "✅ Arkham session is already saved and will be reused once Docker is available."
        fi
        exit 1
    fi
    if ! docker info >/dev/null 2>&1; then
        echo "❌ Error: Docker daemon is not running. Please start Docker first."
        if check_valid_session; then
            echo "✅ Arkham session is already saved and will be reused once Docker is running."
        fi
        exit 1
    fi
}

# 1. Find Best Compatible Host Python (3.8+)
find_host_python() {
    local candidates=("python3.12" "python3.11" "python3.10" "python3.9" "python3" "python")
    for py in "${candidates[@]}"; do
        if command -v "$py" &>/dev/null; then
            local is_supported
            is_supported=$("$py" -c 'import sys; print("yes" if sys.version_info >= (3, 8) else "no")' 2>/dev/null || echo "no")
            if [ "$is_supported" = "yes" ]; then
                echo "$py"
                return 0
            fi
        fi
    done
    return 1
}

HOST_PYTHON=$(find_host_python || echo "")
if [ -z "$HOST_PYTHON" ]; then
    echo "❌ Error: No compatible Python (>= 3.8) found on this machine."
    echo "👉 Please install Python 3.8, 3.9, 3.10, 3.11, or 3.12."
    exit 1
fi

HOST_PY_VER=$("$HOST_PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
echo "🔍 Host Python detected: $HOST_PYTHON ($HOST_PY_VER)"

# 3. Check for Existing Valid Session
check_valid_session() {
    if [ ! -f "storage_state.json" ]; then
        return 1
    fi
    "$HOST_PYTHON" -c "
import json, sys
try:
    data = json.load(open('storage_state.json'))
    cookies = data.get('cookies', [])
    valid = any(
        c.get('name') == 'arkham_session'
        and c.get('value')
        and 'arkm.com' in (c.get('domain') or '')
        for c in cookies
    )
    sys.exit(0 if valid else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null
}

SESSION_VALID=false
if [ "$FORCE_LOGIN" = false ] && check_valid_session; then
    SESSION_VALID=true
    echo "✅ Valid Arkham session detected in storage_state.json (Skipping host login)."
fi

# 4. If Login Needed: Setup Host Environment & Authenticate
if [ "$SESSION_VALID" = false ]; then
    echo ""
    echo "🔑 Arkham authentication required."

    VENV_DIR="$SCRIPT_DIR/.venv"
    if [ -x "$VENV_DIR/bin/python" ]; then
        VENV_PY="$VENV_DIR/bin/python"
    elif [ -x "$VENV_DIR/Scripts/python.exe" ]; then
        VENV_PY="$VENV_DIR/Scripts/python.exe"
    else
        VENV_PY="$VENV_DIR/bin/python"
    fi

    # Validate or recreate existing .venv
    REBUILD_VENV=false
    if [ "$CLEAN_ENV" = true ]; then
        REBUILD_VENV=true
    elif [ ! -d "$VENV_DIR" ] || [ ! -x "$VENV_PY" ]; then
        REBUILD_VENV=true
    elif ! "$VENV_PY" -c 'import sys; sys.exit(0)' 2>/dev/null; then
        echo "⚠️  Existing .venv is broken or from a different OS/version. Rebuilding..."
        REBUILD_VENV=true
    fi

    if [ "$REBUILD_VENV" = true ]; then
        echo "📦 Creating self-contained host virtual environment (.venv)..."
        rm -rf "$VENV_DIR"
        
        if ! "$HOST_PYTHON" -m venv "$VENV_DIR" 2>/dev/null; then
            echo "⚠️  'python -m venv' failed. Attempting automatic standalone virtualenv bootstrap..."
            if command -v virtualenv &>/dev/null; then
                virtualenv -p "$HOST_PYTHON" "$VENV_DIR"
            elif curl -fsSL https://bootstrap.pypa.io/virtualenv.pyz -o /tmp/virtualenv.pyz 2>/dev/null; then
                "$HOST_PYTHON" /tmp/virtualenv.pyz "$VENV_DIR"
                rm -f /tmp/virtualenv.pyz
            else
                echo "❌ Error: Could not create Python virtual environment."
                echo "👉 On Ubuntu/Debian, please run: sudo apt install python3-venv"
                exit 1
            fi
        fi
    fi

    # Ensure all required packages and browser binaries are downloaded and up to date
    if ! "$VENV_PY" -c 'import playwright, requests, curl_cffi' 2>/dev/null; then
        echo "⬇️  Automatically downloading and installing required Python packages..."
        "$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel --quiet
        "$VENV_DIR/bin/pip" install -r requirements.txt --quiet

        echo "🌐 Automatically downloading browser binaries and system libraries (Chromium)..."
        "$VENV_DIR/bin/playwright" install --with-deps chromium 2>/dev/null || \
        "$VENV_DIR/bin/playwright" install chromium chrome 2>/dev/null || \
        "$VENV_DIR/bin/playwright" install chromium || true
    fi

    if ! "$VENV_PY" -c 'import api_generator, sys; sys.exit(0 if api_generator.installed_login_browser() else 1)' 2>/dev/null; then
        echo "🌐 No Chrome or Playwright browser found. Downloading one for the login window..."
        if [ -x "$VENV_DIR/bin/playwright" ]; then
            PW="$VENV_DIR/bin/playwright"
        else
            PW="$VENV_DIR/Scripts/playwright.exe"
        fi
        "$PW" install chrome 2>/dev/null || "$PW" install chromium || true
    fi

    echo ""
    echo "👉 Opening real Chrome on your display... Please log in and solve any captcha."
    echo ""
    "$VENV_PY" api_generator.py login

    # Verify session was successfully saved
    if ! check_valid_session; then
        echo "❌ Authentication failed or aborted. Exiting."
        exit 1
    fi
    echo "✅ Authentication successful! Session saved to storage_state.json."
fi

require_docker

# Handle Systemd Service Installation
if [ "$INSTALL_SERVICE" = true ]; then
    echo ""
    echo "⚙️  Installing Linux Systemd Service for 24h Crawler Daemon..."
    
    if ! command -v systemctl &>/dev/null; then
        echo "❌ Error: systemctl is not available on this OS (non-systemd environment)."
        echo "👉 For Docker background daemon without systemd, run: ./run.sh --daemon"
        exit 1
    fi

    DOCKER_BIN=$(command -v docker)
    SERVICE_FILE="/etc/systemd/system/arkm-crawler.service"

    SERVICE_CONTENT="[Unit]
Description=Arkham Iranian Cryptocurrency Exchanges Crawler Daemon (24h + Jitter)
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
Environment=\"CRAWLER_CMD=python3 scheduler.py\"
ExecStart=$DOCKER_BIN compose up
ExecStop=$DOCKER_BIN compose down
Restart=always
RestartSec=30
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
"

    echo "Building Docker image before service registration..."
    docker compose build

    echo "Writing systemd unit file to $SERVICE_FILE..."
    if [ "$EUID" -ne 0 ]; then
        echo "$SERVICE_CONTENT" | sudo tee "$SERVICE_FILE" >/dev/null
        sudo systemctl daemon-reload
        sudo systemctl enable arkm-crawler.service
        sudo systemctl restart arkm-crawler.service
    else
        echo "$SERVICE_CONTENT" > "$SERVICE_FILE"
        systemctl daemon-reload
        systemctl enable arkm-crawler.service
        systemctl restart arkm-crawler.service
    fi

    echo ""
    echo "======================================================================"
    echo "✅ Linux Systemd Service installed and started successfully!"
    echo "======================================================================"
    echo "• Service Name : arkm-crawler.service"
    echo "• Interval     : 24h cron loop with ±2h random jitter (scheduler.py)"
    echo "• Check status : sudo systemctl status arkm-crawler"
    echo "• Live logs    : sudo journalctl -u arkm-crawler -f"
    echo "• Stop service : sudo systemctl stop arkm-crawler"
    echo "• Start service: sudo systemctl start arkm-crawler"
    echo "• Uninstall    : ./run.sh --uninstall-service"
    echo "======================================================================"
    exit 0
fi

# Handle Docker Background Daemon Mode
if [ "$DAEMON_MODE" = true ]; then
    echo ""
    echo "🚀 Launching 24h Crawler Scheduler Daemon in background (Docker)..."
    echo "----------------------------------------------------------------------"
    CRAWLER_CMD="python3 scheduler.py" docker compose up -d --build
    echo ""
    echo "✅ Crawler daemon running in background!"
    echo "• View live logs: docker compose logs -f"
    echo "• Stop daemon   : docker compose down"
    echo "----------------------------------------------------------------------"
    exit 0
fi

# 5. Launch Standard Single Pipeline Run in Docker
echo ""
echo "🚀 Launching crawler inside Docker..."
echo "----------------------------------------------------------------------"

if [ ${#PASSTHROUGH_ARGS[@]} -eq 0 ]; then
    docker compose up --build
else
    docker compose run --rm crawler python3 run_pipeline.py "${PASSTHROUGH_ARGS[@]}"
fi

echo "----------------------------------------------------------------------"
echo "🎉 Execution finished! Results are saved in ./api_output/"
