import logging
import os
from dataclasses import dataclass
from typing import Any, Set, Tuple, List, Dict
from gitopscli.git_api import GitApiConfig, GitRepo, GitRepoApiFactory
from gitopscli.io_api.yaml_util import merge_yaml_element, yaml_file_load, yaml_load
from gitopscli.gitops_exception import GitOpsException
from .command import Command
from ruamel.yaml import YAML 


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
class AppTenantConfig: 
    config_type: str #is instance initialized as config located in root/team repo
    data: YAML
    #schema important fields
    # config - entrypoint
    # config.repository - tenant repository url
    # config.applications - tenant applications list
    # config.applications.{}.userconfig - user configuration 
    name: str #tenant name
    config_source_repository: str #team tenant repository url
    user_config: dict #contents of custom_tenant_config.yaml in team repository
    file_path: str
    file_name: str
    def __init__(self, config_type, config_source_repository=None, data=None, name=None, file_path=None, file_name=None):
        self.config_type = config_type
        if self.config_type == "root":
            self.data = data
            self.config_source_repository = config_source_repository
            self.name = name
            self.user_config = None
            self.file_path = file_path
            self.file_name = file_name
        elif self.config_type == "team":
            self.config_source_repository = config_source_repository
            self.config_source_repository.clone()
            self.data = self.generate_config_from_team_repo()
            self.name = name
            #self.user_config = self.get_custom_config()
            self.user_config = None

    def generate_config_from_team_repo(self):   
        #recognize type of repo
        team_config_git_repo = self.config_source_repository
        repo_dir = team_config_git_repo.get_full_file_path(".")
        applist = {
            name
            for name in os.listdir(repo_dir)
            if os.path.isdir(os.path.join(repo_dir, name)) and not name.startswith(".")
        }
        template_yaml = '''
        config: 
          repository: {}
          applications: []
        '''.format(team_config_git_repo.get_clone_url())
        data = yaml_load(template_yaml)
        data["config"]["applications"] = applist
        return data


    def get_custom_config(self):
        team_config_git_repo = self.config_source_repository
        try:
            custom_config_file = team_config_git_repo.get_full_file_path("app_value_file.yaml")
        except: 
            #handle missing file
            #handle broken file
            pass
        return yaml_file_load(custom_config_file)
    def list_apps(self):
        return self.data["config"]["applications"]
    def add_app(self):
        #adds app to the app tenant config
        pass
    def modify_app(self):
        #modifies existing app in tenant config
        pass
    def delete_app(self):
        #deletes app from tenant config
        pass
@dataclass
class RootRepo:
    name: str #root repository name
    tenant_list: dict #TODO of AppTenantConfig #list of the tenant configs in the root repository (in apps folder)
    bootstrap: set #list of tenants to be bootstrapped, derived form values.yaml in bootstrap root repo dict   
    app_list: set #llist of apps without custormer separation
    
    def __init__(self, root_config_git_repo: GitRepo):
        repo_clone_url = root_config_git_repo.get_clone_url()
        root_config_git_repo.clone()
        bootstrap_values_file = root_config_git_repo.get_full_file_path("bootstrap/values.yaml")
        self.bootstrap = self.__get_bootstrap_entries(bootstrap_values_file)
        self.name = repo_clone_url.split("/")[-1].removesuffix(".git")
        self.tenant_list = self.__generate_tenant_app_dict(root_config_git_repo)
        self.app_list = self.__get_all_apps_list()
    
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
        
    def __generate_tenant_app_dict(self, root_config_git_repo: GitRepo):
        tenant_app_dict = {}
        for bootstrap_entry in self.bootstrap:
            tenant_apps_config_file_name = "apps/" + bootstrap_entry["name"] + ".yaml"
            logging.info("Analyzing %s in root repository", tenant_apps_config_file_name)
            tenant_apps_config_file = root_config_git_repo.get_full_file_path(tenant_apps_config_file_name)
            try:
                tenant_apps_config_content = yaml_file_load(tenant_apps_config_file)
            except FileNotFoundError as ex:
                raise GitOpsException(f"File '{tenant_apps_config_file_name}' not found in root repository.") from ex
            #TODO exception handling for malformed yaml
            if "config" in tenant_apps_config_content:
                tenant_apps_config_content = tenant_apps_config_content["config"]
                found_apps_path = "config.applications"
            if "repository" not in tenant_apps_config_content:
                raise GitOpsException(f"Cannot find key 'repository' in '{tenant_apps_config_file_name}'")
            #if "config" in tenant_apps_config_content:
            logging.info("adding {}".format(bootstrap_entry["name"]))
            atc = AppTenantConfig(data=yaml_file_load(tenant_apps_config_file),name=bootstrap_entry["name"],config_type="root",file_path=tenant_apps_config_file,file_name=tenant_apps_config_file_name)
            tenant_app_dict.update({bootstrap_entry["name"] : atc })
        return tenant_app_dict

    def __get_all_apps_list(self):
        all_apps_list = []
        for tenant in self.tenant_list:
            all_apps_list.extend(list(dict(self.tenant_list[tenant].data["config"]["applications"]).keys()))
        return all_apps_list



