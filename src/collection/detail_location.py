from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict

from .contracts import CollectionAdapter

logger = logging.getLogger(__name__)


class DetailLocationInference:
    """Adapter-specific location enrichment shared by detail API entrypoints."""

    adapter: CollectionAdapter

    def infer_location(
        self,
        *,
        address: str,
        title: str,
        item_id: str | None,
        chat_with_glm: Callable[[str], str],
        log_prediction_event: Callable[..., None],
    ) -> Dict[str, Any]:
        prompt = self.adapter.location_prompt(address=address, title=title)
        if prompt is None:
            log_prediction_event(
                task_type="infer_location",
                item_id=item_id,
                duration_ms=0,
                recall_count=0,
                final_confidence=None,
                success=False,
                failure_reason="location inference is not supported by this collection adapter",
            )
            return {}
        infer_started_at = time.time()
        try:
            resp = chat_with_glm(prompt)
            if "```json" in resp:
                resp = resp.split("```json")[1].split("```")[0]
            elif "```" in resp:
                resp = resp.split("```")[1].split("```")[0]
            result = json.loads(resp.strip())
            log_prediction_event(
                task_type="infer_location",
                item_id=item_id,
                duration_ms=(time.time() - infer_started_at) * 1000,
                recall_count=None,
                final_confidence=None,
                success=True,
                failure_reason=None,
            )
            return result
        except Exception as e:
            logger.exception("Error calling LLM for location inference")
            log_prediction_event(
                task_type="infer_location",
                item_id=item_id,
                duration_ms=(time.time() - infer_started_at) * 1000,
                recall_count=0,
                final_confidence=None,
                success=False,
                failure_reason=str(e),
            )
            return {}
