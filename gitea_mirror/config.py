from __future__ import annotations

import configparser
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Config:
    gitea_host: str
    gitea_token_main: str
    gitea_token_clone: str
    github_username: str
    github_token: str
    cf_client_id: str | None = None
    cf_client_secret: str | None = None

    @classmethod
    def from_ini(
        cls,
        path: str = 'config.ini',
        section: str = 'gitea',
    ) -> Config:
        if not os.path.exists(path):
            msg = (
                f'Config file {path!r} not found. '
                'Copy config.ini.example to config.ini and fill in values.'
            )
            raise FileNotFoundError(msg)

        cfg = configparser.ConfigParser()
        cfg.read(path)

        cf_id: str | None = None
        cf_secret: str | None = None
        if cfg.has_section('cloudflare'):
            cf_id = cfg.get('cloudflare', 'cf_access_client_id', fallback=None)
            cf_secret = cfg.get('cloudflare', 'cf_access_client_secret', fallback=None)

        return cls(
            gitea_host=cfg.get(section, 'host'),
            gitea_token_main=cfg.get(section, 'token_main_account'),
            gitea_token_clone=cfg.get(section, 'token_clone_account'),
            github_username=cfg.get('github', 'username'),
            github_token=cfg.get('github', 'token'),
            cf_client_id=cf_id,
            cf_client_secret=cf_secret,
        )
