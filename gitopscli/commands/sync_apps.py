import logging
from dataclasses import dataclass
from gitopscli.git_api import GitApiConfig, GitRepo, GitRepoApiFactory
from gitopscli.io_api.yaml_util import merge_yaml_element
from gitopscli.gitops_exception import GitOpsException
from .command import Command


# from gitopscli.appconfig_api.app_tenant_config import AppTenantConfig
# from gitopscli.appconfig_api.root_repo import RootRepo
# from gitopscli.appconfig_api.traverse_config import traverse_config

###########################################################################################
######## TO BE REPLACED WITH IMPORT FROM appconfig_api
# TODO: Custom config reader
# TODO: Test custom config read, creation of objects AppTenantConfig and RootRepo
import os
from typing import Any
from dataclasses import dataclass
from ruamel.yaml import YAML
from gitopscli.appconfig_api.traverse_config import traverse_config
from gitopscli.io_api.yaml_util import yaml_file_load, yaml_load


@dataclass
class AppTenantConfig:
    # TODO: rethink objects and class initialization methods
    config_type: str  # is instance initialized as config located in root/team repo
    data: YAML
    # schema important fields
    # config - entrypoint
    # config.repository - tenant repository url
    # config.applications - tenant applications list
    # config.applications.{}.userconfig - user configuration
    name: str  # tenant name
    config_source_repository: str  # team tenant repository url
    # user_config: dict #contents of custom_tenant_config.yaml in team repository
    file_path: str
    file_name: str
    config_api_version: tuple

    def __init__(
        self, config_type, config_source_repository=None, data=None, name=None, file_path=None, file_name=None
    ):
        self.config_type = config_type
        self.config_source_repository = config_source_repository
        if self.config_type == "root":
            self.data = data
            self.file_path = file_path
            self.file_name = file_name
        elif self.config_type == "team":
            self.config_source_repository.clone()
            self.data = self.generate_config_from_team_repo()
        self.config_api_version = self.__get_config_api_version()
        self.name = name

    def __get_config_api_version(self):
        # maybe count the keys?
        if "config" in self.data.keys():
            return ("v2", ("config", "applications"))
        return ("v1", ("applications",))

    def generate_config_from_team_repo(self):
        # recognize type of repo
        team_config_git_repo = self.config_source_repository
        repo_dir = team_config_git_repo.get_full_file_path(".")
        applist = {
            name
            for name in os.listdir(repo_dir)
            if os.path.isdir(os.path.join(repo_dir, name)) and not name.startswith(".")
        }
        # TODO: Create YAML() object without writing template strings
        # Currently this is the easiest method, although it can be better
        template_yaml = """
        config: 
          repository: {}
          applications: {{}}
        """.format(
            team_config_git_repo.get_clone_url()
        )
        data = yaml_load(template_yaml)
        for app in applist:
            template_yaml = """
            {}: {{}}
            """.format(
                app
            )
            customconfig = self.get_custom_config(app)
            app_as_yaml_object = yaml_load(template_yaml)
            # dict path hardcoded as object generated will always be in v2 or later
            data["config"]["applications"].update(app_as_yaml_object)
            data["config"]["applications"][app].insert(1, "customAppConfig", customconfig)

        return data

    # TODO: rewrite! as config should be inside of the app folder
    # TODO: method should contain all aps, not only one, requires rewriting of merging during root repo init
    def get_custom_config(self, appname):
        team_config_git_repo = self.config_source_repository
        #        try:
        custom_config_file = team_config_git_repo.get_full_file_path(f"{appname}/app_value_file.yaml")
        #        except Exception as ex:
        # handle missing file
        # handle broken file/nod adhering to allowed
        #            return ex
        # sanitize
        # TODO: how to keep whole content with comments
        # TODO: handling generic values for all apps
        if os.path.exists(custom_config_file):
            custom_config_content = yaml_file_load(custom_config_file)
            return custom_config_content
        return None

    def list_apps(self):
        return traverse_config(self.data, self.config_api_version)

    def add_app(self):
        # adds app to the app tenant config
        pass

    def modify_app(self):
        # modifies existing app in tenant config
        pass

    def delete_app(self):
        # deletes app from tenant config
        pass


