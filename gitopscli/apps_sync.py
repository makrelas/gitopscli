import logging
import os
from pprint import pformat

from ruamel.yaml import YAML

from gitopscli.yaml_util import merge_yaml_element


def sync_apps(apps_git, root_git):
    repo_apps = get_repo_apps(apps_git)
    apps_config_file, app_file_name, apps_from_other_repos = find_apps_config_from_repo(apps_git, root_git)
    check_if_app_already_exists(repo_apps, apps_from_other_repos)
    merge_yaml_element(apps_config_file, "applications", repo_apps, True)
    commit_and_push(apps_git, root_git, app_file_name)


def find_apps_config_from_repo(apps_git, root_git):
    logging.info("Searching for %s in apps/", apps_git.get_clone_url())
    yaml = YAML()
    # List for all entries in .applications from each config repository
    apps_from_other_repos = []
    apps_config_file = None
    app_file_name = None
    selected_app_config = None
    app_file_entries = get_bootstrap_entries(root_git)
    for app_file in app_file_entries:
        app_file_name = "apps/" + app_file["name"] + ".yaml"
        logging.info("Analyzing %s", app_file_name)
        apps_config_file = root_git.get_full_file_path(app_file_name)
        with open(apps_config_file, "r") as stream:
            app_config_content = yaml.load(stream)
        if app_config_content["repository"] == apps_git.get_clone_url():
            logging.info("Found repository in %s", app_file_name)
            selected_app_config = app_config_content
            apps_config_file = str(apps_config_file)
        else:
            if "applications" in app_config_content and app_config_content["applications"] is not None:
                apps_from_other_repos += app_config_content["applications"].keys()
    if selected_app_config is None:
        raise Exception(f"Could't find config file with .repository={apps_git.get_clone_url()} in apps/ directory")
    return apps_config_file, app_file_name, apps_from_other_repos


def commit_and_push(apps_git, root_git, app_file_name):
    author = apps_git.get_author_from_last_commit()
    root_git.commit(f"{author} updated " + app_file_name)
    root_git.push("master")


def get_bootstrap_entries(root_git):
    yaml = YAML()
    root_git.checkout("master")
    bootstrap_values_file = root_git.get_full_file_path("bootstrap/values.yaml")
    with open(bootstrap_values_file, "r") as stream:
        bootstrap = yaml.load(stream)
    return bootstrap["bootstrap"]


def get_repo_apps(apps_git):
    apps_git.checkout("master")
    repo_dir = apps_git.get_full_file_path(".")
    apps_dirs = get_application_directories(repo_dir)
    logging.info("Apps in %s\n%s", apps_git.get_clone_url(), pformat(apps_dirs))
    return apps_dirs


def get_application_directories(full_file_path):
    app_dirs = [
        name
        for name in os.listdir(full_file_path)
        if os.path.isdir(os.path.join(full_file_path, name)) and not name.startswith(".")
    ]
    apps = {}
    for app_dir in app_dirs:
        apps[app_dir] = {}
    return apps


def check_if_app_already_exists(apps_dirs, apps_from_other_repos):
    for app_key in apps_dirs:
        if app_key in apps_from_other_repos:
            raise Exception("application: " + app_key + " already exists in a different repository")