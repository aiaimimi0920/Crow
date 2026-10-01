"""Inspect pool capacity without printing credential-bearing configuration."""

from src.llm_diagnostics import diagnostic_number, failure_kind
from src.llm_model_selector import get_model_selector


def main() -> int:
    try:
        model_selector = get_model_selector()
    except Exception as error:
        print(f"Pool unavailable: {failure_kind(error)}")
        return 1

    print(f"Total Models: {len(model_selector.pool)}")
    print(f"Total Capacity: {diagnostic_number(model_selector.get_total_capacity())}")
    for index, model in enumerate(model_selector.pool, start=1):
        limit = diagnostic_number(model_selector.limits[model["name"]])
        print(f"- Model slot {index} (Limit: {limit})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
