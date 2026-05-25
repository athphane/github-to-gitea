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
gitea-mirror org <org_name> --section gitea_private   # use CF-protected Gitea
gitea-mirror search                         # interactive search and mirror
```

Global options: `--config PATH` (default `config.ini`), `--section SECTION` (default `gitea`), `--debug`.
Per subcommand: `--no-mirror` (clone without mirroring), `--workers N` (concurrent mirrors, default 1). `search` also takes `--limit N`.

The old `scripts/` wrappers still work:
```bash
python scripts/clone_github_stars.py
python scripts/clone_own_repos.py
python scripts/interactive.py
python scripts/scrape_organization.py <org_name>
python scripts/scrape_organization_cf.py <org_name>
```

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
- Repo lists are cached per entity `username` so existence checks hit the API once per account/org, not once per repo.
- No test suite, no CI.
