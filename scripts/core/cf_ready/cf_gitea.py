from gitea import Gitea


class CFGitea(Gitea):
    def __init__(self, gitea_url: str, token_text=None, auth=None, verify=True, log_level="INFO",
                 cf_access_client_id=None, cf_access_client_secret=None):

        super().__init__(gitea_url, token_text, auth, verify, log_level)
        self.headers["CF-Access-Client-Id"] = cf_access_client_id
        self.headers["CF-Access-Client-Secret"] = cf_access_client_secret
