from dataclasses import dataclass


@dataclass(frozen=True)
class Application:
    name: str
    customConfig: dict