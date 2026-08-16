"""Command-line interface for the historical-table pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from historical_table_pipeline import __version__
from historical_table_pipeline.config import load_profile
from historical_table_pipeline.io import sha256_file, write_json, write_jsonl
from historical_table_pipeline.providers.openai_compatible import (
    provider_config_from_profile,
    transcribe_page,
)
from historical_table_pipeline.publish import publish as publish_records
from historical_table_pipeline.render import render_pdf
from historical_table_pipeline.validation import validate_consensus
from historical_table_pipeline.workflow import (
    WorkflowError,
    apply_decision_file,
    export_review,
    load_consensus,
    reconcile_files,
)


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def _command_profile_validate(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    _print_json(
        {
            "valid": True,
            "profile": str(profile.path),
            "profile_id": profile.raw.get("profile_id"),
            "profile_version": profile.profile_version,
            "name": profile.name,
            "record_type": profile.record_type,
            "field_count": len(profile.fields),
            "expected_sources": profile.expected_sources,
            "parser": profile.raw.get("parser", {}).get("kind"),
            "claim_boundary": (
                "Structural validity does not prove that an untested document layout "
                "is supported."
            ),
        }
    )
    return 0


def _command_render(args: argparse.Namespace) -> int:
    pages = render_pdf(
        args.pdf,
        args.output,
        dpi=args.dpi,
        page_indices=args.page,
    )
    _print_json(
        {
            "page_count": len(pages),
            "output_directory": str(Path(args.output).expanduser().resolve()),
            "page_manifest": str(
                Path(args.output).expanduser().resolve() / "pages.jsonl"
            ),
        }
    )
    return 0


def _command_ocr(args: argparse.Namespace) -> int:
    if args.page_index < 0:
        raise WorkflowError("page-index must be zero or greater")
    profile = load_profile(args.profile)
    provider = provider_config_from_profile(profile, args.engine)
    rows = transcribe_page(
        args.image,
        profile=profile,
        provider=provider,
        document_id=args.document_id,
        source_pdf_page_index=args.page_index,
        allow_network=args.allow_network,
    )
    output = write_jsonl(args.output, rows)
    _print_json(
        {
            "engine_id": provider.engine_id,
            "engine_version": provider.model,
            "network_used": True,
            "row_count": len(rows),
            "output": str(output.resolve()),
            "output_sha256": sha256_file(output),
        }
    )
    return 0


def _command_reconcile(args: argparse.Namespace) -> int:
    result = reconcile_files(args.profile, args.input, args.output)
    _print_json(result)
    return 0


def _command_review_export(args: argparse.Namespace) -> int:
    _print_json(export_review(args.consensus, args.output))
    return 0


def _command_review_apply(args: argparse.Namespace) -> int:
    result = apply_decision_file(
        args.consensus,
        args.decisions,
        args.profile,
        args.output,
        default_reviewer=args.default_reviewer,
        default_decided_at=args.default_decided_at,
    )
    _print_json(result)
    return 0


def _command_validate(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    artifact, records = load_consensus(args.consensus)
    report = validate_consensus(records, profile)
    report["consensus_sha256"] = sha256_file(artifact)
    report["profile_sha256"] = sha256_file(profile.path)
    if args.report:
        write_json(args.report, report)
        report["report"] = str(Path(args.report).expanduser().resolve())
    _print_json(report)
    if not report["structurally_valid"]:
        return 1
    if report["unresolved_cell_count"] and not args.allow_unresolved:
        return 1
    return 0


def _publish_artifact(
    *,
    consensus: str | Path,
    profile_path: str | Path,
    output: str | Path,
    allow_unresolved: bool,
    research_formats: bool,
) -> dict[str, Any]:
    profile = load_profile(profile_path)
    artifact, records = load_consensus(consensus)
    report = validate_consensus(records, profile)
    if not report["structurally_valid"]:
        raise WorkflowError("publication blocked: consensus has structural errors")
    if report["unresolved_cell_count"] and not allow_unresolved:
        raise WorkflowError(
            "publication blocked: unresolved cells remain; review them or pass "
            "--allow-unresolved to publish uncertainty explicitly"
        )
    destination = Path(output).expanduser().resolve()
    quality = publish_records(
        records,
        profile,
        destination,
        include_research_formats=research_formats,
    )
    write_json(destination / "validation-report.json", report)
    publication = {
        "schema_version": "1",
        "consensus_sha256": sha256_file(artifact),
        "profile_sha256": sha256_file(profile.path),
        "allow_unresolved": allow_unresolved,
        "output_directory": str(destination),
        "record_count": len(records),
        "unresolved_cell_count": report["unresolved_cell_count"],
        "quality_summary": str(destination / "quality-summary.json"),
    }
    write_json(destination / "publication.json", publication)
    return {**publication, "quality": quality}


def _command_publish(args: argparse.Namespace) -> int:
    _print_json(
        _publish_artifact(
            consensus=args.consensus,
            profile_path=args.profile,
            output=args.output,
            allow_unresolved=args.allow_unresolved,
            research_formats=args.research_formats,
        )
    )
    return 0


def _demo_paths() -> tuple[Path, Path, Path, Path]:
    repository = Path(__file__).resolve().parents[2]
    fixture = repository / "examples" / "synthetic"
    profile = repository / "profiles" / "example-records.yaml"
    if fixture.is_dir() and profile.is_file():
        return (
            profile,
            fixture / "ocr" / "engine-a.jsonl",
            fixture / "ocr" / "engine-b.jsonl",
            fixture / "decisions" / "reconciliation.jsonl",
        )
    package_data = Path(__file__).resolve().parent / "data"
    fixture = package_data / "examples" / "synthetic"
    profile = package_data / "profiles" / "example-records.yaml"
    if fixture.is_dir() and profile.is_file():
        return (
            profile,
            fixture / "ocr" / "engine-a.jsonl",
            fixture / "ocr" / "engine-b.jsonl",
            fixture / "decisions" / "reconciliation.jsonl",
        )
    raise WorkflowError("the installed package does not contain the synthetic demo bundle")


def _command_demo(args: argparse.Namespace) -> int:
    profile, engine_a, engine_b, decisions = _demo_paths()
    reconciliation = reconcile_files(
        profile,
        [engine_a, engine_b],
        Path(args.output) / "reconciliations",
    )
    application = apply_decision_file(
        reconciliation["consensus"],
        decisions,
        profile,
        Path(reconciliation["run_directory"]) / "02-review",
        default_decided_at="2000-01-01T00:00:00Z",
    )
    publication_dir = Path(application["application_directory"]) / "publication"
    publication = _publish_artifact(
        consensus=application["reviewed_consensus"],
        profile_path=profile,
        output=publication_dir,
        allow_unresolved=False,
        research_formats=args.research_formats,
    )
    _print_json(
        {
            "demo": "complete",
            "network_used": False,
            "run_id": reconciliation["run_id"],
            "initial_unresolved_cells": reconciliation["unresolved_cells"],
            "compiled_decisions": application["compiled_decision_count"],
            "remaining_review_items": application["remaining_review_items"],
            "published_records": publication["record_count"],
            "publication_directory": publication["output_directory"],
            "claim_boundary": (
                "This synthetic demonstration verifies the workflow contract, not OCR "
                "accuracy on a real publication."
            ),
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="historical-table",
        description=(
            "Reconcile independent OCR transcriptions of historical record tables "
            "into auditable research data."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    profile_validate = subparsers.add_parser(
        "profile-validate", help="validate a document profile"
    )
    profile_validate.add_argument("profile", help="YAML profile path")
    profile_validate.set_defaults(handler=_command_profile_validate)

    render = subparsers.add_parser(
        "render", help="render selected PDF pages to local PNG images"
    )
    render.add_argument("pdf", help="source PDF path")
    render.add_argument("--output", required=True, help="output directory")
    render.add_argument("--dpi", type=int, default=300, help="rendering DPI (default: 300)")
    render.add_argument(
        "--page",
        type=int,
        action="append",
        help="zero-based PDF page index; repeat for multiple pages (default: all)",
    )
    render.set_defaults(handler=_command_render)

    ocr = subparsers.add_parser(
        "ocr", help="transcribe one page through an explicitly authorized network adapter"
    )
    ocr.add_argument("image", help="local page image")
    ocr.add_argument("--profile", required=True, help="YAML profile path")
    ocr.add_argument("--engine", required=True, help="profile OCR engine ID")
    ocr.add_argument("--document-id", required=True, help="stable source document ID")
    ocr.add_argument(
        "--page-index", required=True, type=int, help="zero-based page index in the full PDF"
    )
    ocr.add_argument("--output", required=True, help="output OCR JSONL path")
    ocr.add_argument(
        "--allow-network",
        action="store_true",
        help="confirm authorization to transmit the page to the configured provider",
    )
    ocr.set_defaults(handler=_command_ocr)

    reconcile = subparsers.add_parser(
        "reconcile", help="align and compare two or more independent OCR JSONL sources"
    )
    reconcile.add_argument("--profile", required=True, help="YAML profile path")
    reconcile.add_argument(
        "--input",
        required=True,
        action="append",
        help="canonical OCR JSONL path; repeat for each source",
    )
    reconcile.add_argument(
        "--output",
        required=True,
        help="run root; a content-derived run ID is appended",
    )
    reconcile.set_defaults(handler=_command_reconcile)

    review_export = subparsers.add_parser(
        "review-export", help="export unresolved cell packets and a decision template"
    )
    review_export.add_argument(
        "consensus", help="consensus JSONL path or reconciliation run directory"
    )
    review_export.add_argument("--output", required=True, help="review export directory")
    review_export.set_defaults(handler=_command_review_export)

    review_apply = subparsers.add_parser(
        "review-apply", help="compile and replay explicit review decisions"
    )
    review_apply.add_argument(
        "consensus", help="consensus JSONL path or reconciliation run directory"
    )
    review_apply.add_argument("--decisions", required=True, help="decision JSONL path")
    review_apply.add_argument("--profile", required=True, help="YAML profile path")
    review_apply.add_argument(
        "--output", help="application root; a content-derived application ID is appended"
    )
    review_apply.add_argument(
        "--default-reviewer",
        help="fallback reviewer for workflow-level legacy events",
    )
    review_apply.add_argument(
        "--default-decided-at",
        help="fallback ISO-8601 timestamp for workflow-level legacy events",
    )
    review_apply.set_defaults(handler=_command_review_apply)

    validate = subparsers.add_parser(
        "validate", help="validate structure, provenance, and unresolved state"
    )
    validate.add_argument(
        "consensus", help="consensus JSONL path or application/reconciliation directory"
    )
    validate.add_argument("--profile", required=True, help="YAML profile path")
    validate.add_argument("--report", help="optional validation JSON output path")
    validate.add_argument(
        "--allow-unresolved",
        action="store_true",
        help="return success when only unresolved cells remain",
    )
    validate.set_defaults(handler=_command_validate)

    publish = subparsers.add_parser(
        "publish", help="create research-facing JSONL, CSV, and quality outputs"
    )
    publish.add_argument(
        "consensus", help="reviewed consensus JSONL path or application directory"
    )
    publish.add_argument("--profile", required=True, help="YAML profile path")
    publish.add_argument("--output", required=True, help="publication directory")
    publish.add_argument(
        "--allow-unresolved",
        action="store_true",
        help="publish unresolved cells explicitly (default: block)",
    )
    publish.add_argument(
        "--research-formats",
        action="store_true",
        help="also create DuckDB and Parquet when the research extra is installed",
    )
    publish.set_defaults(handler=_command_publish)

    demo = subparsers.add_parser(
        "demo", help="run the bundled, offline, fully synthetic example"
    )
    demo.add_argument(
        "--output", default="runs/demo", help="demo output root (default: runs/demo)"
    )
    demo.add_argument(
        "--research-formats",
        action="store_true",
        help="also create DuckDB and Parquet when the research extra is installed",
    )
    demo.set_defaults(handler=_command_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


__all__ = ["build_parser", "main"]
