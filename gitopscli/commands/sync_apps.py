import logging
import os
from dataclasses import dataclass
from typing import Any, Set, Tuple, List, Dict

from jinja2 import TemplateAssertionError
from gitopscli.git_api import GitApiConfig, GitRepo, GitRepoApiFactory
from gitopscli.io_api.yaml_util import merge_yaml_element, yaml_file_load
from gitopscli.gitops_exception import GitOpsException
from .command import Command


YAML_BLACKLIST: List[str] = []


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
@dataclass
class AppConfig:
    name: str #appname
    config_type: str #is instance initialized as config located in root/team repo
    parent_tennant: str #which tenant app belongs to
    parent_repository: str #parent tenant team repo url
    user_config: dict #custom project configuration from tenant repo custom_tenant_config.yaml from team repo (only part containing the application instance, yaml location applications.{}.user_config
    status: bool #indicator if appconfig is currently synced (not entirely sure if this porperty brings value)
    admin_config: dict #application configuration obtained from root repository applications.{}, excluding user_config, empty when AppConfig object instance is initialized as team_repo app config
@dataclass
class AppTenantConfig: 
    name: str #tenant name
    app_list: set(AppConfig) #list of AppConfig objects owned by the tenant
    repository: str #team tenant repository url
    user_config: dict #contents of custom_tenant_config.yaml in team repository
    def list_apps(self):
        #lists apps contained in the config
        return
    def add_app(self):
        #adds app to the app tenant config
        return
    def modify_app(self):
        #modifies existing app in tenant config
        return
    def delete_app(self):
        #deletes app from tenant config
        return
@dataclass
class RootRepoTenant:
    name: str #tenant name
    tenant_config: dict #whole configuration of tenant
    app_list: AppTenantConfig #apps owned by tenant

@dataclass
class RootRepo:
    name: str #root repository name
    tenant_list: set(RootRepoTenant) #list of the tenant configs in the root repository (in apps folder)
    bootstrap: set #list of tenants to be bootstrapped, derived form values.yaml in bootstrap root repo dict   
    
    def __init__(self, root_config_git_repo: GitRepo):
        repo_clone_url = root_config_git_repo.get_clone_url()
        root_config_git_repo.clone()
        bootstrap_values_file = root_config_git_repo.get_full_file_path("bootstrap/values.yaml")
        self.bootstrap = self.__get_bootstrap_entries(bootstrap_values_file)
        self.name = repo_clone_url.split("/")[-1].removesuffix(".git")
        self.tenant_list = self.__generate_tenant_app_list

    def __get_bootstrap_entries(self, bootstrap_values_file: str) -> Any:
        try:
            bootstrap_yaml = yaml_file_load(bootstrap_values_file)
        except FileNotFoundError as ex:
            raise GitOpsException("File 'bootstrap/values.yaml' not found in root repository.") from ex
        if "bootstrap" not in bootstrap_yaml:
            raise GitOpsException("Cannot find key 'bootstrap' in 'bootstrap/values.yaml'")
        for bootstrap_entry in bootstrap_yaml["bootstrap"]:
            if "name" not in bootstrap_entry:
                raise GitOpsException("Every bootstrap entry must have a 'name' property.")
        return bootstrap_yaml["bootstrap"]
        
    def __generate_tenant_app_list(self, root_config_git_repo: GitRepo):
        #TODO rename tenant_app_config_* variables to differ apps config from single app config
        for bootstrap_entry in self.bootstrap:
            tenant_app_config_file_name = "apps/" + bootstrap_entry["name"] + ".yaml"
            logging.info("Analyzing %s in root repository", tenant_app_config_file_name)
            tenant_app_config_file = root_config_git_repo.get_full_file_path(tenant_app_config_file_name)
            try:
                tenant_app_config_content = yaml_file_load(tenant_app_config_file)
            except FileNotFoundError as ex:
                raise GitOpsException(f"File '{tenant_app_config_file_name}' not found in root repository.") from ex
            #TODO exception handling for malformed yaml
            if "repository" not in tenant_app_config_content:
                raise GitOpsException(f"Cannot find key 'repository' in '{tenant_app_config_file_name}'")
            if "config" in tenant_app_config_content:
                #TODO: change this var as well, confusing naming
                tenant_apps_config_content = tenant_app_config_content["config"]
                tenant_apps_config_object = AppTenantConfig(name=bootstrap_entry["name"],user_config=tenant_apps_config_content)
                for tenant_app_config in tenant_app_config_content["applications"]:
                    single_app_config = AppConfig(
                        name=tenant_app_config.key(),
                        config_type="root",
                        parent_tennant=tenant_apps_config_object.name,
                        parent_repository=tenant_apps_config_object.repository,
                        admin_config=tenant_app_config.value())
                    tenant_apps_config_object.add_app(single_app_config)


                #found_apps_path = "config.applications"
            #TODO: what that if/else is actually checking - and why
            #if tenant_app_config_content["repository"] == team_config_git_repo_clone_url:
                #logging.info("Found apps repository in %s", tenant_app_config_file_name)
                #found_app_config_file = app_config_file
                #found_app_config_file_name = app_file_name
                #found_app_config_apps = __get_applications_from_app_config(app_config_content)
            #else:
                #apps_from_other_repos.update(__get_applications_from_app_config(app_config_content))

        #if found_app_config_file is None or found_app_config_file_name is None:
            #raise GitOpsException(f"Couldn't find config file for apps repository in root repository's 'apps/' directory")




