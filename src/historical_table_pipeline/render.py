"""Optional, permissively licensed PDF-to-page rendering adapter."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from historical_table_pipeline.io import sha256_file, write_jsonl


class PdfDependencyError(RuntimeError):
    """Raised when the optional PDF renderer is not installed."""


def render_pdf(
    pdf_path: str | Path,
    output_dir: str | Path,
    *,
    dpi: int = 300,
    page_indices: Iterable[int] | None = None,
) -> list[dict[str, Any]]:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise PdfDependencyError(
            "PDF rendering requires the optional 'pdf' extra: "
            "pip install 'historical-table-data-pipeline[pdf]'"
        ) from exc

    source = Path(pdf_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if dpi <= 0:
        raise ValueError("dpi must be positive")
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    document = pdfium.PdfDocument(source)
    requested = list(page_indices) if page_indices is not None else list(range(len(document)))
    metadata: list[dict[str, Any]] = []
    scale = dpi / 72.0
    source_hash = sha256_file(source)
    for source_index in requested:
        if source_index < 0 or source_index >= len(document):
            raise IndexError(f"PDF page index out of range: {source_index}")
        page = document[source_index]
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil()
        target = destination / f"page-{source_index + 1:04d}.png"
        image.save(target, format="PNG")
        metadata.append(
            {
                "source_file": source.name,
                "source_sha256": source_hash,
                "source_pdf_page_index": source_index,
                "image_file": target.name,
                "image_sha256": sha256_file(target),
                "dpi": dpi,
                "width_px": image.width,
                "height_px": image.height,
            }
        )
        bitmap.close()
        page.close()
    document.close()
    write_jsonl(destination / "pages.jsonl", metadata)
    return metadata
