# AGENTS.md

## Setup
- Python 3.10 venv at `venv/`. Activate it, then `pip install -r requirements.txt`.
- Copy `config.ini.example` to `config.ini` and fill in values. This file is gitignored.
- Install the package in editable mode: `venv/bin/pip install -e .`

## Running
The `gitea-mirror` CLI (or `venv/bin/python -m gitea_mirror`) supports four subcommands:

```bash
gitea-mirror stars                         # mirror all starred repos
gitea-mirror owned                          # mirror repos owned by you
gitea-mirror org <org_name>                 # mirror all repos in a GitHub org
gitea-mirror --section gitea_private org <org_name>   # use CF-protected Gitea
gitea-mirror search                         # interactive search and mirror
```

Global options: `--config PATH` (default `config.ini`), `--section SECTION` (default `gitea`), `--debug`.
Batch commands: `--no-mirror` (clone without mirroring), `--workers N` (concurrent mirrors, default 5; use 1 for sequential). `search` takes `--limit N`.

The old `scripts/` wrappers still work:
```bash
python scripts/clone_github_stars.py
python scripts/clone_own_repos.py
python scripts/interactive.py
python scripts/scrape_organization.py <org_name>
python scripts/scrape_organization_cf.py <org_name>
```

## Docker
- After making changes to this project, run `./scripts/rebuild-image.sh` before handing work back so the local Docker image includes the latest code. The script only builds; it does not start migrations. It works from any directory and accepts Compose build flags such as `--no-cache`.
- Compose uses the local image `athphane/github-to-gitea:local` with `pull_policy: never`. Keep the image local; do not publish it to a registry.
- Run the configured batch with `docker compose up --no-color --exit-code-from mirror mirror`. Compose builds the image if missing and reuses it otherwise. Edit `command` in `compose.yaml` to change the default `owned` job.
- Run other one-off commands with `docker compose run --rm mirror owned` (or `org`, `search`). `config.ini` is mounted read-only and must already exist.
- The image runs Python 3.12 on Alpine 3.23 as UID 1000. Pass `docker run --user UID:GID` if the mounted config requires another user's permissions.
- `.dockerignore` allows only application/build files into the context; never copy credentials into the image.
- Schedule `scripts/run-mirror.sh` in host cron. It resolves the project directory, runs the configured Compose job, appends output to `mirror.log`, and skips overlapping runs using `/tmp/gitea-mirror.lock`. Do not allocate a TTY for scheduled runs.
- Dedicated runners: `scripts/run-owned.sh`, `scripts/run-stars.sh`, and `scripts/run-org.sh ORG_NAME`. They forward batch options such as `--workers N` and `--no-mirror` through `run-mirror.sh`, using temporary Compose containers. The shared runner accepts full CLI arguments (e.g. `--section gitea_private org ORG_NAME`); with no arguments it still runs the configured Compose job via `up`. All runners share the same lock and log.
- The runner uses Bash and rotates output while writing: 10 MiB per log, three backups (`mirror.log.1`–`mirror.log.3`), at most 40 MiB retained. Keep rotation under the run lock and preserve Compose's exit status.

## Linting
```bash
venv/bin/ruff check .
venv/bin/ruff format .
```

## Architecture

The `gitea_mirror/` package at the repo root contains the core logic:
- `mirror.py` — `GithubToGitea`: the single unified class for mirroring repos. Accepts an optional `gitea_client_class` parameter to swap in `CFGitea` for Cloudflare Access-protected Gitea instances.
- `cf_gitea.py` — `CFGitea`: a `py-gitea` `Gitea` subclass that injects `CF-Access-Client-Id` and `CF-Access-Client-Secret` headers.
- `config.py` — `Config` dataclass with a `from_ini()` factory that reads `config.ini` from CWD. Explicit `section=` parameter picks `[gitea]` vs `[gitea_private]`.
- `cli.py` — argparse-based CLI with four subcommands.

Two Gitea accounts are required (configured in `config.ini`):
- **Main account** (`token_main_account`): owns repos belonging to your own GitHub user, and owns any Gitea organizations created.
- **Clone account** (`token_clone_account`): owns repos from other GitHub users. These are renamed to `{owner}_{repo}` to avoid collisions.

When a repo belongs to a GitHub organization, the script creates that org on Gitea (via the main account) and places the mirror there.

## Gotchas
- Repo descriptions are truncated to 255 chars (Gitea DB limit).
- `find_org_from_gitea` is recursive with a max depth of 10; if org creation silently fails it raises `RecursionError` instead of looping infinitely.
- Repo lists and organizations are cached. Preparation runs on the calling thread; migrations use separate Gitea sessions in a worker pool.
- tqdm shows preparation and completion progress, with console logging redirected above the bars. Bars are disabled for non-terminal output.
- Run offline regression tests with `venv/bin/python -m unittest discover -s tests`. No CI.