@dataclass
class RootRepo:
    name: str  # root repository name
    tenant_list: dict  # TODO of AppTenantConfig #list of the tenant configs in the root repository (in apps folder)
    bootstrap: set  # list of tenants to be bootstrapped, derived form values.yaml in bootstrap root repo dict
    app_list: set  # llist of apps without custormer separation

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
            # TODO exception handling for malformed yaml
            if "config" in tenant_apps_config_content:
                tenant_apps_config_content = tenant_apps_config_content["config"]
            if "repository" not in tenant_apps_config_content:
                raise GitOpsException(f"Cannot find key 'repository' in '{tenant_apps_config_file_name}'")
            # if "config" in tenant_apps_config_content:
            logging.info("adding {}".format(bootstrap_entry["name"]))
            atc = AppTenantConfig(
                data=tenant_apps_config_content,
                name=bootstrap_entry["name"],
                config_type="root",
                file_path=tenant_apps_config_file,
                file_name=tenant_apps_config_file_name,
            )
            tenant_app_dict.update({bootstrap_entry["name"]: atc})
        return tenant_app_dict

    def __get_all_apps_list(self):
        all_apps_list = dict()
        for tenant in self.tenant_list:
            value = traverse_config(self.tenant_list[tenant].data, self.tenant_list[tenant].config_api_version)
            all_apps_list.update({tenant: list((dict(value).keys()))})
        return all_apps_list


def traverse_config(data, configver):
    path = configver[1]
    lookup = data
    for key in path:
        lookup = lookup[key]
    return lookup


#################################################################################################
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
    root_repo = RootRepo(root_config_git_repo)
    tenant_config_team_repo = AppTenantConfig("team", config_source_repository=team_config_git_repo)

    # dict conversion causes YAML object to be unordered
    tenant_config_repo_apps = dict(tenant_config_team_repo.list_apps())
    if not team_config_app_name in list(root_repo.tenant_list.keys()):
        raise GitOpsException("Couldn't find config file for apps repository in root repository's 'apps/' directory")
    current_repo_apps = dict(root_repo.tenant_list[team_config_app_name].list_apps())

    apps_from_other_repos = root_repo.app_list.copy()
    apps_from_other_repos.pop(team_config_app_name)
    for app in list(tenant_config_repo_apps.keys()):
        for tenant in apps_from_other_repos.values():
            if app in tenant:
                raise GitOpsException(f"Application '{app}' already exists in a different repository")

    logging.info(
        "Found %s app(s) in apps repository: %s", len(tenant_config_repo_apps), ", ".join(tenant_config_repo_apps)
    )
    logging.info("Searching apps repository in root repository's 'apps/' directory...")

    apps_config_file = root_repo.tenant_list[team_config_app_name].file_path
    apps_config_file_name = root_repo.tenant_list[team_config_app_name].file_name
    # TODO FIX VALUE TO DIFFER BETWEEN OLD/NEW STYLE
    found_apps_path = "config.applications"

    # removing all keys not being current app repo in order to compare app lists
    # excluding keys added by root repo administrator,
    # TODO: figure out how to handle that better
    for app in list(current_repo_apps.keys()):
        if current_repo_apps.get(app, dict()) is not None:
            for key in list(current_repo_apps.get(app, dict())):
                if key != "customAppConfig":
                    del current_repo_apps[app][key]
    if current_repo_apps == tenant_config_repo_apps:
        logging.info("Root repository already up-to-date. I'm done here.")
        return

    logging.info("Sync applications in root repository's %s.", apps_config_file_name)
    merge_yaml_element(
        apps_config_file,
        found_apps_path,
        {
            repo_app: traverse_config(tenant_config_team_repo.data, tenant_config_team_repo.config_api_version).get(
                repo_app, "{}"
            )
            for repo_app in tenant_config_repo_apps
        },
    )

    __commit_and_push(team_config_git_repo, root_config_git_repo, git_user, git_email, apps_config_file_name)


def __commit_and_push(
    team_config_git_repo: GitRepo, root_config_git_repo: GitRepo, git_user: str, git_email: str, app_file_name: str
) -> None:
    author = team_config_git_repo.get_author_from_last_commit()
    root_config_git_repo.commit(git_user, git_email, f"{author} updated " + app_file_name)
    root_config_git_repo.push()
