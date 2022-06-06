import configparser

from prettytable import PrettyTable

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

searched_repos = []
_limit_search_results_to = 10


def search_for_repos(query):
    global searched_repos

    search_results = gitea.github.search_repositories(query)[:_limit_search_results_to]
    searched_repos = [x for x in search_results]


def search_for_repos_in_organization(query):
    global searched_repos

    organization = gitea.github.get_organization(query)
    search_results = organization.get_repos()[:10]

    searched_repos = [x for x in search_results]


def format_repo_list():
    ac = PrettyTable()
    # ac.header = False
    ac.title = "Github Repo Search Results"
    ac.field_names = ['IDX', 'Repo']

    for i, x in enumerate(searched_repos):
        ac.add_row([i, x.full_name])

    ac.align = "l"
    print(ac)


def yes_or_no(question):
    reply = str(input(question + ' (Y/n)\n> ')).lower().strip()
    if reply[0] == 'y':
        return True
    if reply[0] == 'n':
        return False
    else:
        return yes_or_no("Uhhhh... please enter ")


if __name__ == '__main__':
    does_want_to_clone = False
    while True:
        search_term = input('Enter the repo name...\n> ')
        search_for_repos(search_term)
        format_repo_list()

        selected_repo = int(input('Select target repo from list...\n> '))
        selected_repo = searched_repos[selected_repo]
        print(f"Selected: {selected_repo.full_name}")

        if yes_or_no('Do you want to clone this to your Gitea instance?'):
            if yes_or_no('Do you want it to be a mirror?'):
                print('Mirroring...')
                gitea.create_repo_mirror(selected_repo)

            else:
                print('Cloning...')
                gitea.create_repo_mirror(selected_repo, False)

            break

        print('Done...')
