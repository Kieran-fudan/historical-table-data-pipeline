from __future__ import annotations

from historical_table_pipeline.alignment import AlignmentConfig, align_rows
from historical_table_pipeline.consensus import (
    ConsensusConfig,
    build_consensus,
    consensus_records_from_dicts,
)
from historical_table_pipeline.models import ConsensusRecord, ConsensusStatus, RowInput


def make_row(engine_id: str, cells: dict[str, str | None]) -> RowInput:
    return RowInput(
        document_id="document-1",
        page_id="page-1",
        table_id="table-1",
        engine_id=engine_id,
        engine_version="1",
        source_row_index=0,
        source_pdf_page_index=4,
        printed_page_label="3",
        cells=cells,
        metadata={"prompt_hash": f"hash-{engine_id}"},
    )


def consensus_fixture() -> ConsensusRecord:
    rows = {
        "alpha": [
            make_row(
                "alpha",
                {
                    "catalog_code": "ＡＲＣ-20 ",
                    "location": "Vault A",
                    "note": "x",
                    "blank": "",
                    "single": "only-alpha",
                },
            )
        ],
        "beta": [
            make_row(
                "beta",
                {
                    "catalog_code": "ARC-20",
                    "location": "Vault A",
                    "note": "y",
                    "blank": None,
                },
            )
        ],
        "gamma": [
            make_row(
                "gamma",
                {
                    "catalog_code": "ARC-20",
                    "location": "Vault B",
                    "note": "z",
                    "blank": "   ",
                },
            )
        ],
    }
    groups = align_rows(
        rows,
        config=AlignmentConfig(field_weights={"catalog_code": 1}, anchor_engine="alpha"),
    )
    return build_consensus(
        groups,
        expected_engine_ids=("alpha", "beta", "gamma"),
        config=ConsensusConfig(
            fields=("catalog_code", "location", "note", "blank", "single")
        ),
    )[0]


def test_unanimous_majority_conflict_and_missing_are_explicit() -> None:
    record = consensus_fixture()

    assert record.cells["catalog_code"].status is ConsensusStatus.UNANIMOUS
    assert record.cells["catalog_code"].chosen_value == "ARC-20"
    assert record.cells["location"].status is ConsensusStatus.MAJORITY
    assert record.cells["location"].chosen_value == "Vault A"
    assert record.cells["note"].status is ConsensusStatus.CONFLICT
    assert record.cells["note"].chosen_value is None
    assert record.cells["blank"].status is ConsensusStatus.UNANIMOUS
    assert record.cells["blank"].chosen_value is None
    assert len(record.cells["blank"].supporting_candidate_ids) == 3
    assert record.cells["single"].status is ConsensusStatus.MISSING
    assert record.cells["single"].chosen_value == "only-alpha"
    assert record.cells["single"].missing_engine_ids == ("beta", "gamma")


def test_raw_candidates_and_full_provenance_are_lossless() -> None:
    record = consensus_fixture()
    candidates = record.cells["catalog_code"].candidates

    assert [candidate.raw_value for candidate in candidates] == [
        "ＡＲＣ-20 ",
        "ARC-20",
        "ARC-20",
    ]
    assert {candidate.provenance.engine_id for candidate in candidates} == {
        "alpha",
        "beta",
        "gamma",
    }
    assert candidates[0].provenance.metadata["prompt_hash"].startswith("hash-")
    assert len({candidate.candidate_id for candidate in candidates}) == 3


def test_consensus_artifact_has_a_lossless_round_trip() -> None:
    record = consensus_fixture()
    payload = record.to_dict()

    restored = ConsensusRecord.from_dict(payload)
    restored_many = consensus_records_from_dicts([payload])

    assert restored.to_dict() == payload
    assert restored_many[0].to_dict() == payload
    assert payload["anchor_engine_id"] == "alpha"
    assert "document_id" in payload and "document" not in payload
    assert "missing_engine_ids" in payload["cells"]["single"]
