"""Bounded discovery, five-case qualification and failover for collection AI."""
import re
import sqlite3
import threading
import time

import requests

from src.llm_analysis_policy import require_non_gpt_analysis_model
from src.llm_model_selector import LLMBackendUnavailableError
from src.llm_qualification_cases import CASES, INSTRUCTION, VERSION, exact_match
from src.llm_qualification_runtime import (
    QualificationCancelled,
    check_cancelled,
    shared_store,
    wait_for_slot,
)
from src.llm_qualification_transport import (
    ModelHttpError,
    ModelRateLimitedError,
    request_json,
)
from src.project_environment import getenv as project_getenv

MAX_CANDIDATES = 8
PROBE_TIMEOUT = 60
QUALIFICATION_TTL = 86400
MEDIA = re.compile(r"image|embedding|rerank|(?:^|[-_/])(?:tts|asr|ocr|video|audio)(?:$|[-_/])|flux", re.IGNORECASE)
_REFRESH_LOCK = threading.Lock()
_REFRESH_THREADS = {}


def pool_enabled():
    return project_getenv("CROW_ANALYSIS_MODEL_POOL_ENABLED", "0").lower() in {"1", "true", "yes", "on"}


def eligible_model(model):
    if not isinstance(model, str) or len(model) > 200 or MEDIA.search(model):
        return False
    try:
        require_non_gpt_analysis_model(model, setting="qualified analysis model")
    except ValueError:
        return False
    return bool(model.strip())


def qualified_score(row):
    return isinstance(row.get("score"), int) and row["score"] >= 4


def failure_cooldown(exc):
    # Failed calls count toward upstream abuse limits too, not just token quota.
    minimum = 3600 if getattr(exc, "status_code", None) in {401, 403} else 600
    return max(minimum, getattr(exc, "retry_after_seconds", 0))


class RequestBudgetExceeded(LLMBackendUnavailableError):
    def __init__(self):
        super().__init__("LLM backend unavailable: request scheduling budget exhausted")