def _sync_apps_command(args: SyncAppsCommand.Args) -> None:
    team_config_git_repo_api = GitRepoApiFactory.create(args, args.organisation, args.repository_name)
    root_config_git_repo_api = GitRepoApiFactory.create(args, args.root_organisation, args.root_repository_name)
    with GitRepo(team_config_git_repo_api) as team_config_git_repo:
        with GitRepo(root_config_git_repo_api) as root_config_git_repo:
            __sync_apps(team_config_git_repo, root_config_git_repo, args.git_user, args.git_email)


def __sync_apps(team_config_git_repo: GitRepo, root_config_git_repo: GitRepo, git_user: str, git_email: str) -> None:
    logging.info("Team config repository: %s", team_config_git_repo.get_clone_url())
    logging.info("Root config repository: %s", root_config_git_repo.get_clone_url())

    repo_apps = __get_repo_apps(team_config_git_repo)
    logging.info("Found %s app(s) in apps repository: %s", len(repo_apps), ", ".join(repo_apps))

    logging.info("Searching apps repository in root repository's 'apps/' directory...")
    (
        apps_config_file,
        apps_config_file_name,
        current_repo_apps,
        apps_from_other_repos,
        found_apps_path,
    ) = __find_apps_config_from_repo(team_config_git_repo, root_config_git_repo)

    if current_repo_apps == repo_apps:
        logging.info("Root repository already up-to-date. I'm done here.")
        return

    __check_if_app_already_exists(repo_apps, apps_from_other_repos)

    logging.info("Sync applications in root repository's %s.", apps_config_file_name)
    merge_yaml_element(
        apps_config_file,
        found_apps_path,
        {repo_app: __clean_repo_app(team_config_git_repo, repo_app) for repo_app in repo_apps},
    )
    __commit_and_push(team_config_git_repo, root_config_git_repo, git_user, git_email, apps_config_file_name)


def __clean_yaml(values: Dict[str, Any]) -> Any:
    yml_result = values.copy()
    for key in values.keys():
        if key in YAML_BLACKLIST:
            logging.info("value %s removed", key)
            del yml_result[key]
        else:
            if isinstance(values[key], dict):
                yml_result[key] = __clean_yaml(values[key].copy())
    return yml_result


def __clean_repo_app(team_config_git_repo: GitRepo, app_name: str) -> Any:
    app_spec_file = team_config_git_repo.get_full_file_path(f"{app_name}/values.yaml")
    try:
        app_config_content = yaml_file_load(app_spec_file)
        return __clean_yaml(app_config_content)
    except FileNotFoundError as ex:
        logging.exception("no specific app settings file found for %s", app_name, exc_info=ex)
        return {}


