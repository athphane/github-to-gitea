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

### Usage

```bash
gitea-mirror stars                          # mirror all your starred repos
gitea-mirror stars --workers 10             # ...with 10 concurrent workers
gitea-mirror owned                          # mirror repos you own
gitea-mirror search                         # interactive search and pick
gitea-mirror org <org_name>                 # mirror all repos in a GitHub org
gitea-mirror org <org_name> --section gitea_private  # via CF-protected Gitea
```

Global options: `--config PATH`, `--section SECTION`, `--debug`.

Per subcommand: `--no-mirror` (clone without mirroring), `--workers N` (concurrent mirrors, default 1). `search` also takes `--limit N`.

> The old `python scripts/*.py` wrappers still work for backward compatibility.

### Pro tip

Add webhook notifications in your Gitea admin panel. I use Telegram — a bot pings me whenever a new repo is created, so I know things are working.

### Future plans

- [ ] Interactive Telegram bot to trigger mirrors remotely
- [ ] Per-org repo filtering in `org` subcommand

## Credits

- [Athfan Khaleel (@athphane)](https://athfan.com)

---

<p align="center">Made with love from the Maldives ❤</p>
