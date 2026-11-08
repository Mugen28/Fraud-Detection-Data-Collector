#!/bin/sh
# Container entrypoint. Refuses a broken session mount, then runs the given command.
set -e

STATE_FILE="${ARKM_STORAGE_FILE:-/app/storage_state.json}"

if [ -d "$STATE_FILE" ]; then
    echo "ERROR: $STATE_FILE is a directory." >&2
    echo "Docker creates a directory when the host file is missing at mount time." >&2
    echo "Create a real storage_state.json on the host first (./run.sh --login), then start the container." >&2
    exit 1
fi

if [ "$#" -eq 0 ]; then
    set -- python3 run_pipeline.py
fi

# Compose may pass the command as one string ("python3 scheduler.py").
if [ "$#" -eq 1 ]; then
    case "$1" in
        *" "*)
            exec sh -c "$1"
            ;;
    esac
fi

exec "$@"
