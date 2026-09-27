"""Legacy screening statistics without server initialization or persistence."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, Protocol, cast


class ScreenSummaryHost(Protocol):
    def _prediction_confidence_bucket(self, confidence: object) -> str: ...


@dataclass(frozen=True)
class ScreenResultSummary:
    host: ScreenSummaryHost
    __all__: ClassVar[list[str]] = [
        "_prediction_confidence_bucket",
        "summarize_screen_results",
    ]

    def _prediction_confidence_bucket(self, confidence: object) -> str:
        if confidence is None:
            return "unknown"
        try:
            value = float(cast(float, confidence))
        except (TypeError, ValueError):
            return "unknown"
        if value >= 0.75:
            return "high"
        if value >= 0.45:
            return "medium"
        return "low"

    def summarize_screen_results(
        self, results: Sequence[Mapping[str, object]]
    ) -> dict[str, object]:
        strategy_counts: dict[str, int] = {}
        coordinate_strategy_counts: dict[str, int] = {}
        confidence_bucket_counts: dict[str, int] = {}
        blocked_reason_counts: dict[str, int] = {}
        malignant_count = 0
        alert_candidate_count = 0
        manual_review_count = 0
        manual_review_blocked_count = 0
        risk_validation_blocked_count = 0
        margin_values = []
        for result in results:
            prediction = cast(Mapping[str, object], result.get("prediction") or {})
            strategy = str(prediction.get("strategy") or "unknown")
            strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
            trace = cast(Mapping[str, object], prediction.get("trace") or {})
            coordinate_strategy = str(
                trace.get("subject_coordinate_strategy") or "unknown"
            )
            coordinate_strategy_counts[coordinate_strategy] = (
                coordinate_strategy_counts.get(coordinate_strategy, 0) + 1
            )
            bucket = self.host._prediction_confidence_bucket(
                prediction.get("confidence")
            )
            confidence_bucket_counts[bucket] = (
                confidence_bucket_counts.get(bucket, 0) + 1
            )
            if prediction.get("manual_review_recommended"):
                manual_review_count += 1
            blockers = cast(Sequence[str], result.get("alert_blockers") or [])
            for blocker in blockers:
                blocked_reason_counts[blocker] = (
                    blocked_reason_counts.get(blocker, 0) + 1
                )
            if "manual_review_required" in blockers:
                manual_review_blocked_count += 1
            if (
                "risk_validation_incomplete" in blockers
                or "risk_validation_invalid" in blockers
            ):
                risk_validation_blocked_count += 1
            if result.get("is_malignant_risk"):
                malignant_count += 1
            if result.get("meets_alert_threshold"):
                alert_candidate_count += 1
            margin = result.get("margin")
            if isinstance(margin, (int, float)):
                margin_values.append(float(margin))
        average_margin = (
            round(sum(margin_values) / len(margin_values), 4) if margin_values else None
        )
        top_result_id = results[0]["id"] if results else None
        return {
            "strategy_counts": dict(sorted(strategy_counts.items())),
            "coordinate_strategy_counts": dict(
                sorted(coordinate_strategy_counts.items())
            ),
            "confidence_bucket_counts": dict(sorted(confidence_bucket_counts.items())),
            "malignant_risk_count": malignant_count,
            "alert_candidate_count": alert_candidate_count,
            "manual_review_count": manual_review_count,
            "blocked_reason_counts": dict(sorted(blocked_reason_counts.items())),
            "manual_review_blocked_count": manual_review_blocked_count,
            "risk_validation_blocked_count": risk_validation_blocked_count,
            "average_margin": average_margin,
            "top_result_id": top_result_id,
        }
