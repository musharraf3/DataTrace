"""Headless incident import, investigation and artifact export."""

import argparse
import json
from pathlib import Path

from .cases import make_case
from .inputs import bundle_dict, load_bundle
from .investigator import Investigation, offline_walkthrough
from .meta import MetaAPIError, investigate_meta, investigate_baseline
from .reporting import markdown_report
from .scenarios import SCENARIOS, make_realistic_case


def _print_event(event):
    kind = event["type"]
    if kind == "tool_call":
        print(f"[{event['t']:6.1f}s] {event['tool']}: {event.get('purpose') or event.get('question') or ''}", flush=True)
    elif kind in {"diagnosis", "review", "clarification", "verified"}:
        detail = event.get("classification") or event.get("verdict") or event.get("question") or event.get("reason")
        print(f"[{event['t']:6.1f}s] {kind}: {detail}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="datatrace")
    commands = parser.add_subparsers(dest="command", required=True)
    sample = commands.add_parser("sample", help="Create a reusable incident input template.")
    sample.add_argument("--family", choices=["duplicate_join", "dropped_records", "date_filter", "growth", "ambiguous"], default="duplicate_join")
    sample.add_argument("--realistic", choices=list(SCENARIOS), help="Write a ~4k-order realistic incident instead.")
    sample.add_argument("--output", default="incident.json")
    run = commands.add_parser("investigate", help="Investigate an incident JSON bundle.")
    run.add_argument("incident")
    run.add_argument("--mode", choices=["offline", "meta", "baseline"], default="offline")
    run.add_argument("--allow-paid", action="store_true")
    run.add_argument("--review", action="store_true", help="Add the independent muse-wonder-1.0 reviewer (meta mode).")
    run.add_argument("--output-dir", default="artifacts/investigation")
    verify = commands.add_parser("verify", help="Independently check candidate SQL.")
    verify.add_argument("incident")
    verify.add_argument("sql_file")
    args = parser.parse_args(argv)
    try:
        if args.command == "sample":
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            incident = make_realistic_case(args.realistic) if args.realistic else make_case(args.family)
            destination.write_text(json.dumps(bundle_dict(incident), indent=2), encoding="utf-8")
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
        if args.mode == "meta":
            from .openweight import make_agent_client
            report = investigate_meta(incident, client=make_agent_client(), review=args.review, on_event=_print_event)
            report.pop("resume_state", None)
        else:
            report = {"offline": offline_walkthrough, "baseline": investigate_baseline}[args.mode](incident)
        destination = Path(args.output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (destination / "report.md").write_text(markdown_report(report), encoding="utf-8")
        print(json.dumps({"classification": report["classification"], "report_directory": str(destination)}, indent=2))
    except (OSError, ValueError, MetaAPIError) as exc:
        parser.exit(2, f"DataTrace: {exc}\n")
