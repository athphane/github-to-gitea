#!/bin/sh
set -eu

usage() {
    printf 'Usage: %s ORG_NAME [--workers N] [--no-mirror]\n' "$0"
}

case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    ''|-*) usage >&2; exit 2 ;;
esac

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
exec "$script_dir/run-mirror.sh" org "$@"
