from __future__ import annotations
from tools.live_smoke_context import *  # noqa: F401,F403


def _browserless_seed_probe():
    from tools import browserless_seed_probe

    return browserless_seed_probe

def preflight_llm_backend(*, timeout: float, check_chat: bool = False) -> dict[str, Any]:
    from src import llm_helper

    return llm_helper.preflight_llm_backend(timeout=timeout, check_chat=check_chat)

def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def new_resume_state() -> dict[str, Any]:
    return {
        "schema_version": RESUME_SCHEMA_VERSION,
        "updated_at": utc_now_iso(),
        "items": {},
    }

def load_resume_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return new_resume_state()
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError):
        return new_resume_state()
    if not isinstance(payload, dict):
        return new_resume_state()
    items = payload.get("items")
    if not isinstance(items, dict):
        items = {}
    state = dict(payload)
    state["schema_version"] = str(state.get("schema_version") or RESUME_SCHEMA_VERSION)
    state["items"] = items
    state.setdefault("updated_at", utc_now_iso())
    return state

def save_resume_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state)
    payload["schema_version"] = str(payload.get("schema_version") or RESUME_SCHEMA_VERSION)
    payload["updated_at"] = utc_now_iso()
    if not isinstance(payload.get("items"), dict):
        payload["items"] = {}
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)
    state.clear()
    state.update(payload)

def _resume_item_id(value: Any) -> str | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None

def resume_item_id(item: dict[str, Any]) -> str | None:
    return _resume_item_id(item.get("id") or item.get("item_id") or item.get("source_item_id"))

def mark_resume_item(
    state: dict[str, Any],
    item_id: Any,
    *,
    status: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_id = _resume_item_id(item_id)
    if normalized_id is None:
        raise ValueError("resume item id is required")
    items = state.setdefault("items", {})
    if not isinstance(items, dict):
        items = {}
        state["items"] = items
    previous = items.get(normalized_id)
    if not isinstance(previous, dict):
        previous = {}
    attempts = int(previous.get("attempts") or 0)
    if status == "in_progress":
        attempts += 1
    entry = dict(previous)
    entry.update(metadata or {})
    entry["status"] = status
    entry["updated_at"] = utc_now_iso()
    entry["attempts"] = attempts
    if status == RESUME_COMPLETED_STATUS:
        entry.setdefault("completed_at", entry["updated_at"])
    items[normalized_id] = entry
    state["updated_at"] = entry["updated_at"]
    return entry

def is_resume_completed(state: dict[str, Any], item_id: Any) -> bool:
    normalized_id = _resume_item_id(item_id)
    if normalized_id is None:
        return False
    items = state.get("items")
    if not isinstance(items, dict):
        return False
    entry = items.get(normalized_id)
    return isinstance(entry, dict) and entry.get("status") == RESUME_COMPLETED_STATUS

def select_resume_candidates(
    items: Iterable[dict[str, Any]],
    state: dict[str, Any],
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    candidates: list[dict[str, Any]] = []
    skipped_completed: list[str] = []
    for item in items:
        item_id = resume_item_id(item)
        if item_id and is_resume_completed(state, item_id):
            skipped_completed.append(item_id)
            continue
        if len(candidates) >= limit:
            break
        candidates.append(item)
    return candidates, skipped_completed

def hydrate_resume_state_from_artifacts(
    state: dict[str, Any],
    items: Iterable[dict[str, Any]],
    *,
    output_dir: Path,
) -> list[str]:
    hydrated: list[str] = []
    for item in items:
        item_id = resume_item_id(item)
        if not item_id or is_resume_completed(state, item_id):
            continue
        if not has_completed_item_artifacts(output_dir, item_id):
            continue
        mark_resume_item(
            state,
            item_id,
            status=RESUME_COMPLETED_STATUS,
            metadata={
                "source_url": item.get("url"),
                "title": item.get("title"),
                "selected_json_path": str(output_dir / item_id / "selected.json"),
                "final_json_path": str(output_dir / item_id / "final.json"),
                "recovered_from_artifacts": True,
            },
        )
        hydrated.append(item_id)
    return hydrated

def has_completed_item_artifacts(output_dir: Path, item_id: str) -> bool:
    item_dir = output_dir / item_id
    return (item_dir / "final.json").exists() and (item_dir / "selected.json").exists()

def has_value(value: Any) -> bool:
    return value not in (None, "", [])

def pick_first(*values: Any) -> Any:
    for value in values:
        if has_value(value):
            return value
    return None

def parse_csv_values(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    values: list[str] = []
    for chunk in str(raw).replace(";", ",").split(","):
        value = chunk.strip()
        if value and value not in values:
            values.append(value)
    return tuple(values)

def replace_list_url_params(
    url: str,
    *,
    location_code: str | None = None,
    category: str | None = None,
    st_param: str | None = None,
    page: int | None = None,
) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if location_code:
        query["location_code"] = [str(location_code)]
    if st_param:
        query["st_param"] = [str(st_param)]
    if page is not None:
        query["page"] = [str(int(page))]
    if category:
        path_parts = parsed.path.split("/")
        for index, part in enumerate(path_parts):
            if part.startswith("50025969") or part.startswith("200782003") or "__" in part:
                suffix = ""
                if "__" in part:
                    suffix = "__" + part.split("__", 1)[1]
                elif part.endswith(".htm"):
                    suffix = ".htm"
                path_parts[index] = f"{category}{suffix or '__2.htm'}"
                break
        else:
            path_parts.append(f"{category}__2.htm")
        parsed = parsed._replace(path="/".join(path_parts))
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

__all__ = ('_browserless_seed_probe', 'preflight_llm_backend', 'write_json', 'load_json', 'utc_now_iso', 'new_resume_state', 'load_resume_state', 'save_resume_state', '_resume_item_id', 'resume_item_id', 'mark_resume_item', 'is_resume_completed', 'select_resume_candidates', 'hydrate_resume_state_from_artifacts', 'has_completed_item_artifacts', 'has_value', 'pick_first', 'parse_csv_values', 'replace_list_url_params')
