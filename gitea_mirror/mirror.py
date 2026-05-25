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

logger = logging.getLogger(__name__)

_MAX_ORG_RECURSION = 10


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

        self._repo_cache: dict[str, list[str]] = {}

    @property
    def user(self) -> Any:
        return self._user

    def _org_exists(self, github_org_login: str) -> Organization | None:
        for org in self.gitea_main.get_orgs():
            if org.username == github_org_login:
                return org
        return None

    def find_org_from_gitea(self, github_org: Any, _depth: int = 0) -> Organization:
        if _depth > _MAX_ORG_RECURSION:
            raise RecursionError(
                f'Failed to create Gitea org {github_org.login!r} '
                f'after {_MAX_ORG_RECURSION} attempts'
            )

        existing = self._org_exists(github_org.login)
        if existing:
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
        gh_full_name: str = repo.full_name
        gh_organization = repo.organization
        repo_name: str = gh_full_name.split('/')[1]
        gh_owner_name: str = gh_full_name.split('/')[0]

        construct_prefix = False

        if gh_organization:
            gitea_account = self.gitea_main
            gitea_entity = self.find_org_from_gitea(gh_organization)
        else:
            gitea_account = self.gitea_clone
            gitea_entity = self._user
            construct_prefix = True

        if self.github_username in gh_full_name:
            gitea_account = self.gitea_main
            gitea_entity = self._main_user
            construct_prefix = False

        if self._find_repo_in_entity(
            gitea_entity,
            gh_owner_name,
            repo_name,
            bool(gh_organization),
            construct_prefix,
        ):
            logger.info('Repo already exists: %s', gh_full_name)
            return

        if construct_prefix:
            repo_name = f'{gh_owner_name}_{repo_name}'

        repo_owner = (
            gitea_entity.name
            if isinstance(gitea_entity, Organization)
            else gitea_entity.login_name
        )

        try:
            Repository.migrate_repo(
                gitea_account,
                service=MigrationServices.GITHUB,
                clone_addr=repo.clone_url,
                repo_name=repo_name,
                description=(
                    repo.description[:255] if repo.description else 'No Description'
                ),
                auth_token=self.github_token,
                auth_username=self.github_username,
                mirror=mirror,
                private=repo.private,
                wiki=True,
                labels=True,
                issues=True,
                pull_requests=True,
                milestones=True,
                repo_owner=repo_owner,
            )
            logger.info('Mirrored: %s -> %s', gh_full_name, repo_name)
        except AlreadyExistsException:
            logger.info('Repo already exists (caught on migrate): %s', repo_name)
        except Exception:
            logger.exception('Failed to mirror repo: %s', gh_full_name)

    def _find_repo_in_entity(
        self,
        gitea_entity: Any,
        gh_owner_name: str,
        new_repo_name: str,
        is_gh_organization: bool,
        construct_prefix: bool,
    ) -> bool:
        cache_key = gitea_entity.username
        if cache_key not in self._repo_cache:
            self._repo_cache[cache_key] = [
                repo.get_full_name() for repo in gitea_entity.get_repositories()
            ]

        repos = self._repo_cache[cache_key]

        if is_gh_organization or not construct_prefix:
            needle = f'{gh_owner_name}/{new_repo_name}'
        else:
            needle = f'{gh_owner_name}_{new_repo_name}'

        return needle in repos

    def mirror_repos_batch(
        self, repos: list[Any], *, mirror: bool = True, workers: int = 5
    ) -> tuple[int, int]:
        tasks: list[_MirrorTask] = []
        skipped = 0

        for repo in repos:
            task = self._prepare_mirror(repo, mirror=mirror)
            if task is None:
                skipped += 1
            else:
                tasks.append(task)

        mirrored = 0
        if not tasks:
            return mirrored, skipped

        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_to_task: dict[Future[None], _MirrorTask] = {
                pool.submit(self._execute_mirror, task): task for task in tasks
            }
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    future.result()
                    mirrored += 1
                except AlreadyExistsException:
                    logger.info('Repo already exists: %s', task.repo_name)
                    skipped += 1
                except Exception:
                    logger.exception('Failed to mirror repo: %s', task.gh_full_name)
                    skipped += 1

        return mirrored, skipped

    def _prepare_mirror(self, repo: Any, *, mirror: bool = True) -> _MirrorTask | None:
        gh_full_name: str = repo.full_name
        gh_organization = repo.organization
        repo_name: str = gh_full_name.split('/')[1]
        gh_owner_name: str = gh_full_name.split('/')[0]

        construct_prefix = False

        if gh_organization:
            gitea_account = self.gitea_main
            gitea_entity = self.find_org_from_gitea(gh_organization)
        else:
            gitea_account = self.gitea_clone
            gitea_entity = self._user
            construct_prefix = True

        if self.github_username in gh_full_name:
            gitea_account = self.gitea_main
            gitea_entity = self._main_user
            construct_prefix = False

        if self._find_repo_in_entity(
            gitea_entity,
            gh_owner_name,
            repo_name,
            bool(gh_organization),
            construct_prefix,
        ):
            logger.info('Repo already exists: %s', gh_full_name)
            return None

        if construct_prefix:
            repo_name = f'{gh_owner_name}_{repo_name}'

        repo_owner = (
            gitea_entity.name
            if isinstance(gitea_entity, Organization)
            else gitea_entity.login_name
        )

        return _MirrorTask(
            gitea_account=gitea_account,
            clone_url=repo.clone_url,
            repo_name=repo_name,
            description=(
                repo.description[:255] if repo.description else 'No Description'
            ),
            mirror=mirror,
            private=repo.private,
            repo_owner=repo_owner,
            gh_full_name=gh_full_name,
            github_token=self.github_token,
            github_username=self.github_username,
        )

    @staticmethod
    def _execute_mirror(task: _MirrorTask) -> None:
        Repository.migrate_repo(
            task.gitea_account,
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
    gitea_account: Any
    clone_url: str
    repo_name: str
    description: str
    mirror: bool
    private: bool
    repo_owner: str
    gh_full_name: str
    github_token: str
    github_username: str