class QualifiedModelPool:
    def __init__(self, config, *, proxies=None, store=None, session=None, cancel_event=None):
        self.config = config
        self.probe_timeout = min(PROBE_TIMEOUT, max(1, float(config["timeout"])))
        self.store = store if store is not None else shared_store(config)
        self.cancel_event = cancel_event if cancel_event is not None else threading.Event()
        self.session = session or requests.Session()
        self.session.trust_env = False
        self.session.proxies = proxies or {}
        self.headers = {"Authorization": "Bearer " + config["api_key"]}

    def available(self):
        now = time.time()
        snapshot = self.store.snapshot()
        if snapshot.get("cooldown_until", 0) > now:
            return []
        rows = snapshot["models"]
        good = [(name, row) for name, row in rows.items() if eligible_model(name)
                and qualified_score(row) and row["checked_at"] + QUALIFICATION_TTL > now
                and row.get("blocked_until", 0) <= now]
        good.sort(key=lambda item: (-item[1]["score"], item[1]["elapsed"], item[0]))
        return [name for name, _ in good[:5]]

    def _backoff_qualification(self, exc):
        seconds = failure_cooldown(exc)
        if getattr(exc, "status_code", None) in {401, 403, 429} or not self.available():
            self.store.cool_down(seconds)
        else:
            self.store.defer_scan(seconds)

    def request(self, model, content, *, probe=False, deadline=None):
        from src.llm_evidence_prompt import request_messages
        from src.llm_request_policy import MAX_OUTPUT_TOKENS

        check_cancelled(self.cancel_event)
        if not eligible_model(model):
            raise LLMBackendUnavailableError("LLM backend unavailable: excluded model")
        payload = {"model": model, "messages": request_messages(content), "temperature": 0, "max_tokens": MAX_OUTPUT_TOKENS}
        if self.config.get("reasoning_effort"):
            payload["reasoning_effort"] = self.config["reasoning_effort"]
        if probe:
            payload["max_tokens"] = 256
        timeout = self.probe_timeout if probe else self.config["timeout"]
        slot_deadline = time.monotonic() + timeout
        if deadline is not None:
            slot_deadline = min(slot_deadline, deadline - timeout)
        while True:
            check_cancelled(self.cancel_event)
            if time.monotonic() > slot_deadline:
                raise RequestBudgetExceeded()
            delay = self.store.reserve_request_slot()
            if delay is None:
                raise ModelRateLimitedError(0)
            if not delay:
                break
            if time.monotonic() + delay > slot_deadline:
                raise RequestBudgetExceeded()
            wait_for_slot(self.cancel_event, delay)
        check_cancelled(self.cancel_event)
        if time.monotonic() > slot_deadline:
            raise RequestBudgetExceeded()
        if self.store.snapshot().get("cooldown_until", 0) > time.time():
            raise ModelRateLimitedError(0)
        try:
            body = request_json(self.session, "post", self.config["base_url"] + "/chat/completions",
                                headers=self.headers, json=payload,
                                timeout=timeout,
                                max_bytes=65536 if probe else 2097152)
        except (requests.RequestException, LLMBackendUnavailableError, ValueError) as exc:
            check_cancelled(self.cancel_event)
            if probe:
                self._backoff_qualification(exc)
            elif isinstance(exc, ModelHttpError) and exc.status_code in {401, 403, 429}:
                self.store.cool_down(failure_cooldown(exc))
            raise
        check_cancelled(self.cancel_event)
        try:
            value = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMBackendUnavailableError("LLM backend unavailable: invalid chat response") from None
        if not isinstance(value, str) or not value.strip():
            raise LLMBackendUnavailableError("LLM backend unavailable: empty chat response")
        return value

    def discover(self):
        check_cancelled(self.cancel_event)
        body = request_json(self.session, "get", self.config["base_url"] + "/models",
                            headers=self.headers, timeout=min(10, self.probe_timeout), max_bytes=2097152)
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list) or len(data) > 10000:
            raise LLMBackendUnavailableError("LLM backend unavailable: invalid catalog")
        names = {row.get("id") for row in data if isinstance(row, dict) and eligible_model(row.get("id"))}
        # Try different families before spending a whole batch on one provider's aliases.
        preferred = self.config.get("models", [])
        families = ("deepseek", "glm", "gemini", "qwen", "mistral", "grok", "kimi", "minimax", "llama", "claude")
        buckets = {}
        for name in names:
            family = next((family for family in families if family in name.casefold()), "other")
            buckets.setdefault(family, []).append(name)
        ranked = []
        for family, models in buckets.items():
            models.sort(key=lambda name: (not any(word in name.casefold() for word in ("flash", "small", "mini")),
                                          "think" in name.casefold(), "/" in name, len(name), name))
            for index, name in enumerate(models):
                ranked.append((0 if name in preferred else 1, index,
                               families.index(family) if family in families else len(families), name))
        return [row[-1] for row in sorted(ranked)]

    def ensure(self, *, continue_scan=True):
        check_cancelled(self.cancel_event)
        if not self.store.scan_lock.acquire(blocking=False):
            return self.available()
        try:
            return self._ensure(continue_scan=continue_scan)
        finally:
            self.store.scan_lock.release()

    def _ensure(self, *, continue_scan=True):
        from src.llm_evidence_prompt import EvidencePrompt
        active = self.available()
        snapshot = self.store.snapshot()
        if active and (not continue_scan or snapshot.get("scan_complete")):
            return active
        if not self.store.claim():
            return active
        cursor = snapshot["cursor"]
        complete = False
        deadline = time.monotonic() + 450
        try:
            candidates = self.discover()
            if not candidates:
                return []
            records = self.store.snapshot()["models"]
            now = time.time()
            ordered = [
                name for name in candidates if name not in records or (
                    records[name].get("blocked_until", 0) <= now
                    and records[name]["checked_at"]
                    + (QUALIFICATION_TTL if qualified_score(records[name]) else 900) <= now
                )
            ]
            # Catalogs can shrink during provider cooldown. Remember IDs, not positions,
            # so changing catalogs cannot repeatedly restart the first eight probes.
            # Renew explicit and previously qualified routes before exploring aliases;
            # a large failing catalog must not starve the routes that carried business.
            preferred = {name: index for index, name in enumerate(self.config.get("models", []))}

            def priority(name):
                row = records.get(name, {})
                tier = 0 if name in preferred else 1 if qualified_score(row) else 2
                return tier, preferred.get(name, 0), name in records, row.get("checked_at", 0)

            ordered.sort(key=priority)
            tested = 0
            for model in ordered[:MAX_CANDIDATES]:
                check_cancelled(self.cancel_event)
                if time.monotonic() + len(CASES) * (self.probe_timeout + 4) > deadline:
                    break
                start = time.monotonic()
                matches = []
                errors = []
                for source, expected in CASES:
                    try:
                        answer = self.request(model, EvidencePrompt(INSTRUCTION, source), probe=True, deadline=deadline)
                        matches.append(int(exact_match(answer, expected)))
                        errors.append(None)
                    except QualificationCancelled:
                        raise
                    except (ModelRateLimitedError, RequestBudgetExceeded):
                        # An account limit is not five wrong answers from this model.
                        return self.available()
                    except (requests.RequestException, LLMBackendUnavailableError, ValueError) as exc:
                        errors.append(str(exc) if isinstance(exc, LLMBackendUnavailableError) else type(exc).__name__)
                        self.store.record(model, {"score": None, "matches": matches, "errors": errors,
                            "checked_at": time.time(), "elapsed": round(time.monotonic() - start, 3),
                            "blocked_until": 0, "version": VERSION, "status": "probe_error"})
                        self._backoff_qualification(exc)
                        return self.available()
                score = sum(matches)
                self.store.record(model, {"score": score, "matches": matches, "errors": errors,
                    "checked_at": time.time(), "elapsed": round(time.monotonic() - start, 3),
                    "blocked_until": 0, "version": VERSION})
                tested += 1
            cursor = len(set(candidates) & self.store.snapshot()["models"].keys())
            complete = tested == len(ordered)
            return self.available()
        except QualificationCancelled:
            raise
        except (requests.RequestException, ValueError, LLMBackendUnavailableError) as exc:
            self._backoff_qualification(exc)
            return self.available()
        except RuntimeError:
            return active
        finally:
            self.store.finish(cursor, complete)

    def refresh_in_background(self):
        """Preflight never waits for a benchmark or claims a business item."""
        active = self.available()
        snapshot = self.store.snapshot()
        if ((active and snapshot.get("scan_complete")) or snapshot["lease_until"] > time.time()
                or snapshot["next_scan"] > time.time()):
            return active
        key = self.store.key
        with _REFRESH_LOCK:
            if key not in _REFRESH_THREADS:
                def run():
                    try:
                        self.ensure()
                    except (OSError, sqlite3.Error, RuntimeError, ValueError):
                        pass  # Remain unavailable; never consume an item's retry budget.
                    finally:
                        with _REFRESH_LOCK:
                            _REFRESH_THREADS.pop(key, None)
                        self.session.close()
                thread = threading.Thread(target=run, name="analysis-model-qualification", daemon=True)
                _REFRESH_THREADS[key] = thread
                thread.start()
        return active

    def chat(self, content, *, model=None):
        check_cancelled(self.cancel_event)
        candidates = self.available()
        if model:
            candidates = [model] if model in candidates else []
        else:
            candidates = self.store.route_order(candidates)
        for candidate in candidates:
            if candidate not in self.available():
                continue
            try:
                answer = self.request(candidate, content)
                self.config["last_successful_model"] = candidate
                return answer
            except QualificationCancelled:
                raise
            except (ModelRateLimitedError, RequestBudgetExceeded):
                break  # Do not spend the same account's quota on more aliases.
            except (requests.RequestException, LLMBackendUnavailableError, ValueError):
                self.store.disable(candidate)
        # Re-qualification is performed by the next worker preflight, not per item.
        raise LLMBackendUnavailableError("LLM backend unavailable: qualified model pool exhausted or probing")
