from __future__ import annotations

import argparse
import logging

from gitea_mirror import CFGitea, Config, GithubToGitea

logger = logging.getLogger(__name__)
_SEARCH_LIMIT = 10


def _create_gitea(config: Config) -> GithubToGitea:
    common: dict = {
        'gitea_url': config.gitea_host,
        'gitea_token_main': config.gitea_token_main,
        'gitea_token_clone': config.gitea_token_clone,
        'github_username': config.github_username,
        'github_token': config.github_token,
    }
    if config.cf_client_id and config.cf_client_secret:
        common['gitea_client_class'] = CFGitea
        common['gitea_client_kwargs'] = {
            'cf_access_client_id': config.cf_client_id,
            'cf_access_client_secret': config.cf_client_secret,
        }
    return GithubToGitea(**common)


def cmd_stars(args: argparse.Namespace) -> None:
    config = Config.from_ini(args.config, section=args.section)
    gitea = _create_gitea(config)

    logger.info('Gitea version: %s', gitea.gitea_clone.get_version())
    logger.info('API token belongs to user: %s', gitea.user.username)

    repos = [repo for repo in gitea.github.get_user().get_starred() if not repo.fork]

    mirrored, skipped = gitea.mirror_repos_batch(
        repos, mirror=args.mirror, workers=args.workers
    )
    logger.info(
        'Mirrored %d repositories from your GitHub Stars (%d already existed).',
        mirrored,
        skipped,
    )


def cmd_owned(args: argparse.Namespace) -> None:
    config = Config.from_ini(args.config, section=args.section)
    gitea = _create_gitea(config)

    logger.info('Gitea version: %s', gitea.gitea_clone.get_version())
    logger.info('API token belongs to user: %s', gitea.user.username)

    repos = [
        repo
        for repo in gitea.github.get_user().get_repos()
        if repo.owner.login == config.github_username
    ]

    mirrored, skipped = gitea.mirror_repos_batch(
        repos, mirror=args.mirror, workers=args.workers
    )
    logger.info(
        'Mirrored %d repositories owned by %s (%d already existed).',
        mirrored,
        config.github_username,
        skipped,
    )


def cmd_org(args: argparse.Namespace) -> None:
    config = Config.from_ini(args.config, section=args.section)
    gitea = _create_gitea(config)

    org = gitea.github.get_organization(args.org_name)
    repos = list(org.get_repos())

    mirrored, skipped = gitea.mirror_repos_batch(
        repos, mirror=args.mirror, workers=args.workers
    )
    logger.info(
        'Mirrored %d new repositories from %s (%d already existed).',
        mirrored,
        args.org_name,
        skipped,
    )


def cmd_search(args: argparse.Namespace) -> None:
    from prettytable import PrettyTable

    config = Config.from_ini(args.config, section=args.section)
    gitea = _create_gitea(config)

    while True:
        query = input('Enter the repo name...\n> ')
        results = list(gitea.github.search_repositories(query)[: args.limit])

        table = PrettyTable()
        table.title = 'Github Repo Search Results'
        table.field_names = ['IDX', 'Repo']
        table.align = 'l'
        for i, repo in enumerate(results):
            table.add_row([i, repo.full_name])
        print(table)

        idx = int(input('Select target repo from list...\n> '))
        selected = results[idx]
        logger.info('Selected: %s', selected.full_name)

        if _yes_or_no('Do you want to clone this to your Gitea instance?'):
            want_mirror = _yes_or_no('Do you want it to be a mirror?')
            logger.info('%s...', 'Mirroring' if want_mirror else 'Cloning')
            gitea.create_repo_mirror(selected, mirror=want_mirror)
            break

    logger.info('Done.')


def _yes_or_no(question: str) -> bool:
    reply = input(f'{question} (Y/n)\n> ').strip().lower()
    if reply.startswith('y'):
        return True
    if reply.startswith('n'):
        return False
    return _yes_or_no('Please enter Y or n... ')


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog='gitea-mirror',
        description='Mirror GitHub repositories to a Gitea instance',
    )
    parser.add_argument(
        '--config',
        default='config.ini',
        help='Path to config.ini (default: config.ini)',
    )
    parser.add_argument(
        '--section',
        default='gitea',
        help="Config section for Gitea credentials (default: 'gitea')",
    )
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')

    subs = parser.add_subparsers(dest='command', required=True)

    p_stars = subs.add_parser('stars', help='Mirror all starred GitHub repos')
    p_stars.add_argument(
        '--no-mirror',
        dest='mirror',
        action='store_false',
        default=True,
        help='Clone without mirroring',
    )
    p_stars.add_argument(
        '--workers',
        type=int,
        default=1,
        metavar='N',
        help='Concurrent mirror workers (default: 1, sequential)',
    )
    p_stars.set_defaults(func=cmd_stars)

    p_owned = subs.add_parser('owned', help='Mirror repos owned by your GitHub user')
    p_owned.add_argument(
        '--no-mirror',
        dest='mirror',
        action='store_false',
        default=True,
        help='Clone without mirroring',
    )
    p_owned.add_argument(
        '--workers',
        type=int,
        default=1,
        metavar='N',
        help='Concurrent mirror workers (default: 1, sequential)',
    )
    p_owned.set_defaults(func=cmd_owned)

    p_org = subs.add_parser('org', help='Mirror all repos from a GitHub organization')
    p_org.add_argument('org_name', help='GitHub organization name')
    p_org.add_argument(
        '--no-mirror',
        dest='mirror',
        action='store_false',
        default=True,
        help='Clone without mirroring',
    )
    p_org.add_argument(
        '--workers',
        type=int,
        default=1,
        metavar='N',
        help='Concurrent mirror workers (default: 1, sequential)',
    )
    p_org.set_defaults(func=cmd_org)

    p_search = subs.add_parser('search', help='Interactive search and mirror')
    p_search.add_argument(
        '--limit',
        type=int,
        default=_SEARCH_LIMIT,
        help=f'Max search results to display (default: {_SEARCH_LIMIT})',
    )
    p_search.set_defaults(func=cmd_search)

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )

    args.func(args)


if __name__ == '__main__':
    main()
