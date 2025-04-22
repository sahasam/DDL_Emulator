#!/bin/bash

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# SSH connection details
# Remote host configurations - using simple arrays instead of associative array
REMOTE_HOSTS=(
  "daedaelus@10.0.1.25:/opt/hermes/src"
  "daedaelus@10.0.1.28:/opt/hermes/src"
)
LOCAL_DIR="$SCRIPT_DIR/../src"

# Ensure fswatch is installed
if ! command -v fswatch &> /dev/null; then
    echo "Error: fswatch is required but not installed."
    echo "Install with: brew install fswatch"
    exit 1
fi

echo "Watching $LOCAL_DIR for changes..."

# Watch for changes and sync immediately when detected using fswatch (macOS compatible)
fswatch -o $LOCAL_DIR | while read f; do
    echo "Change detected in $LOCAL_DIR"
    for host in "${REMOTE_HOSTS[@]}"; do
        echo "Syncing to $host..."
        rsync -avz --delete $LOCAL_DIR/ $host
    done
done


