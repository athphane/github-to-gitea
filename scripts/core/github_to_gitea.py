"""Core helpers for mirroring GitHub repositories to Gitea.

This module previously exposed two almost identical classes – one regular
``GithubToGitea`` and another ``GithubToGiteaCF`` which only differed in the
type of ``Gitea`` client that was instantiated.  Maintaining two copies of the
logic made it hard to keep the behaviour in sync and introduced a lot of
repetition.  The code has now been consolidated into a single class with optional
Cloudflare Access support.

``GithubToGitea`` accepts optional ``cf_access_client_id`` and
``cf_access_client_secret`` arguments.  When provided a ``CFGitea`` client is
used, otherwise the regular ``Gitea`` client is utilised.  A convenience
``from_config`` class method is also provided so that scripts can construct the
object without repeating configuration parsing code.
"""

from gitea import AlreadyExistsException, Gitea, Repository, MigrationServices, Organization
from github import Github

try:  # pragma: no cover - optional dependency
    from core.cf_ready.cf_gitea import CFGitea
except Exception:  # ImportError or any other error
    CFGitea = None


class GithubToGitea:
    """
    Custom class to interact with the Gitea API package in an easier way.
    TODO: Fix like, everything in here.
    """

    def __init__(
        self,
        gitea_url,
        gitea_token_main_account,
        gitea_token_clone_account,
        github_username,
        github_token,
        cf_access_client_id=None,
        cf_access_client_secret=None,
    ):
        """Create a helper around the Gitea and GitHub API clients.

        When Cloudflare Access credentials are supplied a ``CFGitea`` client is
        instantiated which includes the required headers.  Otherwise the normal
        ``Gitea`` client is used.
        """

        self.gitea_url = gitea_url
        self.gitea_token_main_account = gitea_token_main_account  # Main account key
        self.gitea_token_clone_account = gitea_token_clone_account  # Test account key
        self.github_username = github_username
        self.github_token = github_token

        # Decide which Gitea implementation to use
        use_cf = cf_access_client_id and cf_access_client_secret and CFGitea is not None
        gitea_cls = CFGitea if use_cf else Gitea
        gitea_kwargs = {}
        if use_cf:
            gitea_kwargs = {
                "cf_access_client_id": cf_access_client_id,
                "cf_access_client_secret": cf_access_client_secret,
            }

        # Create the Gitea API objects here
        self.gitea_main_account = gitea_cls(self.gitea_url, self.gitea_token_main_account, **gitea_kwargs)
        self.gitea_clone_account = gitea_cls(self.gitea_url, self.gitea_token_clone_account, **gitea_kwargs)

        # Create the Github API object here
        self.github = Github(self.github_token)

        # Load the Gitea user
        self.user = self.gitea_clone_account.get_user()

    @classmethod
    def from_config(
        cls,
        config,
        gitea_section="gitea",
        github_section="github",
        cf_section="cloudflare",
        use_cloudflare=False,
    ):
        """Build ``GithubToGitea`` from a ``ConfigParser`` instance.

        Parameters
        ----------
        config:
            ``configparser.ConfigParser`` instance with loaded values.
        gitea_section:
            Name of the section containing Gitea credentials.
        github_section:
            Section containing GitHub credentials.
        cf_section:
            Section containing Cloudflare Access credentials.  Only read when
            ``use_cloudflare`` is ``True``.
        use_cloudflare:
            Whether to instantiate using ``CFGitea``.
        """

        kwargs = dict(
            gitea_url=config.get(gitea_section, "host"),
            gitea_token_main_account=config.get(gitea_section, "token_main_account"),
            gitea_token_clone_account=config.get(gitea_section, "token_clone_account"),
            github_username=config.get(github_section, "username"),
            github_token=config.get(github_section, "token"),
        )

        if use_cloudflare:
            kwargs.update(
                cf_access_client_id=config.get(cf_section, "cf_access_client_id"),
                cf_access_client_secret=config.get(cf_section, "cf_access_client_secret"),
            )

        return cls(**kwargs)

    def find_org_from_gitea(self, github_org):
        gitea_organizations = self.gitea_main_account.get_orgs()

        for org in gitea_organizations:
            if org.username == github_org.login:
                return org

        self.create_org_in_gitea(github_org.login, github_org.description)

        return self.find_org_from_gitea(github_org)

    def create_org_in_gitea(self, organization_name, organization_description):
        # Create the Github organization on Gitea
        self.gitea_main_account.create_org(
            owner=self.gitea_main_account.get_user(),
            orgName=organization_name,
            description=organization_description[:255] if organization_description else ''
        )

    def check_if_repo_exists_in_gitea(self, gitea_org, repo_name):
        # Check if the repo exists for a given organization in Gitea
        pass

    def create_repo_mirror(self, repo, mirror=True):
        # Create the mirror on Gitea
        gh_full_name = repo.full_name
        gh_organization = repo.organization
        repo_name = gh_full_name.split('/')[1]
        gh_owner_name = gh_full_name.split('/')[0]
        gh_private = repo.private

        construct_user_organization_string = False

        if gh_organization:
            gitea_account = self.gitea_main_account
            gitea_entity = self.find_org_from_gitea(gh_organization)
        else:
            gitea_account = self.gitea_clone_account
            gitea_entity = self.gitea_clone_account.get_user()
            construct_user_organization_string = True

        if self.github_username in gh_full_name:
            gitea_account = self.gitea_main_account
            gitea_entity = self.gitea_main_account.get_user()
            construct_user_organization_string = False

        if not self.find_repo_in_entity(gitea_entity, gh_owner_name, repo_name, gh_organization):
            if construct_user_organization_string:
                repo_name = f"{gh_owner_name}_{repo_name}"

            try:
                Repository.migrate_repo(
                    gitea_account,
                    service=MigrationServices.GITHUB,
                    clone_addr=repo.clone_url,
                    repo_name=repo_name,
                    description=repo.description[:255] if repo.description else 'No Description',
                    auth_token=self.github_token,
                    auth_username=self.github_username,
                    mirror=mirror,
                    private=gh_private,
                    wiki=True,
                    labels=True,
                    issues=True,
                    pull_requests=True,
                    milestones=True,
                    repo_owner=gitea_entity.name if type(gitea_entity) == Organization else gitea_entity.login_name
                    # uid=gitea_entity.id,
                )
            except AlreadyExistsException as e:
                print('Repo already exists')
            except Exception as e:
                print(e)
        else:
            print('Repo already Exists')

    @staticmethod
    def find_repo_in_entity(gitea_entity, gh_owner_name, new_repo_name, is_gh_organization):
        repo_found = False

        for repo in gitea_entity.get_repositories():
            repo_name = repo.get_full_name()

            if is_gh_organization:
                if f"{gh_owner_name}/{new_repo_name}" in repo_name:
                    repo_found = True
            else:
                if f"{gh_owner_name}_{new_repo_name}" in repo_name:
                    repo_found = True

        return repo_found
