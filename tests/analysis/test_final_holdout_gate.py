"""Exercise final CLI with synthetic data and a temp-only receipt root."""

import json
from datetime import date
from pathlib import Path

import pytest

from src.analysis.six_month import __main__ as cli, evaluation
from src.analysis.six_month.contracts import HOLDOUT_CITIES, SPLIT_VERSION, TRAIN_CITIES


ORIGINS = ["2022-07-31", "2023-07-31"]
FROZEN = {
    "split_version": SPLIT_VERSION,
    "backend": "ridge",
    "cutoffs": ORIGINS[-1],
    "origins": ORIGINS,
    "evaluation_asof": "2024-02-01",
    "input_mode": "crow_only",
    "label_definition": "resale_cell_median_month_t_plus_6_v1",
}


@pytest.fixture
def final_run(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "OUTPUT_ROOT", tmp_path)
    receipt = tmp_path / "synthetic-holdout-receipt.json"

    def run(
        *,
        labels="matched",
        as_of="2024-02-01",
        overrides=None,
        origins=",".join(ORIGINS),
        filename="report.json",
    ):
        rows = []

        def sales(city, kind, month, *, community="synthetic-core", available=None):
            for day in range(2, 5):
                traded = str(date.fromisoformat(month + "-01").replace(day=day))
                key = f"synthetic:{city}:{kind}:{traded}"
                rows.append(
                    {
                        "record_id": key,
                        "property_id": key,
                        "kind": kind,
                        "city": city,
                        "district": "synthetic-district",
                        "community": community,
                        "traded_at": traded,
                        "available_at": available or traded,
                        "unit_price": 8000 + day * 10,
                        "source": "synthetic-test-fixture",
                        "sold": True,
                        "synthetic": True,
                    }
                )

        # One training-city label can mature before the final cutoff.
        for month in ("2022-02", "2022-06"):
            sales(TRAIN_CITIES[0], "auction", month)
        sales(TRAIN_CITIES[0], "resale", "2023-01")
        # Exactly one held-out city qualifies by design; don't require all four.
        for month in ("2023-02", "2023-06"):
            sales(HOLDOUT_CITIES[0], "auction", month)
        if labels != "missing":
            sales(
                HOLDOUT_CITIES[0],
                "resale",
                "2024-01",
                community="different-cell" if labels == "unmatched" else "synthetic-core",
                available="2024-02-02" if labels == "late" else None,
            )
        source, protocol, output = (
            tmp_path / "input.json",
            tmp_path / "protocol.json",
            tmp_path / filename,
        )
        source.write_text(json.dumps(rows), encoding="utf-8")
        frozen = dict(FROZEN, evaluation_asof=as_of)
        frozen.update(overrides or {})
        protocol.write_text(json.dumps(frozen), encoding="utf-8")
        monkeypatch.setattr(
            "sys.argv",
            [
                "six_month", "evaluate",
                "--input", str(source),
                "--origins", origins,
                "--cutoffs", ORIGINS[-1],
                "--as-of", as_of,
                "--holdout",
                "--frozen-protocol", str(protocol),
                "--output", str(output),
            ],
        )
        cli.main()
        return json.loads(output.read_text(encoding="utf-8"))

    return run, receipt


@pytest.mark.parametrize(
    "labels,as_of",
    [
        ("matched", "2024-01-31"),
        ("missing", "2024-02-01"),
        ("unmatched", "2024-02-01"),
        ("late", "2024-02-01"),
    ],
)
def test_zero_scoreable_does_not_spend_final_receipt(final_run, labels, as_of):
    run, receipt = final_run
    try:
        unsafe = run(labels=labels, as_of=as_of)
    except ValueError as exc:
        assert "no scoreable holdout labels" in str(exc)
    else:
        fold = unsafe["folds"][0]
        pytest.fail(
            f"final={fold['status']}, scores_n={fold['scores']['crow_model']['n']}, "
            f"temp_receipt_exists={receipt.exists()}"
        )
    assert not receipt.exists()
    assert not (receipt.parent / "report.json").exists()
    report = run(as_of="2024-02-01")
    assert report["folds"][0]["status"] == "scored"
    assert report["folds"][0]["scores"]["crow_model"]["n"] == 1
    assert receipt.is_file()
    original = receipt.read_bytes()
    reservation = json.loads(original)
    assert reservation["origins"] == report["origins"] == ORIGINS
    assert reservation["evaluation_asof"] == report["evaluation_asof"] == "2024-02-01"
    assert reservation["protocol_sha256"] == report["protocol_sha256"]
    with pytest.raises(FileExistsError):
        run(filename="repeat.json")
    assert receipt.read_bytes() == original


