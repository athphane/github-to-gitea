import configparser

from github.GithubException import GithubException

from core.github_to_gitea import GithubToGitea

if __name__ == '__main__':
    config = configparser.ConfigParser()
    config.read('config.ini')

    gitea = GithubToGitea(
        config.get('gitea', 'host'),
        config.get('gitea', 'token_main_account'),
        config.get('gitea', 'token_clone_account'),
        config.get('github', 'username'),
        config.get('github', 'token'),
    )

    print(f"Gitea Version: {gitea.gitea_clone_account.get_version()}")
    print(f"API-Token belongs to user: {gitea.user.username}")

    # Get all repos from my Github Account
    count = 0

    for repo in gitea.github.get_user().get_starred():
        if repo.fork:
            print('Is fork')

        try:
            print(f"{count} - {repo.full_name} - MIRRORING")
            gitea.create_repo_mirror(repo)
            count += 1
        except GithubException as E:
            print('There was an error with this repo?')

    print(f"Mirrored {count} NEW repositories from your Github Stars.")
