from dataclasses import dataclass


@dataclass(frozen=True)
class AppsRootConfigRepo:
    configRepos: list[ConfigRepo]

    getConfigRepoByGitUrl()



