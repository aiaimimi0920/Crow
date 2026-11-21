"""Small, deterministic eight-city synthetic end-to-end fixture, not evidence."""

from datetime import date

from .contracts import HOLDOUT_CITIES, TRAIN_CITIES, Transaction, add_months
from .dataset import build_examples
from .evaluation import backtest


def demo_report():
    rows = []
    for city_index, city in enumerate(TRAIN_CITIES + HOLDOUT_CITIES):
        for month_index in range(36):
            month = add_months(date(2022, 1, 1), month_index)
            for kind in ("resale", "auction"):
                for i in range(3):
                    day = month.replace(day=i + 2)
                    rid = f"synthetic-{city}-{kind}-{month_index}-{i}"
                    price = 8000 + city_index * 1000 + month_index * 30 + i * 10
                    rows.append(
                        Transaction(
                            rid,
                            rid,
                            kind,
                            city,
                            "合成区",
                            "合成小区",
                            "",
                            day,
                            day,
                            price * (0.8 if kind == "auction" else 1.0),
                            "generated_fixture_not_market_data",
                            True,
                            None,
                            None,
                            90.0 + i,
                        )
                    )
    origins = [
        date(2022, 7, 31),
        date(2022, 10, 31),
        date(2023, 2, 28),
        date(2023, 4, 30),
        date(2023, 7, 31),
    ]
    output = {"status": "SYNTHETIC_PIPELINE_TEST_ONLY", "transactions": len(rows)}
    for mode in ("crow_only", "market_augmented"):
        examples = build_examples(rows, origins, input_mode=mode)
        output[mode] = {
            "temporal": backtest(
                examples, origins[2:], evaluation_asof=date(2024, 2, 1)
            ),
            "holdout": backtest(
                examples, [origins[-1]], holdout=True, evaluation_asof=date(2024, 2, 1)
            ),
        }
    return output
