import logging
import os
from dataclasses import dataclass
from typing import Any, Set, Tuple, Dict
from gitopscli.git_api import GitApiConfig, GitRepo, GitRepoApiFactory
from gitopscli.io_api.yaml_util import YAMLException, merge_yaml_element, yaml_file_load, yaml_load
from gitopscli.gitops_exception import GitOpsException
from .command import Command


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


class TeamRepoContent:
    # TODO: ONLY ONE CLONE, ONLY ONE TeamRepoContent PER LIFECYCLE?
    def __init__(self, team_config_git_repo) -> None:
        team_config_git_repo.clone()
        self.applist = self.__get_repo_apps(team_config_git_repo)
        self.custom_config = self.__get_repo_custom_config(team_config_git_repo)

    def __get_repo_apps(self, team_config_git_repo: GitRepo) -> Set[str]:
        repo_dir = team_config_git_repo.get_full_file_path(".")
        return {
            name
            for name in os.listdir(repo_dir)
            if os.path.isdir(os.path.join(repo_dir, name)) and not name.startswith(".")
        }

    def __get_repo_custom_config(self, team_config_git_repo: GitRepo, custom_config_file: str = "custom_config.yaml"):
        custom_config_file = team_config_git_repo.get_full_file_path(custom_config_file)
        try:
            app_config_content = yaml_file_load(custom_config_file)
        except FileNotFoundError as ex:
            logging.warning("no custom app settings file found - default value: {}".format(custom_config_file))
            return {}
        except YAMLException as yex:
            logging.error(
                "Unable to load {} from app repository, please validate if this is a correct YAML file".format(
                    custom_config_file
                ),
                exc_info=yex,
            )
            # TODO: SHOULD FAIL WHEN INCORRECT APP SPEC FILE PROVIDED?
            # TODO: which errors should be raised as GitOpsException
            return {}
        return app_config_content


class RootRepoContent:
    def __init__(self, root_config_git_repo) -> None:
        root_config_git_repo.clone()
        self.bootstrap_entries = self.__get_bootstrap_entries(root_config_git_repo)
        self.apps_from_other_repos: Set[str] = set()  # Set for all entries in .applications from each config repository
        self.found_app_config_file = None
        self.found_app_config_file_name = None
        self.found_apps_path = "applications"
        self.found_app_config_apps: Set[str] = set()
        self.app_config_content = None

    def get_app_config_content(self, app_config_file):
        try:
            app_config_content = yaml_file_load(app_config_file)
        except FileNotFoundError as ex:
            raise GitOpsException(f"File '{app_config_file}' not found in root repository.") from ex
        return app_config_content
        

    def __get_bootstrap_entries(self, root_config_git_repo: GitRepo) -> Any:
        bootstrap_values_file = root_config_git_repo.get_full_file_path("bootstrap/values.yaml")
        try:
            bootstrap_yaml = yaml_file_load(bootstrap_values_file)
        except FileNotFoundError as ex:
            raise GitOpsException("File 'bootstrap/values.yaml' not found in root repository.") from ex
        if "bootstrap" not in bootstrap_yaml:
            raise GitOpsException("Cannot find key 'bootstrap' in 'bootstrap/values.yaml'")
        return bootstrap_yaml["bootstrap"]


class FoundAppsConfig:
    def __init__(
        self,
        found_app_config_file,
        found_app_config_file_name,
        found_app_config_apps,
        apps_from_other_repos,
        found_apps_path,
    ) -> None:
        self.found_app_config_file = found_app_config_file
        self.found_app_config_file_name = found_app_config_file_name
        self.found_app_config_apps = found_app_config_apps
        self.apps_from_other_repos = apps_from_other_repos
        self.found_apps_path = found_apps_path


def _sync_apps_command(args: SyncAppsCommand.Args) -> None:
    team_config_git_repo_api = GitRepoApiFactory.create(args, args.organisation, args.repository_name)
    root_config_git_repo_api = GitRepoApiFactory.create(args, args.root_organisation, args.root_repository_name)
    with GitRepo(team_config_git_repo_api) as team_config_git_repo:
        with GitRepo(root_config_git_repo_api) as root_config_git_repo:
            __sync_apps(team_config_git_repo, root_config_git_repo, args.git_user, args.git_email)


