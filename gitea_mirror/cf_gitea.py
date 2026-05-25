from __future__ import annotations

from gitea import Gitea


class CFGitea(Gitea):
    def __init__(
        self,
        gitea_url: str,
        token_text: str | None = None,
        auth: str | None = None,
        verify: bool = True,
        log_level: str = 'INFO',
        cf_access_client_id: str | None = None,
        cf_access_client_secret: str | None = None,
    ) -> None:
        super().__init__(gitea_url, token_text, auth, verify, log_level)
        if cf_access_client_id:
            self.headers['CF-Access-Client-Id'] = cf_access_client_id
        if cf_access_client_secret:
            self.headers['CF-Access-Client-Secret'] = cf_access_client_secret
