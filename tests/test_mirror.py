from __future__ import annotations

import io
import threading
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gitea import AlreadyExistsException
from tqdm import tqdm

from gitea_mirror import CFGitea, GithubToGitea
from gitea_mirror.cli import main
from gitea_mirror.mirror import DEFAULT_WORKERS


def repo(full_name: str, **kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(
        full_name=full_name,
        organization=kwargs.get('organization'),
        clone_url=f'https://github.invalid/{full_name}.git',
        description='description' * 30,
        private=True,
    )


class MirrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clients: list[CFGitea] = []
        self.entities = {
            username: SimpleNamespace(
                username=username, get_repositories=Mock(return_value=[])
            )
            for username in ('gitea-me', 'clones')
        }
        clients = self.clients
        entities = self.entities

        class OfflineGitea(CFGitea):
            def __init__(self, *args: object, **kwargs: object) -> None:
                super().__init__(*args, **kwargs)
                self.requests.close = Mock(wraps=self.requests.close)
                clients.append(self)

            def get_user(self) -> SimpleNamespace:
                token = self.headers['Authorization']
                return entities['gitea-me' if token == 'token main' else 'clones']

        with patch('gitea_mirror.mirror.Github'):
            self.mirror = GithubToGitea(
                'https://gitea.invalid',
                'main',
                'clone',
                'me',
                'github-token',
                gitea_client_class=OfflineGitea,
                gitea_client_kwargs={
                    'cf_access_client_id': 'cf-id',
                    'cf_access_client_secret': 'cf-secret',
                },
            )
        migration_patch = patch('gitea_mirror.mirror.Repository.migrate_repo')
        self.migrate = migration_patch.start()
        self.addCleanup(migration_patch.stop)

    def test_default_workers_overlap_and_use_separate_sessions(self) -> None:
        # Every request must start before any can finish. A sequential executor
        # or a pool smaller than the default breaks the barrier.
        barrier = threading.Barrier(DEFAULT_WORKERS, timeout=5)

        def migrate(client: CFGitea, **kwargs: object) -> None:
            barrier.wait()

        self.migrate.side_effect = migrate
        repos = [repo(f'me/project-{i}') for i in range(DEFAULT_WORKERS)]
        self.assertEqual(self.mirror.mirror_repos_batch(repos), (DEFAULT_WORKERS, 0))
        workers = self.clients[2:]
        self.assertEqual(
            len({id(client.requests) for client in workers}), DEFAULT_WORKERS
        )
        for client in workers:
            self.assertEqual(client.headers['Authorization'], 'token main')
            self.assertEqual(client.headers['CF-Access-Client-Id'], 'cf-id')
            self.assertEqual(client.headers['CF-Access-Client-Secret'], 'cf-secret')
            client.requests.close.assert_called_once()

    def test_existing_repos_and_completed_migrations_are_cached(self) -> None:
        for owner, full_name in (
            ('gitea-me', 'Gitea-Me/Existing'),
            ('clones', 'clones/Other_Existing'),
        ):
            self.entities[owner].get_repositories.return_value = [
                SimpleNamespace(get_full_name=lambda name=full_name: name)
            ]

        repos = [repo('me/existing'), repo('other/existing'), repo('other/new')]
        self.assertEqual(self.mirror.mirror_repos_batch(repos), (1, 2))
        self.assertEqual(self.mirror.mirror_repos_batch(repos), (0, 3))
        self.migrate.assert_called_once()
        for entity in self.entities.values():
            entity.get_repositories.assert_called_once()

    def test_prefix_and_exact_ownership_with_sequential_cloning(self) -> None:
        repos = [repo('someone/tool'), repo('other/me-tool'), repo('ME/tool')]
        self.assertEqual(
            self.mirror.mirror_repos_batch(repos, mirror=False, workers=1), (3, 0)
        )
        calls = self.migrate.call_args_list
        self.assertEqual(
            [(call.kwargs['repo_owner'], call.kwargs['repo_name']) for call in calls],
            [
                ('clones', 'someone_tool'),
                ('clones', 'other_me-tool'),
                ('gitea-me', 'tool'),
            ],
        )
        for call in calls:
            self.assertFalse(call.kwargs['mirror'])
            self.assertTrue(call.kwargs['private'])
            self.assertEqual(len(call.kwargs['description']), 255)

    def test_failures_do_not_stop_batch_or_count_as_existing(self) -> None:
        bars = []

        def progress(*args: object, **kwargs: object) -> tqdm:
            kwargs.update(file=io.StringIO(), disable=False)
            bar = tqdm(*args, **kwargs)
            bars.append(bar)
            return bar

        def migrate(client: CFGitea, **kwargs: object) -> None:
            if kwargs['repo_name'] == 'exists':
                raise AlreadyExistsException()
            if kwargs['repo_name'] == 'failed':
                raise RuntimeError('offline failure')

        self.migrate.side_effect = migrate
        broken = SimpleNamespace(full_name='broken')
        repos = [repo('me/exists'), repo('me/failed'), broken, repo('me/ok')]
        with (
            patch('gitea_mirror.mirror.tqdm', side_effect=progress),
            self.assertLogs('gitea_mirror.mirror', level='ERROR') as logs,
        ):
            self.assertEqual(self.mirror.mirror_repos_batch(repos), (1, 1))

        self.assertIn('2 repositories failed', '\n'.join(logs.output))
        self.assertEqual(bars[-1].n, len(repos))
        self.assertIn('mirrored=1', bars[-1].postfix)
        self.assertIn('skipped=1', bars[-1].postfix)
        self.assertIn('failed=2', bars[-1].postfix)
        for client in self.clients[2:]:
            client.requests.close.assert_called_once()

        # Failed migrations remain eligible for retry.
        self.migrate.side_effect = None
        self.assertEqual(self.mirror.mirror_repos_batch([repo('me/failed')]), (1, 0))

    def test_organization_is_created_once_before_migrations(self) -> None:
        github_org = SimpleNamespace(login='team', description=None)
        gitea_org = SimpleNamespace(
            username='team',
            name='Team Display Name',
            get_repositories=Mock(return_value=[]),
        )
        creating_thread = threading.get_ident()

        def create_org(**kwargs: object) -> None:
            self.assertEqual(threading.get_ident(), creating_thread)
            self.migrate.assert_not_called()

        self.mirror.gitea_main.get_orgs = Mock(side_effect=[[], [gitea_org]])
        self.mirror.gitea_main.create_org = Mock(side_effect=create_org)
        repos = [repo(f'team/project-{i}', organization=github_org) for i in range(3)]
        self.assertEqual(self.mirror.mirror_repos_batch(repos), (3, 0))
        self.mirror.gitea_main.create_org.assert_called_once()
        for call in self.migrate.call_args_list:
            self.assertEqual(call.kwargs['repo_owner'], 'team')
            self.assertEqual(call.args[0].headers['Authorization'], 'token main')

    def test_empty_batch_and_duplicate_targets(self) -> None:
        self.assertEqual(self.mirror.mirror_repos_batch([]), (0, 0))
        self.migrate.assert_not_called()
        self.assertEqual(
            self.mirror.mirror_repos_batch([repo('me/tool'), repo('ME/TOOL')]), (1, 1)
        )
        self.migrate.assert_called_once()

    def test_single_repo_search_path_updates_cache(self) -> None:
        self.mirror.create_repo_mirror(repo('me/tool'), mirror=False)
        self.mirror.create_repo_mirror(repo('me/tool'))
        self.migrate.assert_called_once()
        self.assertFalse(self.migrate.call_args.kwargs['mirror'])

    def test_invalid_worker_count(self) -> None:
        for workers in (0, -1):
            with self.subTest(workers=workers), self.assertRaises(ValueError):
                self.mirror.mirror_repos_batch([], workers=workers)


class CLITests(unittest.TestCase):
    def test_batch_worker_defaults_and_override(self) -> None:
        for command in ('stars', 'owned', 'org'):
            args = [command, 'team'] if command == 'org' else [command]
            for options, expected in (([], DEFAULT_WORKERS), (['--workers', '1'], 1)):
                with self.subTest(command=command, options=options):
                    with patch(f'gitea_mirror.cli.cmd_{command}') as handler:
                        main(args + options)
                    self.assertEqual(handler.call_args.args[0].workers, expected)

    def test_invalid_workers_rejected_before_connecting(self) -> None:
        for command in ('stars', 'owned', 'org'):
            args = [command, 'team'] if command == 'org' else [command]
            for workers in ('0', '-1', 'invalid'):
                with (
                    self.subTest(command=command, workers=workers),
                    patch('gitea_mirror.cli._create_gitea') as create,
                    redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as error,
                ):
                    main(args + ['--workers', workers])
                self.assertEqual(error.exception.code, 2)
                create.assert_not_called()


if __name__ == '__main__':
    unittest.main()
