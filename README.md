## Github To Gitea Cloning Scripts
> Clone and mirror all the repos!

I started to host my own [Gitea](https://github.com/go-gitea/gitea) server and wanted a way to easily 'syncronize' the repos I have to my own
Gitea server. 

If you want to deploy your own Gitea server, you can follow Gitea's own 
Docker Installation Guide [here](https://docs.gitea.io/en-us/install-with-docker/)

### Setting it up
**Environment Variables**
This application uses a config.ini file for its environment variables. You can rename the 
[config.ini.example](config.ini.example) to config.ini and fill in the values as below.
        
Key | Value
------------ | -------------
gitea.host | The hostname to your Gitea instance. (https://git.domain.com)
gitea.token_main_account | Access token for your main Gitea account.
gitea.token_clone_account | Access token for your clone Gitea account.
github.username | Your Github username. Eg: athphane.
github.token | Your Gituhb Personal Access Token, which you can get from [here](https://github.com/settings/tokens/new).

**What is this Main and Clone account? Why do I need two account?**
    
I personally do not want my own Gitea account to be the owner of all the cloned/mirrored repositories.

My main account is 'athphane' and I would like to only clone repos I own to this account, so that it is a sort of one to one copy from Github.

So that is why I have a secondary account called 'athphane-clone' that will own all cloned/mirrored repositories that are of another `user` from Github.

Note how I mention `user` above. That is because if the script is cloning/mirroring a repository that is owned by an organization, it will create the Organization on Gitea if it does not exist, add my Main Account (athphane) as the organization owner and clone the repo into the Organization. Doesn't make sense? Just try it out and you'll see what I mean.

You can get your gitea access tokens from https://git.domain.com/user/settings/applications. Make sure to get one for both users.

**Using It**

There are a couple of scripts included here. 
1. [clone_github_stars.py](scripts/clone_github_stars.py)
2. [interactive.py](scripts/interactive.py)
3. [scrape_organization.py](scripts/scrape_organization.py)
   

The first script will run all on its own. It will go through your Github Stars and attempt to clone each repository into Gitea.
```bash
python scripts/clone_github_stars.py
```    

The second script is an interactive script. You can enter the name of the repository you want to clone, and it will search Github to find any matches. You will be presented with a list of matches and can select what repo to actually clone.
```bash
python scripts/interactive.py
```    

The third script accepts 1 argument. This argument is the name of the organization you want to scrape.
```bash
python scripts/scrape_ogranization.py spatie
```    

## Pro tip
In your Gitea administration panel, you can add webhook notifications for a number of services. 
I personally use Telegram and have a bot that sends me a notification every time a new repository is created on the system. 
This is useful if you want to make sure your repositories are being cloned.

## Future plans
- [ ] Create interactive Telegram bot where all of this can be done remotely.
- [ ] Add a search function to [scrape_organization.py](scripts/scrape_organization.py) so that not every single repository gets cloned

## Credits
- [Athfan Khaleel (@athphane)](https://athfan.com)

---
<p align="center">Made with love from the Maldives ❤</p>