def _sync_apps_command(args: SyncAppsCommand.Args) -> None:
    team_config_git_repo_api = GitRepoApiFactory.create(args, args.organisation, args.repository_name)
    root_config_git_repo_api = GitRepoApiFactory.create(args, args.root_organisation, args.root_repository_name)
    with GitRepo(team_config_git_repo_api) as team_config_git_repo:
        with GitRepo(root_config_git_repo_api) as root_config_git_repo:
            __sync_apps(team_config_git_repo, root_config_git_repo, args.git_user, args.git_email)


def __sync_apps(team_config_git_repo: GitRepo, root_config_git_repo: GitRepo, git_user: str, git_email: str) -> None:
    logging.info("Team config repository: %s", team_config_git_repo.get_clone_url())
    logging.info("Root config repository: %s", root_config_git_repo.get_clone_url())
    rr=RootRepo(root_config_git_repo)
    tenant_config_team_repo=AppTenantConfig("team",config_source_repository=team_config_git_repo)
    tenant_config_repo_apps = tenant_config_team_repo.list_apps()
    current_repo_apps = rr.tenant_list
    apps_from_other_repos = rr.app_list
    team_config_app_name = team_config_git_repo.get_clone_url().split("/")[-1].removesuffix(".git")
    #team_config_file_name = rr.tenant_list
    if len(apps_from_other_repos) != len(set(apps_from_other_repos)):
        logging.info("duplicate value found, veryfying")
        #TODO find which value is duplicate
        #raise GitOpsException(f"Application '{app_key}' already exists in a different repository")
    logging.info("Found %s app(s) in apps repository: %s", len(tenant_config_repo_apps), ", ".join(tenant_config_repo_apps))

    logging.info("Searching apps repository in root repository's 'apps/' directory...")
    #(
    #    apps_config_file,
    #    apps_config_file_name,
    #    found_apps_path,
    #) = __find_apps_config_from_repo(team_config_git_repo, root_config_git_repo)

    apps_config_file = rr.tenant_list[team_config_app_name].file_path
    apps_config_file_name = rr.tenant_list[team_config_app_name].file_name
    #TODO FIX VALUE
    found_apps_path = "config.applications"

    if current_repo_apps == tenant_config_repo_apps:
        logging.info("Root repository already up-to-date. I'm done here.")
        return

    #__check_if_app_already_exists(tenant_config_repo_apps, apps_from_other_repos)

    logging.info("Sync applications in root repository's %s.", apps_config_file_name)
    merge_yaml_element(
        apps_config_file,
        found_apps_path,
        {repo_app: __clean_repo_app(team_config_git_repo, repo_app) for repo_app in tenant_config_repo_apps},
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


#def __find_apps_config_from_repo(
#    team_config_git_repo: GitRepo, root_config_git_repo: GitRepo
#) -> Tuple[str, str, Set[str], Set[str], str]:
#    apps_from_other_repos: Set[str] = set()  # Set for all entries in .applications from each config repository
#    found_app_config_file = None
#    found_app_config_file_name = None
#    found_apps_path = "applications"
#    found_app_config_apps: Set[str] = set()
#    bootstrap_entries = __get_bootstrap_entries(root_config_git_repo)
#    team_config_git_repo_clone_url = team_config_git_repo.get_clone_url()
#    for bootstrap_entry in bootstrap_entries:
#        #moved to the root_repo bootstrap, not removing until whole function could be replaced 
##       if "name" not in bootstrap_entry:
#            raise GitOpsException("Every bootstrap entry must have a 'name' property.")
#        
#        app_file_name = "apps/" + bootstrap_entry["name"] + ".yaml"
#        logging.info("Analyzing %s in root repository", app_file_name)
#        app_config_file = root_config_git_repo.get_full_file_path(app_file_name)
#        try:
#            app_config_content = yaml_file_load(app_config_file)
#        except FileNotFoundError as ex:
#            raise GitOpsException(f"File '{app_file_name}' not found in root repository.") from ex
#        if "config" in app_config_content:
#            app_config_content = app_config_content["config"]
#            found_apps_path = "config.applications"
#        if "repository" not in app_config_content:
#            raise GitOpsException(f"Cannot find key 'repository' in '{app_file_name}'")
#        if app_config_content["repository"] == team_config_git_repo_clone_url:
#            logging.info("Found apps repository in %s", app_file_name)
#            found_app_config_file = app_config_file
#            found_app_config_file_name = app_file_name
#            found_app_config_apps = __get_applications_from_app_config(app_config_content)
#        else:
#            apps_from_other_repos.update(__get_applications_from_app_config(app_config_content))

#    if found_app_config_file is None or found_app_config_file_name is None:
#        raise GitOpsException(f"Couldn't find config file for apps repository in root repository's 'apps/' directory")
#       ##### 
#    return (
#        found_app_config_file,
#        found_app_config_file_name,
#        found_apps_path,
#    )


#def __get_applications_from_app_config(app_config: Any) -> Set[str]:
#    apps = []
#    if "applications" in app_config and app_config["applications"] is not None:
#        apps += app_config["applications"].keys()
#    return set(apps)


def __commit_and_push(
    team_config_git_repo: GitRepo, root_config_git_repo: GitRepo, git_user: str, git_email: str, app_file_name: str
) -> None:
    author = team_config_git_repo.get_author_from_last_commit()
    root_config_git_repo.commit(git_user, git_email, f"{author} updated " + app_file_name)
    root_config_git_repo.push()


# def __get_bootstrap_entries(root_config_git_repo: GitRepo) -> Any:
#     root_config_git_repo.clone()
#     bootstrap_values_file = root_config_git_repo.get_full_file_path("bootstrap/values.yaml")
#     try:
#         bootstrap_yaml = yaml_file_load(bootstrap_values_file)
#     except FileNotFoundError as ex:
#         raise GitOpsException("File 'bootstrap/values.yaml' not found in root repository.") from ex
#     if "bootstrap" not in bootstrap_yaml:
#         raise GitOpsException("Cannot find key 'bootstrap' in 'bootstrap/values.yaml'")
#     return bootstrap_yaml["bootstrap"]


# def __get_repo_apps(team_config_git_repo: GitRepo) -> Set[str]:
#     team_config_git_repo.clone()
#     repo_dir = team_config_git_repo.get_full_file_path(".")
#     return {
#         name
#         for name in os.listdir(repo_dir)
#         if os.path.isdir(os.path.join(repo_dir, name)) and not name.startswith(".")
#     }


#def __check_if_app_already_exists(apps_dirs: Set[str], apps_from_other_repos: Set[str]) -> None:
#    for app_key in apps_dirs:
#        if app_key in apps_from_other_repos:
#            raise GitOpsException(f"Application '{app_key}' already exists in a different repository")
