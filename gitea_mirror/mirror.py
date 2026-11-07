from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from gitea import (
    AlreadyExistsException,
    Gitea,
    MigrationServices,
    Organization,
    Repository,
)
from github import Github
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

logger = logging.getLogger(__name__)

_MAX_ORG_RECURSION = 10
DEFAULT_WORKERS = 5


class GithubToGitea:
    def __init__(
        self,
        gitea_url: str,
        gitea_token_main: str,
        gitea_token_clone: str,
        github_username: str,
        github_token: str,
        *,
        gitea_client_class: type[Gitea] = Gitea,
        gitea_client_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.gitea_url = gitea_url
        self.github_username = github_username
        self.github_token = github_token

        client_kwargs = gitea_client_kwargs or {}
        self._gitea_client_class = gitea_client_class
        self._gitea_client_kwargs = client_kwargs
        self._gitea_token_main = gitea_token_main
        self._gitea_token_clone = gitea_token_clone

        self.gitea_main = gitea_client_class(
            gitea_url, gitea_token_main, **client_kwargs
        )
        self.gitea_clone = gitea_client_class(
            gitea_url, gitea_token_clone, **client_kwargs
        )
        self.github = Github(github_token)

        self._user = self.gitea_clone.get_user()
        self._main_user = self.gitea_main.get_user()
        logger.debug('Gitea clone user: %s', self._user.username)

        self._repo_cache: dict[str, set[str]] = {}
        self._org_cache: dict[str, Organization] = {}

    @property
    def user(self) -> Any:
        return self._user

    def _org_exists(self, github_org_login: str) -> Organization | None:
        for org in self.gitea_main.get_orgs():
            if org.username == github_org_login:
                return org
        return None

    def find_org_from_gitea(self, github_org: Any, _depth: int = 0) -> Organization:
        if github_org.login in self._org_cache:
            return self._org_cache[github_org.login]

        if _depth > _MAX_ORG_RECURSION:
            raise RecursionError(
                f'Failed to create Gitea org {github_org.login!r} '
                f'after {_MAX_ORG_RECURSION} attempts'
            )

        existing = self._org_exists(github_org.login)
        if existing:
            self._org_cache[github_org.login] = existing
            return existing

        self.create_org_in_gitea(github_org.login, github_org.description)

        return self.find_org_from_gitea(github_org, _depth=_depth + 1)

    def create_org_in_gitea(self, name: str, description: str | None) -> None:
        desc = description[:255] if description else ''
        logger.info('Creating Gitea org: %s', name)
        self.gitea_main.create_org(
            owner=self.gitea_main.get_user(),
            orgName=name,
            description=desc,
        )

    def check_if_repo_exists_in_gitea(self, gitea_entity: Any, repo_name: str) -> bool:
        return any(
            repo.get_full_name().endswith(repo_name)
            for repo in gitea_entity.get_repositories()
        )

    def create_repo_mirror(self, repo: Any, *, mirror: bool = True) -> None:
        self.mirror_repos_batch([repo], mirror=mirror, workers=1)

    def _find_repo_in_entity(
        self,
        gitea_entity: Any,
        repo_name: str,
    ) -> bool:
        cache_key = gitea_entity.username.casefold()
        if cache_key not in self._repo_cache:
            self._repo_cache[cache_key] = {
                repo.get_full_name().casefold()
                for repo in gitea_entity.get_repositories()
            }

        return f'{cache_key}/{repo_name.casefold()}' in self._repo_cache[cache_key]

    def mirror_repos_batch(
        self, repos: list[Any], *, mirror: bool = True, workers: int = DEFAULT_WORKERS
    ) -> tuple[int, int]:
        """Return (mirrored, already existing); log failures separately.

        Prepare on the calling thread so organization creation and repository
        caches stay serial. Only the blocking migrations run concurrently.
        """
        if workers < 1:
            raise ValueError('workers must be at least 1')
        if not repos:
            logger.info('No repositories to mirror.')
            return 0, 0

        tasks: list[_MirrorTask] = []
        targets: set[str] = set()
        mirrored = 0
        skipped = 0
        failed = 0

        with logging_redirect_tqdm():
            for repo in tqdm(
                repos, desc='Preparing', unit='repo', dynamic_ncols=True, disable=None
            ):
                try:
                    task = self._prepare_mirror(repo, mirror=mirror)
                except Exception:
                    logger.exception('Failed to prepare repo: %s', repo.full_name)
                    failed += 1
                    continue
                if task is None or task.target in targets:
                    skipped += 1
                else:
                    targets.add(task.target)
                    tasks.append(task)

            with (
                tqdm(
                    total=len(repos),
                    initial=skipped + failed,
                    desc='Mirroring' if mirror else 'Cloning',
                    unit='repo',
                    dynamic_ncols=True,
                    disable=None,
                    postfix={
                        'mirrored': mirrored,
                        'skipped': skipped,
                        'failed': failed,
                    },
                ) as progress,
                ThreadPoolExecutor(max_workers=workers) as pool,
            ):
                future_to_task: dict[Future[None], _MirrorTask] = {
                    pool.submit(self._execute_mirror, task): task for task in tasks
                }
                for future in as_completed(future_to_task):
                    task = future_to_task[future]
                    try:
                        future.result()
                        mirrored += 1
                    except AlreadyExistsException:
                        logger.debug('Repo already exists: %s', task.gh_full_name)
                        skipped += 1
                        self._repo_cache[task.repo_owner.casefold()].add(task.target)
                    except Exception:
                        logger.exception('Failed to mirror repo: %s', task.gh_full_name)
                        failed += 1
                    else:
                        self._repo_cache[task.repo_owner.casefold()].add(task.target)

                    progress.set_postfix(
                        mirrored=mirrored, skipped=skipped, failed=failed, refresh=False
                    )
                    progress.update()

        if failed:
            logger.error('%d repositories failed; see errors above.', failed)

        return mirrored, skipped

    def _prepare_mirror(self, repo: Any, *, mirror: bool = True) -> _MirrorTask | None:
        gh_full_name: str = repo.full_name
        gh_organization = repo.organization
        repo_name: str = gh_full_name.split('/')[1]
        gh_owner_name: str = gh_full_name.split('/')[0]

        construct_prefix = False

        if gh_organization:
            gitea_token = self._gitea_token_main
            gitea_entity = self.find_org_from_gitea(gh_organization)
        else:
            gitea_token = self._gitea_token_clone
            gitea_entity = self._user
            construct_prefix = True

        if self.github_username.casefold() == gh_owner_name.casefold():
            gitea_token = self._gitea_token_main
            gitea_entity = self._main_user
            construct_prefix = False

        if construct_prefix:
            repo_name = f'{gh_owner_name}_{repo_name}'

        if self._find_repo_in_entity(gitea_entity, repo_name):
            logger.debug('Repo already exists: %s', gh_full_name)
            return None

        return _MirrorTask(
            gitea_token=gitea_token,
            clone_url=repo.clone_url,
            repo_name=repo_name,
            description=(
                repo.description[:255] if repo.description else 'No Description'
            ),
            mirror=mirror,
            private=repo.private,
            repo_owner=gitea_entity.username,
            gh_full_name=gh_full_name,
            github_token=self.github_token,
            github_username=self.github_username,
        )

    def _execute_mirror(self, task: _MirrorTask) -> None:
        # requests.Session is mutable; never share one between worker threads.
        client = self._gitea_client_class(
            self.gitea_url, task.gitea_token, **self._gitea_client_kwargs
        )
        try:
            self._migrate_repo(client, task)
        finally:
            client.requests.close()

    @staticmethod
    def _migrate_repo(client: Gitea, task: _MirrorTask) -> None:
        Repository.migrate_repo(
            client,
            service=MigrationServices.GITHUB,
            clone_addr=task.clone_url,
            repo_name=task.repo_name,
            description=task.description,
            auth_token=task.github_token,
            auth_username=task.github_username,
            mirror=task.mirror,
            private=task.private,
            wiki=True,
            labels=True,
            issues=True,
            pull_requests=True,
            milestones=True,
            repo_owner=task.repo_owner,
        )
        logger.info('Mirrored: %s -> %s', task.gh_full_name, task.repo_name)


@dataclass
class _MirrorTask:
    gitea_token: str
    clone_url: str
    repo_name: str
    description: str
    mirror: bool
    private: bool
    repo_owner: str
    gh_full_name: str
    github_token: str
    github_username: str

    @property
    def target(self) -> str:
        return f'{self.repo_owner}/{self.repo_name}'.casefold()
