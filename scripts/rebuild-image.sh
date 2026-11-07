#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)

exec docker compose \
    --project-directory "$project_dir" \
    --file "$project_dir/compose.yaml" \
    build "$@" mirror
