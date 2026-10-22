"""Command line for market research. Database-free; needs `requests`, and `openpyxl` for workbooks.

    python -m narxnoma.research run --targets products.xlsx --out research.xlsx
    python -m narxnoma.research run --targets list.txt --category smartphones --sources uzum,olcha
    python -m narxnoma.research workbook --from research.json --out research.xlsx --pivots ooxml
    python -m narxnoma.research check research.xlsx

`run` sweeps (24 h cache), matches, saves research.json next to the workbook so the workbook can
be rebuilt without fetching, and builds the workbook. Also reachable as `python -m narxnoma.cli
research ...`.
"""

import argparse
import logging
import sys
from pathlib import Path

from narxnoma.matching.keys import CATEGORIES


def _add_build_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--pivots",
        choices=("auto", "com", "ooxml", "none"),
        default="auto",
        help="PivotTables: auto = Excel COM if present else raw OOXML (default); "
        "com = Excel only (slicers, chart, Data Model); ooxml = no Excel needed; none",
    )
    p.add_argument(
        "--model",
        choices=("auto", "yes", "no"),
        default="auto",
        help="Power Pivot Data Model with the COM pivots: auto = probe, fall back to flat "
        "pivots (default); yes = fail if unavailable; no = skip",
    )
    p.add_argument(
        "--no-verify",
        action="store_true",
        help="skip the Excel recalculation check of the finished file",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="narxnoma.research",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="targets -> markets -> matched offers -> workbook")
    run.add_argument("--targets", required=True, help=".xlsx / .csv / .txt product list")
    run.add_argument(
        "--category", choices=sorted(CATEGORIES), help="category for products whose file gives none"
    )
    run.add_argument("--sources", help="comma-separated markets (default: all but glotr)")
    run.add_argument("--out", required=True, help="output .xlsx")
    run.add_argument("--json", help="where to save the research data (default: <out>.json)")
    run.add_argument("--title", default="Market research")
    run.add_argument("--cache-dir", default="database/research_cache")
    run.add_argument("--max-age-h", type=float, default=24)
    run.add_argument("--force", action="store_true", help="ignore the sweep cache")
    run.add_argument(
        "--usd-rate", type=float, help="UZS per USD for USD inputs (default: central bank, live)"
    )
    _add_build_args(run)

    wb = sub.add_parser("workbook", help="rebuild a workbook from saved research.json, no fetching")
    wb.add_argument("--from", dest="src", required=True, help="research.json from a previous run")
    wb.add_argument("--out", required=True)
    _add_build_args(wb)

    chk = sub.add_parser("check", help="open a workbook in Excel, recalculate, report errors")
    chk.add_argument("path")
    chk.add_argument("--save", action="store_true", help="also write the calculated values back")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.cmd == "check":
        from narxnoma.research.excel import pivots as com

        res = com.verify(args.path, save=args.save)
        print(res)
        n = com.error_count(res)
        return 0 if res.ok and not n else 1

    from narxnoma.research.build import make_workbook
    from narxnoma.research.model import Research

    if args.cmd == "workbook":
        research = Research.from_json(args.src)
    else:
        from narxnoma.research.run import run_research
        from narxnoma.research.targets import load_targets

        targets = load_targets(args.targets, default_category=args.category)
        if not targets:
            logging.error("no products found in %s", args.targets)
            return 1
        markets = [m.strip() for m in args.sources.split(",")] if args.sources else None
        research = run_research(
            targets,
            markets,
            cache_dir=args.cache_dir,
            max_age_h=args.max_age_h,
            force=args.force,
            title=args.title,
            usd_rate=args.usd_rate,
        )
        js = Path(args.json) if args.json else Path(args.out).with_suffix(".json")
        js.parent.mkdir(parents=True, exist_ok=True)
        research.to_json(js)
        logging.info("research data saved: %s", js)

    info = make_workbook(
        research, args.out, pivots=args.pivots, model=args.model, verify=not args.no_verify
    )
    print("\n".join(info["lines"]))
    print(
        f"wrote {info['out']}  pivots={info['pivots']}  "
        f"products={info['layout']['n_products']}  offers={info['layout']['n_offers']}"
    )
    return 1 if info["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
