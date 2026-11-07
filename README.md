## Github To Gitea Mirroring CLI

> Clone and mirror all the repos!

I started to host my own [Gitea](https://github.com/go-gitea/gitea) server and wanted a way to easily synchronize the repos I have to my own Gitea server.

If you want to deploy your own Gitea server, you can follow Gitea's own Docker Installation Guide [here](https://docs.gitea.io/en-us/install-with-docker/).

### Setup

```bash
python3.10 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp config.ini.example config.ini   # then fill in your values
```

### Config

The `config.ini` file supports two Gitea sections for instances behind Cloudflare Access:

| Key | Value |
|---|---|
| `[gitea]` / `[gitea_private]` | Section header — use `gitea_private` for CF-protected instances |
| `host` | Your Gitea instance URL (e.g. `https://git.domain.com`) |
| `token_main_account` | Access token for your main Gitea account |
| `token_clone_account` | Access token for your clone Gitea account |
| `[github] username` | Your GitHub username (e.g. `athphane`) |
| `[github] token` | GitHub personal access token ([create one](https://github.com/settings/tokens/new)) |
| `[cloudflare] cf_access_client_id` | Cloudflare Access client ID (only needed for `gitea_private`) |
| `[cloudflare] cf_access_client_secret` | Cloudflare Access client secret (only needed for `gitea_private`) |

**Why two Gitea accounts?**

My main account (`athphane`) only owns repos I personally own on GitHub — a one-to-one copy. A secondary clone account (`athphane-clone`) owns mirrored repos from *other* GitHub users. Those repos are renamed to `{owner}_{repo}` to avoid collisions.

When mirroring a repo owned by a GitHub **organization**, the tool creates that organization on Gitea (if it doesn't exist), adds your main account as owner, and mirrors the repo into it.

Get your Gitea tokens at `https://git.domain.com/user/settings/applications`. Make one for each account.

#### Private Gitea configuration

To use a second Gitea instance behind Cloudflare Access, add these sections to
`config.ini`, alongside your existing `[gitea]` and `[github]` sections:

```ini
[gitea_private]
host=https://private-git.example.com
token_main_account=your-private-gitea-main-token
token_clone_account=your-private-gitea-clone-token

[cloudflare]
cf_access_client_id=your-cloudflare-access-client-id
cf_access_client_secret=your-cloudflare-access-client-secret
```

Replace the example values with your private instance's URL, its two Gitea
account tokens, and your Cloudflare Access service token values. The GitHub
username and token still come from the shared `[github]` section. When both
Cloudflare values are configured, the CLI includes the Cloudflare Access
headers in its Gitea API requests.

Select this instance with `--section gitea_private` **before** the subcommand:

```bash
gitea-mirror --section gitea_private owned
gitea-mirror --section gitea_private stars --workers 10
gitea-mirror --section gitea_private org go-gitea
```

### Usage

```bash
gitea-mirror stars                          # mirror starred repos, 5 at a time
gitea-mirror stars --workers 10             # ...with 10 concurrent workers
gitea-mirror stars --workers 1              # process repos sequentially
gitea-mirror owned                          # mirror repos you own
gitea-mirror search                         # interactive search and pick
gitea-mirror org <org_name>                 # mirror all repos in a GitHub org
gitea-mirror --section gitea_private org <org_name>  # via CF-protected Gitea
```

Global options: `--config PATH`, `--section SECTION`, `--debug`.

Batch commands (`stars`, `owned`, `org`) accept `--no-mirror` (clone without
mirroring) and `--workers N` (concurrent migrations, default 5). Use
`--workers 1` for sequential migrations. `search` takes `--limit N`.

Repository preparation runs first, then a worker pool submits migrations to
Gitea concurrently. tqdm progress bars show preparation and completed requests,
with counts for mirrored, skipped, and failed repositories. Console logs appear
above the bars, and bars are automatically disabled when output is redirected.
Failures are logged and do not stop the remaining repositories. Gitea may
continue importing a repository after its migration request returns; the bars
track API requests, not server-side import progress.

> The old `python scripts/*.py` wrappers still work for backward compatibility.

### Docker

Compose builds and runs the local image `athphane/github-to-gitea:local`, using
Python 3.12 on Alpine 3.23. No local Python environment is needed. Create
`config.ini` first if you do not already have one, then run the configured batch:

```bash
cp config.ini.example config.ini   # skip this if you already have a config
# Fill in config.ini before running a migration.
docker compose up --no-color --exit-code-from mirror mirror
```

Compose builds the image if it is missing and reuses it on later runs. The
application image stays local, and Compose does not try to pull it from a
registry. The default command in `compose.yaml` mirrors repos you own:

```yaml
command: ["owned"]
```

Change that line to configure the scheduled job, for example:

```yaml
command: ["owned", "--workers", "10"]
# Or: ["--section", "gitea_private", "org", "your-org"]
```

Each `up` invocation runs the batch and exits. The stopped container remains for
inspection and starts again on the next run; `restart: "no"` keeps it from
running continuously. `--exit-code-from mirror` returns the CLI's exit status.
Use `docker compose logs mirror` to inspect logs or `docker compose down` to
remove the stopped container.

For other commands, override the configured job for one run:

```bash
docker compose run --rm mirror owned --workers 10
docker compose run --rm mirror --section gitea_private org <org_name>
docker compose run --rm mirror search
```

`compose.yaml` mounts `./config.ini` read-only and reports an error if it is
missing. Credentials stay on the host. The container runs as UID 1000; if your
config is only readable by a different host user, set `user: "UID:GID"` on the
`mirror` service to match that user's numeric IDs.

Gitea performs the repository imports, so no repository storage volume or
published ports are needed. The configured Gitea URL must be reachable from the
container; `localhost` inside the container refers to the container itself.
Logs are unbuffered; progress bars are disabled without a terminal. Use
`docker compose run --rm mirror ...` from a terminal for progress bars or
interactive search.

#### Rebuild after changes

After changing this project, rebuild the local image:

```bash
./scripts/rebuild-image.sh
```

The script finds the project directory automatically and only builds the image;
it does not start a migration. It accepts Compose build options, such as
`./scripts/rebuild-image.sh --no-cache`. The next `docker compose up` uses the
rebuilt image. The Python base image and dependencies are downloaded during a
build as needed.

#### Batch runner scripts

Use the dedicated scripts to select a batch without changing `compose.yaml`:

```bash
./scripts/run-owned.sh                      # repositories you own
./scripts/run-stars.sh                      # your starred repositories
./scripts/run-org.sh go-gitea                # all repositories in this org
./scripts/run-stars.sh --workers 10          # override concurrent workers
./scripts/run-org.sh go-gitea --no-mirror    # clone without ongoing mirroring
```

`run-org.sh` requires the GitHub organization name as its first argument.
Replace `go-gitea` with the organization you want to copy. The dedicated scripts
use the default `[gitea]` section and forward additional batch options such as
`--workers N` and `--no-mirror` to the CLI.

All runners share the same lock and rotating log, so simultaneous invocations
skip rather than write or migrate concurrently. Output is written to
`mirror.log`; use `tail -f mirror.log` to follow a run.

`scripts/run-mirror.sh` runs the command configured in `compose.yaml` (default:
`owned`), builds the image if it is missing, and appends output to `mirror.log`
in the project directory. It uses `flock` to skip overlapping runs and works
from any working directory. Logs rotate while output is written: `mirror.log`
is capped at 10 MiB, with three backups (`mirror.log.1` through `mirror.log.3`,
newest first). Total retained log output is capped at 40 MiB. Backups are
gitignored along with the current log.

#### Runner scripts with `gitea_private`

After filling in the [private Gitea configuration](#private-gitea-configuration),
use the shared runner to select that section for any batch:

```bash
./scripts/run-mirror.sh --section gitea_private owned
./scripts/run-mirror.sh --section gitea_private stars --workers 10
./scripts/run-mirror.sh --section gitea_private org go-gitea
./scripts/run-mirror.sh --section gitea_private org go-gitea --no-mirror
```

`--section` is a global option, so it must come before `owned`, `stars`, or
`org`. These commands use the same read-only config mount, lock, and rotating
log as the dedicated runners.

To make the configured Compose job use the private instance, set this in
`compose.yaml`:

```yaml
command: ["--section", "gitea_private", "owned"]
```

Then `./scripts/run-mirror.sh` with no arguments, including an existing cron
entry that calls it, runs owned repositories against the private instance.
You can also run a command directly through Compose:

```bash
docker compose run --rm mirror --section gitea_private org go-gitea
```

#### Run from cron

Add a host cron entry with `crontab -e`. This example runs daily at 03:00 in the
host's timezone:

```cron
0 3 * * * /absolute/path/to/github-to-gitea/scripts/run-mirror.sh
```

To schedule stars or an organization instead, use `scripts/run-stars.sh` or
`scripts/run-org.sh go-gitea` in the cron command. Schedule separate jobs at
different times to avoid the shared lock skipping one.

For jobs targeting `gitea_private`, pass the section and batch to the shared
runner. These examples schedule owned repos, stars, and an organization at
different hours; add the entries you want:

```cron
0 3 * * * /absolute/path/to/github-to-gitea/scripts/run-mirror.sh --section gitea_private owned
0 4 * * * /absolute/path/to/github-to-gitea/scripts/run-mirror.sh --section gitea_private stars
0 5 * * * /absolute/path/to/github-to-gitea/scripts/run-mirror.sh --section gitea_private org go-gitea
```

Replace the project path. The runner uses Bash. The cron user's `PATH` must
include `docker` and `flock`, and that user needs access to Docker, the config,
and the log location.
The script holds its lock for the full run, returns the Compose exit status,
and exits successfully without starting another job if a run is already in
progress. Each run discovers new repositories and skips existing mirrors.

Failures are logged; individual repository failures currently do not change the
CLI's exit status, so check the log when monitoring scheduled jobs.

### Pro tip

Add webhook notifications in your Gitea admin panel. I use Telegram — a bot pings me whenever a new repo is created, so I know things are working.

### Future plans

- [ ] Interactive Telegram bot to trigger mirrors remotely
- [ ] Per-org repo filtering in `org` subcommand

## Credits

- [Athfan Khaleel (@athphane)](https://athfan.com)

---

<p align="center">Made with love from the Maldives ❤</p>
