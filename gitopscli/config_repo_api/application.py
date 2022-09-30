from dataclasses import dataclass


@dataclass(frozen=True)
class ConfigRepo(Object):
    applications: list[Applications]
    bla: object
