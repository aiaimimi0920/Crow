"""Offline CLI. No live services, databases or collector writes."""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

from .aggregate import aggregate_archives
from .contracts import HOLDOUT_CITIES, SPLIT_VERSION, TRAIN_CITIES, parse_date
from .current_input import current_snapshot_report
from .dataset import build_examples
from .demo import demo_report
from .evaluation import backtest
from .inference import predict_report, train_artifact
from .inputs import audit_archives, load_transactions

ROOT = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = ROOT / "artifacts" / "analysis"
HOLDOUT_RECEIPT_NAMES = {
    True: "synthetic-holdout-receipt.json",
    False: "real-holdout-receipt.json",
}


def safe_output(value: str) -> Path:
    target = Path(value).resolve()
    root = OUTPUT_ROOT.resolve()
    if not target.is_relative_to(root):
        raise ValueError(
            "output must be under repository artifacts/analysis; never a collector path"
        )
    # Account for Win32 case, trailing dot/space and alternate-stream aliases.
    basename = target.name.split(":", 1)[0].rstrip(" .").casefold()
    if any(
        (target.parent == root and basename == name) or target == (root / name).resolve()
        for name in HOLDOUT_RECEIPT_NAMES.values()
    ):
        raise ValueError("output cannot use a reserved holdout receipt path")
    require_new_output(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def require_new_output(target: Path):
    if target.exists() or target.is_symlink():
        raise ValueError("refusing to overwrite existing analysis evidence")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo")
    demo.add_argument("--output", required=True)
    current = commands.add_parser("current-input")
    current.add_argument("--archive", type=Path, required=True)
    current.add_argument("--output", required=True)
    current.add_argument(
        "--layout", choices=("daily-archive", "worker-final"), default="daily-archive"
    )
    train = commands.add_parser("train")
    train.add_argument("--input", type=Path, required=True)
    train.add_argument("--origins", required=True)
    train.add_argument("--cutoff", required=True)
    train.add_argument("--output", required=True)
    predict = commands.add_parser("predict")
    predict.add_argument("--model", type=Path, required=True)
    predict.add_argument("--input", type=Path, required=True)
    predict.add_argument("--origin", required=True)
    predict.add_argument("--output", required=True)
    audit = commands.add_parser("audit")
    audit.add_argument("--archive", type=Path, required=True)
    audit.add_argument("--output", required=True)
    aggregate = commands.add_parser("aggregate")
    aggregate.add_argument("--archive", type=Path, required=True)
    aggregate.add_argument("--output", required=True)
    aggregate.add_argument(
        "--layout", choices=("daily-archive", "worker-final"), default="daily-archive"
    )
    run = commands.add_parser("evaluate")
    run.add_argument("--input", type=Path, required=True)
    run.add_argument(
        "--origins", required=True, help="comma separated ISO forecast dates"
    )
    run.add_argument(
        "--cutoffs", required=True, help="comma separated ISO training cutoffs"
    )
    run.add_argument("--as-of", required=True)
    run.add_argument(
        "--input-mode", choices=("crow_only", "market_augmented"), default="crow_only"
    )
    run.add_argument(
        "--backend", choices=("ridge", "lightgbm", "catboost"), default="ridge"
    )
    run.add_argument("--holdout", action="store_true")
    run.add_argument("--frozen-protocol", type=Path)
    run.add_argument("--output", required=True)
    args = parser.parse_args()
    output = safe_output(args.output)
    if args.command == "demo":
        report = demo_report()
    elif args.command == "train":
        report = train_artifact(
            args.input,
            [parse_date(v) for v in args.origins.split(",")],
            parse_date(args.cutoff),
        )
    elif args.command == "predict":
        report = predict_report(args.model, args.input, parse_date(args.origin))
    elif args.command in ("audit", "aggregate", "current-input"):
        if output.is_relative_to(args.archive.resolve()):
            raise ValueError("output cannot overlap archive input")
        action = {
            "audit": audit_archives,
            "aggregate": aggregate_archives,
            "current-input": current_snapshot_report,
        }[args.command]
        report = (
            action(args.archive)
            if args.command == "audit"
            else action(args.archive, layout=args.layout)
        )
    else:
        rows, digest = load_transactions(args.input)
        origins = sorted({parse_date(v) for v in args.origins.split(",")})
        effective_origins = [str(origin) for origin in origins]
        cutoffs = [parse_date(v) for v in args.cutoffs.split(",")]
        if not set(cutoffs).issubset(origins):
            raise ValueError("each cutoff needs a forecast origin")
        as_of = parse_date(args.as_of)
        if any(cutoff > as_of for cutoff in cutoffs):
            raise ValueError("evaluation as-of precedes fit cutoff")
        if args.backend != "ridge":
            import importlib

            importlib.import_module(args.backend)
        protocol_hash = None
        begin_final_scoring = None
        if args.holdout:
            if not args.frozen_protocol:
                raise ValueError("holdout requires a preregistered frozen protocol")
            raw = args.frozen_protocol.read_bytes()
            protocol = json.loads(raw)
            expected = {
                "split_version": SPLIT_VERSION,
                "backend": args.backend,
                "cutoffs": args.cutoffs,
                "origins": effective_origins,
                "evaluation_asof": str(as_of),
                "label_definition": "resale_cell_median_month_t_plus_6_v1",
                "input_mode": args.input_mode,
            }
            if any(protocol.get(k) != v for k, v in expected.items()):
                raise ValueError("frozen protocol does not match this experiment")
            if len(cutoffs) != 1:
                raise ValueError("one final cutoff only")
            protocol_hash = sha256(raw).hexdigest()
            lock = OUTPUT_ROOT / HOLDOUT_RECEIPT_NAMES[bool(rows and rows[0].synthetic)]

            def reserve_receipt():
                # Catch outputs created since the initial check. The two file
                # writes are not a transaction; a later output I/O failure
                # must not erase a receipt after scoring has started.
                require_new_output(output)
                with lock.open("x", encoding="utf-8") as stream:
                    json.dump(
                        {
                            "protocol_sha256": protocol_hash,
                            "input_sha256": digest,
                            "origins": effective_origins,
                            "evaluation_asof": str(as_of),
                            "status": "attempt_started_no_repeated_final_test",
                        },
                        stream,
                    )

            begin_final_scoring = reserve_receipt
        examples = build_examples(rows, origins, input_mode=args.input_mode)
        report = backtest(
            examples,
            cutoffs,
            backend=args.backend,
            holdout=args.holdout,
            evaluation_asof=as_of,
            begin_final_scoring=begin_final_scoring,
        )
        report.update(
            input_sha256=digest,
            protocol_sha256=protocol_hash,
            origins=effective_origins,
            input_transactions=len(rows),
            examples=len(examples),
            train_cities=TRAIN_CITIES,
            holdout_cities=HOLDOUT_CITIES,
            label_definition="resale_cell_median_month_t_plus_6_v1",
        )
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(str(output))


if __name__ == "__main__":
    main()
