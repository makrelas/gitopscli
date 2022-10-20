import imp
import logging
import os
from dataclasses import dataclass
from typing import Any
from gitopscli.git_api import GitApiConfig, GitRepo, GitRepoApiFactory
from gitopscli.io_api.yaml_util import merge_yaml_element, yaml_file_load, yaml_load
from gitopscli.gitops_exception import GitOpsException
from .command import Command
from gitopscli.appconfig_api.app_tenant_config import AppTenantConfig
from gitopscli.appconfig_api.root_repo import RootRepo
from gitopscli.appconfig_api.traverse_config import traverse_config


#TODO: Custom config reader
#TODO: Test custom config read, creation of objects AppTenantConfig and RootRepo

class SyncAppsCommand(Command):
    @dataclass(frozen=True)
    class Args(GitApiConfig):
        git_user: str
        git_email: str

        organisation: str
        repository_name: str

        root_organisation: str
        root_repository_name: str

    def __init__(self, args: Args) -> None:
        self.__args = args

    def execute(self) -> None:
        _sync_apps_command(self.__args)

def _sync_apps_command(args: SyncAppsCommand.Args) -> None:
    team_config_git_repo_api = GitRepoApiFactory.create(args, args.organisation, args.repository_name)
    root_config_git_repo_api = GitRepoApiFactory.create(args, args.root_organisation, args.root_repository_name)
    with GitRepo(team_config_git_repo_api) as team_config_git_repo:
        with GitRepo(root_config_git_repo_api) as root_config_git_repo:
            __sync_apps(team_config_git_repo, root_config_git_repo, args.git_user, args.git_email)


def __sync_apps(team_config_git_repo: GitRepo, root_config_git_repo: GitRepo, git_user: str, git_email: str) -> None:
    logging.info("Team config repository: %s", team_config_git_repo.get_clone_url())
    logging.info("Root config repository: %s", root_config_git_repo.get_clone_url())
    team_config_app_name = team_config_git_repo.get_clone_url().split("/")[-1].removesuffix(".git")
    rr=RootRepo(root_config_git_repo)
    tenant_config_team_repo=AppTenantConfig("team",config_source_repository=team_config_git_repo)

    
    #dict conversion causes YAML object to be unordered
    tenant_config_repo_apps = dict(tenant_config_team_repo.list_apps())
    if not team_config_app_name in list(rr.tenant_list.keys()):
        raise GitOpsException("Couldn't find config file for apps repository in root repository's 'apps/' directory")
    current_repo_apps = dict(rr.tenant_list[team_config_app_name].list_apps())

    apps_from_other_repos = rr.app_list.copy()
    apps_from_other_repos.pop(team_config_app_name)
    for app in list(tenant_config_repo_apps.keys()):
        for tenant in apps_from_other_repos.values():
            if app in tenant:
                raise GitOpsException(f"Application '{app}' already exists in a different repository")

    logging.info("Found %s app(s) in apps repository: %s", len(tenant_config_repo_apps), ", ".join(tenant_config_repo_apps))
    logging.info("Searching apps repository in root repository's 'apps/' directory...")

    apps_config_file = rr.tenant_list[team_config_app_name].file_path
    apps_config_file_name = rr.tenant_list[team_config_app_name].file_name
    #TODO FIX VALUE TO DIFFER BETWEEN OLD/NEW STYLE
    found_apps_path = "config.applications"

    #removing all keys not being current app repo in order to compare app lists excluding keys added by root repo administrator, to be figured out how to handle that better
    for app in list(current_repo_apps.keys()):
        if current_repo_apps.get(app, dict()) is not None:
            for key in list(current_repo_apps.get(app, dict())):
                if key != "customAppConfig":
                    del current_repo_apps[app][key]
    #TODO: validate if all changes do key values trigger difference
    if current_repo_apps == tenant_config_repo_apps:
        logging.info("Root repository already up-to-date. I'm done here.")
        return

    logging.info("Sync applications in root repository's %s.", apps_config_file_name)
    merge_yaml_element(
        apps_config_file,
        found_apps_path,
        {repo_app: traverse_config(tenant_config_team_repo.data, tenant_config_team_repo.config_api_version).get(repo_app, "{}") for repo_app in tenant_config_repo_apps},
    )

    __commit_and_push(team_config_git_repo, root_config_git_repo, git_user, git_email, apps_config_file_name)


def __commit_and_push(
    team_config_git_repo: GitRepo, root_config_git_repo: GitRepo, git_user: str, git_email: str, app_file_name: str
) -> None:
    author = team_config_git_repo.get_author_from_last_commit()
    root_config_git_repo.commit(git_user, git_email, f"{author} updated " + app_file_name)
    root_config_git_repo.push()