def __find_apps_config_from_repo(
    team_config_git_repo: GitRepo, root_config_git_repo: GitRepo
) -> Tuple[str, str, Set[str], Set[str], str]:
    apps_from_other_repos: Set[str] = set()  # Set for all entries in .applications from each config repository
    found_app_config_file = None
    found_app_config_file_name = None
    found_apps_path = "applications"
    found_app_config_apps: Set[str] = set()
    bootstrap_entries = __get_bootstrap_entries(root_config_git_repo)
    team_config_git_repo_clone_url = team_config_git_repo.get_clone_url()
    for bootstrap_entry in bootstrap_entries:
        #moved to the root_repo bootstrap, not removing until whole function could be replaced 
        if "name" not in bootstrap_entry:
            raise GitOpsException("Every bootstrap entry must have a 'name' property.")
        
        app_file_name = "apps/" + bootstrap_entry["name"] + ".yaml"
        logging.info("Analyzing %s in root repository", app_file_name)
        app_config_file = root_config_git_repo.get_full_file_path(app_file_name)
        try:
            app_config_content = yaml_file_load(app_config_file)
        except FileNotFoundError as ex:
            raise GitOpsException(f"File '{app_file_name}' not found in root repository.") from ex
        if "config" in app_config_content:
            app_config_content = app_config_content["config"]
            found_apps_path = "config.applications"
        if "repository" not in app_config_content:
            raise GitOpsException(f"Cannot find key 'repository' in '{app_file_name}'")
        if app_config_content["repository"] == team_config_git_repo_clone_url:
            logging.info("Found apps repository in %s", app_file_name)
            found_app_config_file = app_config_file
            found_app_config_file_name = app_file_name
            found_app_config_apps = __get_applications_from_app_config(app_config_content)
        else:
            apps_from_other_repos.update(__get_applications_from_app_config(app_config_content))

    if found_app_config_file is None or found_app_config_file_name is None:
        raise GitOpsException(f"Couldn't find config file for apps repository in root repository's 'apps/' directory")
       ##### 
    return (
        found_app_config_file,
        found_app_config_file_name,
        found_app_config_apps,
        apps_from_other_repos,
        found_apps_path,
    )


def __get_applications_from_app_config(app_config: Any) -> Set[str]:
    apps = []
    if "applications" in app_config and app_config["applications"] is not None:
        apps += app_config["applications"].keys()
    return set(apps)


def __commit_and_push(
    team_config_git_repo: GitRepo, root_config_git_repo: GitRepo, git_user: str, git_email: str, app_file_name: str
) -> None:
    author = team_config_git_repo.get_author_from_last_commit()
    root_config_git_repo.commit(git_user, git_email, f"{author} updated " + app_file_name)
    root_config_git_repo.push()


def __get_bootstrap_entries(root_config_git_repo: GitRepo) -> Any:
    root_config_git_repo.clone()
    bootstrap_values_file = root_config_git_repo.get_full_file_path("bootstrap/values.yaml")
    try:
        bootstrap_yaml = yaml_file_load(bootstrap_values_file)
    except FileNotFoundError as ex:
        raise GitOpsException("File 'bootstrap/values.yaml' not found in root repository.") from ex
    if "bootstrap" not in bootstrap_yaml:
        raise GitOpsException("Cannot find key 'bootstrap' in 'bootstrap/values.yaml'")
    return bootstrap_yaml["bootstrap"]


def __get_repo_apps(team_config_git_repo: GitRepo) -> Set[str]:
    team_config_git_repo.clone()
    repo_dir = team_config_git_repo.get_full_file_path(".")
    return {
        name
        for name in os.listdir(repo_dir)
        if os.path.isdir(os.path.join(repo_dir, name)) and not name.startswith(".")
    }


def __check_if_app_already_exists(apps_dirs: Set[str], apps_from_other_repos: Set[str]) -> None:
    for app_key in apps_dirs:
        if app_key in apps_from_other_repos:
            raise GitOpsException(f"Application '{app_key}' already exists in a different repository")
