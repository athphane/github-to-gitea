import configparser
import sys

from core.github_to_gitea import GithubToGitea

config = configparser.ConfigParser()
config.read('config.ini')

gitea = GithubToGitea(
    config.get('gitea', 'host'),
    config.get('gitea', 'token_main_account'),
    config.get('gitea', 'token_clone_account'),
    config.get('github', 'username'),
    config.get('github', 'token')
)

if __name__ == '__main__':
    organization_name = None

    if len(sys.argv) > 1:
        # Assume the first parameter on the CLI to be the organization name
        organization_name = sys.argv[1]

    if organization_name:
        organization = gitea.github.get_organization(organization_name)
        count = 0
        for repo in organization.get_repos():
            print(f"{count}. {repo.name} - MIRRORING")
            gitea.create_repo_mirror(repo)
            count = count + 1

        print(f"Mirrored {count} repositories from {organization_name}")