@pytest.mark.parametrize(
    "overrides",
    [{"origins": [ORIGINS[-1]]}, {"evaluation_asof": "2024-02-02"}],
)
def test_final_freeze_rejects_changed_evaluation_clock(final_run, overrides):
    run, receipt = final_run
    with pytest.raises(ValueError, match="frozen protocol does not match"):
        run(overrides=overrides)
    assert not receipt.exists()


def test_final_freeze_matches_effective_origins_not_cli_order(final_run):
    run, _ = final_run
    report = run(origins=",".join(reversed(ORIGINS + [ORIGINS[0]])))
    assert report["folds"][0]["status"] == "scored"
    assert report["origins"] == ORIGINS


def test_final_as_of_cannot_precede_cutoff(final_run):
    run, receipt = final_run
    with pytest.raises(ValueError, match="as-of precedes fit cutoff"):
        run(as_of="2023-07-30")
    assert not receipt.exists()


def test_final_receipt_open_failure_stops_before_metrics(final_run, monkeypatch):
    run, receipt = final_run
    original_open = Path.open

    def fail_receipt_open(path, mode="r", *args, **kwargs):
        if path == receipt and mode == "x":
            raise OSError("synthetic receipt open failure")
        return original_open(path, mode, *args, **kwargs)

    def fail_if_scored(*args, **kwargs):
        pytest.fail("metrics ran before the exclusive final receipt")

    monkeypatch.setattr(Path, "open", fail_receipt_open)
    monkeypatch.setattr(evaluation, "metrics", fail_if_scored)
    with pytest.raises(OSError, match="synthetic receipt open failure"):
        run()
    assert not receipt.exists()
    assert not (receipt.parent / "report.json").exists()


@pytest.mark.parametrize(
    "reserved",
    [
        "synthetic-holdout-receipt.json",
        "real-holdout-receipt.json",
        "SYNTHETIC-HOLDOUT-RECEIPT.JSON",
        "REAL-HOLDOUT-RECEIPT.JSON",
        "synthetic-holdout-receipt.json.",
        "real-holdout-receipt.json:alternate",
    ],
)
def test_final_output_cannot_alias_receipt(final_run, monkeypatch, reserved):
    run, receipt = final_run

    def fail_if_scored(*args, **kwargs):
        pytest.fail("metrics ran for a reserved output path")

    monkeypatch.setattr(evaluation, "metrics", fail_if_scored)
    with pytest.raises(ValueError, match="reserved holdout receipt"):
        run(filename=reserved)
    assert not receipt.exists()
    assert not (receipt.parent / "real-holdout-receipt.json").exists()


def test_final_existing_output_does_not_spend_receipt(final_run):
    run, receipt = final_run
    output = receipt.parent / "report.json"
    output.write_text("preserve this file", encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to overwrite"):
        run()
    assert not receipt.exists()
    assert output.read_text(encoding="utf-8") == "preserve this file"


def test_final_output_created_after_preflight_does_not_spend_receipt(
    final_run, monkeypatch
):
    run, receipt = final_run
    output = receipt.parent / "report.json"
    backtest = cli.backtest

    def add_output_then_backtest(*args, **kwargs):
        output.write_text("existing evidence", encoding="utf-8")
        return backtest(*args, **kwargs)

    monkeypatch.setattr(cli, "backtest", add_output_then_backtest)
    with pytest.raises(ValueError, match="refusing to overwrite"):
        run()
    assert not receipt.exists()
    assert output.read_text(encoding="utf-8") == "existing evidence"
