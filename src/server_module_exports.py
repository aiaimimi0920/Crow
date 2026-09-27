"""Publish native owners without replacing their function or method identity."""

from collections.abc import Iterable
from dataclasses import dataclass
from types import ModuleType
from typing import cast


@dataclass(frozen=True)
class ModuleExports:
    namespace: dict[str, object]
    context: ModuleType

    def publish(self, owner: object) -> None:
        exports = list(cast(Iterable[str], getattr(owner, "__all__", ())))
        for name in exports:
            value = getattr(owner, name)
            self.namespace[name] = value
            setattr(self.context, name, value)
            if name not in self.context.__all__:
                self.context.__all__.append(name)
