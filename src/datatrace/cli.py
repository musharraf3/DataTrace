"""Headless incident import, investigation and artifact export."""

import argparse
import json
from pathlib import Path

from .cases import make_case
from .inputs import bundle_dict, load_bundle
from .investigator import Investigation, offline_walkthrough
from .meta import MetaAPIError, investigate_meta, investigate_baseline
from .reporting import markdown_report


def main(argv=None):
    parser = argparse.ArgumentParser(prog="datatrace")
    commands = parser.add_subparsers(dest="command", required=True)
    sample = commands.add_parser("sample", help="Create a reusable incident input template.")
    sample.add_argument("--family", choices=["duplicate_join", "dropped_records", "date_filter", "growth", "ambiguous"], default="duplicate_join")
    sample.add_argument("--output", default="incident.json")
    run = commands.add_parser("investigate", help="Investigate an incident JSON bundle.")
    run.add_argument("incident")
    run.add_argument("--mode", choices=["offline", "meta", "baseline"], default="offline")
    run.add_argument("--allow-paid", action="store_true")
    run.add_argument("--output-dir", default="artifacts/investigation")
    verify = commands.add_parser("verify", help="Independently check candidate SQL.")
    verify.add_argument("incident")
    verify.add_argument("sql_file")
    args = parser.parse_args(argv)
    try:
        if args.command == "sample":
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(bundle_dict(make_case(args.family)), indent=2), encoding="utf-8")
            print(f"Created {destination}")
            return
        incident = load_bundle(Path(args.incident).read_bytes())
        if args.command == "verify":
            session = Investigation(incident)
            try:
                result = session.verify(Path(args.sql_file).read_text(encoding="utf-8"))
            finally:
                session.close()
            print(json.dumps(result, indent=2))
            if not result["verified"]:
                raise SystemExit(1)
            return
        if args.mode != "offline" and not args.allow_paid:
            parser.error("Live modes require --allow-paid.")
        if args.mode != "offline":
            from dotenv import load_dotenv
            load_dotenv()
        function = {"offline": offline_walkthrough, "meta": investigate_meta, "baseline": investigate_baseline}[args.mode]
        report = function(incident)
        destination = Path(args.output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (destination / "report.md").write_text(markdown_report(report), encoding="utf-8")
        print(json.dumps({"classification": report["classification"], "report_directory": str(destination)}, indent=2))
    except (OSError, ValueError, MetaAPIError) as exc:
        parser.exit(2, f"DataTrace: {exc}\n")
