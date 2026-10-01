"""Cookie snapshot configuration and node-scoped path containment."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Protocol

from .project_data_paths import resolve_project_data_root
from .project_environment import getenv as project_getenv


class EnvironmentReader(Protocol):
    def __call__(self, name: str, default: str | None = None) -> str | None: ...


@dataclass(frozen=True)
class AuthCookiePaths:
    env: EnvironmentReader
    repo_root: Callable[[], Path]
    data_dir: Callable[[], str]
    normalize_node: Callable[[object], str]
    roots: Callable[[], list[Path]]

    __all__: ClassVar[list[str]] = [
        "_auth_cookie_snapshot_sample_urls",
        "_normalize_auth_cookie_snapshot_node_id",
        "_auth_cookie_snapshot_root_candidates",
        "_resolve_auth_cookie_snapshot_path",
    ]

    def _auth_cookie_snapshot_sample_urls(
        self, payload: dict[str, object]
    ) -> list[str]:
        raw = payload.get("sample_urls")
        if isinstance(raw, list):
            urls = [str(value).strip() for value in raw if str(value or "").strip()]
            if urls:
                return urls

        env_raw = project_getenv("CROW_COOKIE_SNAPSHOT_SAMPLE_URLS", reader=self.env)
        if env_raw:
            urls = [part.strip() for part in re.split(r"[;,]", env_raw) if part.strip()]
            if urls:
                return urls

        return [
            "https://sf.taobao.com/list/50025969__2.htm",
            "https://sf.taobao.com/list/200782003__1.htm",
        ]

    def _normalize_auth_cookie_snapshot_node_id(self, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if text in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9._-]+", text):
            return ""
        return text

    def _auth_cookie_snapshot_root_candidates(
        self,
    ) -> list[Path]:
        candidates: list[Path] = []
        seen: set[str] = set()

        def _add(path_value: str | Path | None) -> None:
            if not path_value:
                return
            path = Path(path_value).expanduser()
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            key = str(resolved)
            if key in seen:
                return
            seen.add(key)
            candidates.append(resolved)

        _add(project_getenv("CROW_COOKIE_SNAPSHOT_ROOT", reader=self.env))
        _add(project_getenv("CROW_SHARED_DATA_ROOT_HOST", reader=self.env))

        data_root = Path(self.data_dir()).expanduser()
        try:
            data_root = data_root.resolve()
        except OSError:
            pass
        if data_root.name.lower() == "datas":
            _add(data_root.parent)
        if not candidates:
            management_env = {
                key: self.env(key) or ""
                for key in ("CROW_DATA_ROOT_HOST", "FAPAI_DATA_ROOT_HOST")
            }
            _add(resolve_project_data_root(self.repo_root(), env=management_env))

        return candidates

    def _resolve_auth_cookie_snapshot_path(self, payload: dict[str, object]) -> str:
        explicit_path = str(payload.get("cookie_snapshot_path") or "").strip()
        env_path = str(
            project_getenv("CROW_COOKIE_SNAPSHOT", reader=self.env) or ""
        ).strip()
        if env_path:
            configured = Path(env_path).expanduser().resolve()
            if (
                explicit_path
                and Path(explicit_path).expanduser().resolve() != configured
            ):
                return ""
            return str(configured)

        node_id = self.normalize_node(
            payload.get("node_id") or project_getenv("CROW_NODE_ID", reader=self.env)
        )
        if not node_id:
            return ""

        roots = self.roots()
        if not roots:
            return ""

        existing_roots = [root for root in roots if root.exists()]
        selected_root = existing_roots[0] if existing_roots else roots[0]
        node_root = (selected_root / "secrets" / "nodes" / node_id).resolve()
        candidate = (
            Path(explicit_path).expanduser().resolve()
            if explicit_path
            else node_root / "taobao-cookies.json"
        )
        try:
            node_root.relative_to(selected_root.resolve())
            candidate.relative_to(node_root)
        except ValueError:
            return ""
        return str(candidate)
