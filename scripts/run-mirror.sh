#!/bin/bash
set -euo pipefail

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
log_file="$project_dir/mirror.log"
max_log_bytes=$((10 * 1024 * 1024))
log_backups=3

rotate_log() {
    local backup
    for ((backup = log_backups; backup > 1; backup--)); do
        if [[ -f "$log_file.$((backup - 1))" ]]; then
            mv -f -- "$log_file.$((backup - 1))" "$log_file.$backup"
        fi
    done
    if [[ -f "$log_file" ]]; then
        mv -f -- "$log_file" "$log_file.1"
    fi
    : > "$log_file"
}

write_log() {
    # Bash string lengths and slices must count bytes, including for UTF-8 logs.
    local LC_ALL=C
    local log_bytes=0 line remaining chunk
    if [[ -f "$log_file" ]]; then
        log_bytes=$(wc -c < "$log_file")
        if ((log_bytes >= max_log_bytes)); then
            if ((log_bytes > max_log_bytes)); then
                tail -c "$max_log_bytes" -- "$log_file" > "$log_file.tmp"
                mv -f -- "$log_file.tmp" "$log_file"
            fi
            rotate_log
            log_bytes=0
        fi
    fi

    while IFS= read -r line || [[ -n "$line" ]]; do
        line+=$'\n'
        # Keep ordinary log lines together when they fit in one file.
        if ((log_bytes > 0 && log_bytes + ${#line} > max_log_bytes)); then
            rotate_log
            log_bytes=0
        fi
        # Split oversized lines too, so each file stays within the size limit.
        while [[ -n "$line" ]]; do
            if ((log_bytes >= max_log_bytes)); then
                rotate_log
                log_bytes=0
            fi
            remaining=$((max_log_bytes - log_bytes))
            chunk=${line:0:remaining}
            printf '%s' "$chunk" >> "$log_file"
            log_bytes=$((log_bytes + ${#chunk}))
            line=${line:${#chunk}}
        done
    done
}

# Hold the lock through both Compose and the log writer, including rotation.
exec 9>/tmp/gitea-mirror.lock
flock -n -E 200 9 || {
    lock_status=$?
    if [[ "$lock_status" -eq 200 ]]; then
        exit 0
    fi
    exit "$lock_status"
}

compose_command=(
    docker compose
    --project-directory "$project_dir"
    --file "$project_dir/compose.yaml"
)

if (($#)); then
    "${compose_command[@]}" run --rm -T --interactive=false mirror "$@" 2>&1 | write_log
else
    "${compose_command[@]}" up --no-color --exit-code-from mirror mirror 2>&1 | write_log
fi