def __sync_apps(team_config_git_repo: GitRepo, root_config_git_repo: GitRepo, git_user: str, git_email: str) -> None:
    logging.info("Team config repository: %s", team_config_git_repo.get_clone_url())
    logging.info("Root config repository: %s", root_config_git_repo.get_clone_url())
    team_repo = TeamRepoContent(team_config_git_repo)
    repo_apps = team_repo.applist
    logging.info("Found %s app(s) in apps repository: %s", len(repo_apps), ", ".join(repo_apps))

    logging.info("Searching apps repository in root repository's 'apps/' directory...")
    found_repo_content = __find_apps_config_from_repo(team_config_git_repo, root_config_git_repo)

    # TODO to be discussed - how to proceed with changes here, as adding additional custom_values will invalidate this check.
    # Based on the outcome - test test_sync_apps_already_up_to_date also needs to be modified.
    # Options:
    #   - remove this check
    #   - add validation of customizationfile presence to __find_apps_config_from_repo
    #   - move and modify this check to validate actual changes (get the applications list from resulting yaml and compare with current one)
    # if current_repo_apps == repo_apps:
    #     logging.info("Root repository already up-to-date. I'm done here.")
    #     return

    __check_if_app_already_exists(repo_apps, found_repo_content.apps_from_other_repos)

    logging.info("Sync applications in root repository's %s.", found_repo_content.found_app_config_file_name)
    merge_yaml_element(
        found_repo_content.found_app_config_file,
        found_repo_content.found_apps_path,
        {repo_app: {} for repo_app in repo_apps},
    )

    __commit_and_push(
        team_config_git_repo, root_config_git_repo, git_user, git_email, found_repo_content.found_app_config_file_name
    )


def __find_apps_config_from_repo(
    team_config_git_repo: GitRepo, root_config_git_repo: GitRepo
) -> Tuple[str, str, Set[str], Set[str], str]:

    team_config_git_repo_clone_url = team_config_git_repo.get_clone_url()
    root_repo_content = RootRepoContent(root_config_git_repo)
    bootstrap_entries = root_repo_content.bootstrap_entries

    for bootstrap_entry in bootstrap_entries:
        if "name" not in bootstrap_entry:
            raise GitOpsException("Every bootstrap entry must have a 'name' property.")
        app_file_name = "apps/" + bootstrap_entry["name"] + ".yaml"
        logging.info("Analyzing %s in root repository", app_file_name)

        app_config_file = root_config_git_repo.get_full_file_path(app_file_name)
        app_config_content = root_repo_content.get_app_config_content(app_config_file)

        if "config" in app_config_content:
            app_config_content = app_config_content["config"]
            root_repo_content.found_apps_path = "config.applications"

        if "repository" not in app_config_content:
            raise GitOpsException(f"Cannot find key 'repository' in '{app_file_name}'")
        if app_config_content["repository"] == team_config_git_repo_clone_url:
            logging.info("Found apps repository in %s", app_file_name)
            found_app_config_file = app_config_file
            found_app_config_file_name = app_file_name
            root_repo_content.found_app_config_apps = __get_applications_from_app_config(app_config_content)
        else:
            root_repo_content.apps_from_other_repos.update(__get_applications_from_app_config(app_config_content))

    if found_app_config_file is None or found_app_config_file_name is None:
        raise GitOpsException(f"Couldn't find config file for apps repository in root repository's 'apps/' directory")

    return FoundAppsConfig(
        found_app_config_file,
        found_app_config_file_name,
        root_repo_content.found_app_config_apps,
        root_repo_content.apps_from_other_repos,
        root_repo_content.found_apps_path,
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


def __check_if_app_already_exists(apps_dirs: Set[str], apps_from_other_repos: Set[str]) -> None:
    for app_key in apps_dirs:
        if app_key in apps_from_other_repos:
            raise GitOpsException(f"Application '{app_key}' already exists in a different repository")
