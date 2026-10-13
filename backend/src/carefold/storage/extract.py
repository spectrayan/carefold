# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Multi-format document intelligence and text extraction engine (AU-22).

Supports:
- PDF: pypdf page-by-page extraction, sparse text (<30 chars/page) OCR fallback,
       regex stream fallback (extract_text_from_pdf_bytes), encrypted PDF handling.
- Images: PIL + pytesseract OCR with graceful fallback if binaries/libraries absent.
- Text formats: UTF-8 decoding with replace fallback (.txt, .md, .json, .csv, .tsv, .yaml).
- CAS helper: extract_cas_document / extract_cas_attachment reading from Content-Addressed Storage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import io
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Literal, Optional

from carefold.logging import get_logger
from carefold.storage.cas import read_cas_file
from carefold.tools.attach_read import extract_text_from_pdf_bytes

logger = get_logger("carefold.storage.extract")

# Optional dependency detection
try:
    import pypdf
    _PYPDF_AVAILABLE = True
except ImportError:
    pypdf = None
    _PYPDF_AVAILABLE = False

try:
    from PIL import Image
    import pytesseract
    _OCR_AVAILABLE = True
except ImportError:
    Image = None
    pytesseract = None
    _OCR_AVAILABLE = False


@dataclass
class ExtractionResult:
    """Standardized result of multi-format document text extraction."""

    text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: Literal["completed", "failed", "empty"] = "completed"
    format: str = "unknown"
    ocr_applied: bool = False
    page_count: int = 1
    ocr_invoked: bool = False

    def __post_init__(self) -> None:
        if self.ocr_applied and not self.ocr_invoked:
            self.ocr_invoked = True
        elif self.ocr_invoked and not self.ocr_applied:
            self.ocr_applied = True


SPARSE_TEXT_THRESHOLD_CHARS_PER_PAGE = 30.0

TEXT_EXTENSIONS = {
    ".txt": "text",
    ".text": "text",
    ".log": "text",
    ".rst": "text",
    ".md": "markdown",
    ".markdown": "markdown",
    ".json": "json",
    ".csv": "csv",
    ".tsv": "tsv",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".html": "html",
    ".htm": "html",
    ".xml": "xml",
}

IMAGE_EXTENSIONS = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".tiff": "tiff",
    ".tif": "tiff",
    ".bmp": "bmp",
    ".webp": "webp",
}


def is_ocr_available() -> bool:
    """Returns True if both PIL and pytesseract are available."""
    return _OCR_AVAILABLE


def extract_document_text(
    content: bytes,
    filename: str,
    mime_type: Optional[str] = None,
) -> ExtractionResult:
    """Extracts plain text and metadata from raw document bytes across multiple formats."""
    try:
        fmt = _detect_format(filename, mime_type, content or b"")

        if not content:
            if fmt in TEXT_EXTENSIONS.values():
                return ExtractionResult(
                    text="",
                    metadata={"reason": "empty_content", "byte_size": 0},
                    status="empty",
                    format=fmt,
                    ocr_applied=False,
                    page_count=0,
                )
            else:
                return ExtractionResult(
                    text="",
                    metadata={"error": "Empty file content", "byte_size": 0},
                    status="failed",
                    format=fmt,
                    ocr_applied=False,
                    page_count=0,
                )

        if fmt == "pdf":
            return _extract_pdf(content)
        elif fmt in IMAGE_EXTENSIONS.values() or fmt == "image":
            return _extract_image(content, fmt)
        elif fmt in TEXT_EXTENSIONS.values():
            return _extract_text(content, fmt)
        else:
            return _extract_unknown_or_binary(content, fmt)

    except Exception as exc:
        logger.error("extract_document_text_unexpected_error", filename=filename, error=str(exc))
        return ExtractionResult(
            text="",
            metadata={"error": str(exc)},
            status="failed",
            format=_detect_format(filename, mime_type, content or b""),
            ocr_applied=False,
            page_count=0,
        )


def extract_cas_document(
    carefold_home: Path,
    user_id: Optional[str],
    profile_id: Optional[str],
    sha256_hash: str,
    filename: str,
    mime_type: Optional[str] = None,
) -> ExtractionResult:
    """Reads a document from Content-Addressed Storage (CAS) and extracts text."""
    try:
        content = read_cas_file(
            carefold_home=carefold_home,
            user_id=user_id,
            profile_id=profile_id,
            sha256_hash=sha256_hash,
        )
    except FileNotFoundError as fnf:
        logger.warning("cas_file_not_found_for_extraction", sha256=sha256_hash, error=str(fnf))
        return ExtractionResult(
            text="",
            metadata={"error": f"CAS file not found: {fnf}", "sha256": sha256_hash},
            status="failed",
            format=_detect_format(filename, mime_type, b""),
            ocr_applied=False,
            page_count=0,
        )
    except Exception as exc:
        logger.error("cas_read_error_for_extraction", sha256=sha256_hash, error=str(exc))
        return ExtractionResult(
            text="",
            metadata={"error": f"CAS read error: {exc}", "sha256": sha256_hash},
            status="failed",
            format=_detect_format(filename, mime_type, b""),
            ocr_applied=False,
            page_count=0,
        )

    return extract_document_text(content=content, filename=filename, mime_type=mime_type)


# Alias for backwards compatibility
extract_cas_attachment = extract_cas_document


def _detect_format(filename: str, mime_type: Optional[str], content: bytes) -> str:
    """Identifies the canonical document format from filename, mime-type, or magic bytes."""
    ext = Path(filename).suffix.lower()
    mime = (mime_type or "").strip().lower()

    if ext == ".pdf" or mime == "application/pdf" or content.startswith(b"%PDF"):
        return "pdf"

    if ext in IMAGE_EXTENSIONS:
        return IMAGE_EXTENSIONS[ext]
    if mime.startswith("image/"):
        sub = mime.split("/", 1)[1]
        return sub if sub in IMAGE_EXTENSIONS.values() else "image"

    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if content.startswith(b"BM"):
        return "bmp"
    if content.startswith(b"II*\x00") or content.startswith(b"MM\x00*"):
        return "tiff"

    if ext in TEXT_EXTENSIONS:
        return TEXT_EXTENSIONS[ext]
    if mime.startswith("text/"):
        return "text"
    if mime in ("application/json", "application/x-yaml", "application/yaml"):
        return mime.split("/")[-1].replace("x-", "")

    return "unknown"


def _extract_pdf(content: bytes) -> ExtractionResult:
    """Extracts text from PDF via pypdf with sparse OCR fallback and regex stream fallback."""
    if _PYPDF_AVAILABLE:
        try:
            reader = pypdf.PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                try:
                    decrypted = reader.decrypt("")
                    # In pypdf, decrypt returns 0 if failed, or 1/2 if successful
                    if decrypted == 0:
                        return ExtractionResult(
                            text="",
                            metadata={"error": "PDF is password-protected and encrypted", "encrypted": True},
                            status="failed",
                            format="pdf",
                            ocr_applied=False,
                            page_count=0,
                        )
                except Exception as dec_err:
                    return ExtractionResult(
                        text="",
                        metadata={"error": f"PDF is encrypted: {dec_err}", "encrypted": True},
                        status="failed",
                        format="pdf",
                        ocr_applied=False,
                        page_count=0,
                    )

            page_count = len(reader.pages)
            if page_count == 0:
                return ExtractionResult(
                    text="",
                    metadata={"parser": "pypdf", "page_count": 0},
                    status="empty",
                    format="pdf",
                    ocr_applied=False,
                    page_count=0,
                )

            page_texts: List[str] = []
            for page in reader.pages:
                try:
                    txt = page.extract_text() or ""
                    page_texts.append(txt.strip())
                except Exception as p_err:
                    logger.debug("pypdf_page_extract_error", error=str(p_err))
                    page_texts.append("")

            combined_text = "\n\n".join(t for t in page_texts if t).strip()
            total_chars = len(combined_text)
            avg_chars = total_chars / max(1, page_count)

            # Sparse text check (< 30 chars/page)
            if avg_chars < SPARSE_TEXT_THRESHOLD_CHARS_PER_PAGE:
                if is_ocr_available():
                    ocr_pages: List[str] = []
                    for page in reader.pages:
                        page_ocr: List[str] = []
                        images = getattr(page, "images", [])
                        for img_obj in images:
                            try:
                                img = Image.open(io.BytesIO(img_obj.data))
                                ocr_t = pytesseract.image_to_string(img).strip()
                                if ocr_t:
                                   page_ocr.append(ocr_t)
                            except Exception as ocr_err:
                                logger.debug("pdf_image_ocr_failed", error=str(ocr_err))
                        if page_ocr:
                            ocr_pages.append("\n".join(page_ocr))

                    ocr_text = "\n\n".join(ocr_pages).strip()
                    if len(ocr_text) > len(combined_text):
                        return ExtractionResult(
                            text=ocr_text,
                            metadata={
                                "parser": "pypdf+ocr",
                                "page_count": page_count,
                                "avg_chars": avg_chars,
                                "sparse_text": True,
                                "ocr_applied": True,
                            },
                            status="completed",
                            format="pdf",
                            ocr_applied=True,
                            page_count=page_count,
                        )

                # Return pypdf text with sparse note
                status = "completed" if combined_text else "empty"
                return ExtractionResult(
                    text=combined_text,
                    metadata={
                        "parser": "pypdf",
                        "page_count": page_count,
                        "avg_chars": avg_chars,
                        "sparse_text": True,
                        "ocr_available": is_ocr_available(),
                        "ocr_applied": False,
                    },
                    status=status,
                    format="pdf",
                    ocr_applied=False,
                    page_count=page_count,
                )

            # Dense text extracted successfully
            return ExtractionResult(
                text=combined_text,
                metadata={
                    "parser": "pypdf",
                    "page_count": page_count,
                    "avg_chars": avg_chars,
                    "char_count": total_chars,
                },
                status="completed",
                format="pdf",
                ocr_applied=False,
                page_count=page_count,
            )

        except Exception as pypdf_err:
            logger.debug("pypdf_parsing_failed_fallback_to_stream", error=str(pypdf_err))

    # Fallback to pure-Python regex stream parser
    try:
        stream_text = extract_text_from_pdf_bytes(content)
        if stream_text and stream_text != "[Notice: PDF document contains no extractable text layer or is image-scanned.]":
            return ExtractionResult(
                text=stream_text,
                metadata={"parser": "regex_stream", "fallback_from_pypdf": True},
                status="completed",
                format="pdf",
                ocr_applied=False,
                page_count=1,
            )
        else:
            if not content.startswith(b"%PDF"):
                return ExtractionResult(
                    text="",
                    metadata={"parser": "regex_stream", "error": "Invalid or corrupt PDF stream"},
                    status="failed",
                    format="pdf",
                    ocr_applied=False,
                    page_count=0,
                )
            return ExtractionResult(
                text="",
                metadata={"parser": "regex_stream", "notice": "no_extractable_text_layer"},
                status="empty",
                format="pdf",
                ocr_applied=False,
                page_count=1,
            )
    except Exception as fallback_err:
        logger.warning("pdf_all_parsers_failed", error=str(fallback_err))
        return ExtractionResult(
            text="",
            metadata={"parser": "none", "error": str(fallback_err)},
            status="failed",
            format="pdf",
            ocr_applied=False,
            page_count=0,
        )


def _extract_image(content: bytes, fmt: str) -> ExtractionResult:
    """Extracts text from raster images using pytesseract with defensive error handling."""
    if not is_ocr_available():
        return ExtractionResult(
            text="",
            metadata={"ocr_available": False, "note": "PIL or pytesseract not installed"},
            status="empty",
            format=fmt,
            ocr_applied=False,
            page_count=1,
        )

    try:
        image = Image.open(io.BytesIO(content))
        img_format = image.format or fmt
        img_size = list(image.size)
        img_mode = image.mode

        text = pytesseract.image_to_string(image).strip()
        status = "completed" if text else "empty"

        return ExtractionResult(
            text=text,
            metadata={
                "engine": "pytesseract",
                "image_format": img_format,
                "image_size": img_size,
                "image_mode": img_mode,
            },
            status=status,
            format=fmt,
            ocr_applied=bool(text),
            page_count=1,
        )
    except (getattr(pytesseract, "TesseractNotFoundError", OSError), OSError) as err:
        logger.warning("tesseract_binary_not_found", error=str(err))
        return ExtractionResult(
            text="",
            metadata={"error": "Tesseract binary not found on system PATH", "ocr_available": False},
            status="empty",
            format=fmt,
            ocr_applied=False,
            page_count=1,
        )
    except getattr(pytesseract, "TesseractError", Exception) as terr:
        logger.warning("tesseract_execution_error", error=str(terr))
        return ExtractionResult(
            text="",
            metadata={"error": f"Tesseract execution error: {terr}", "ocr_available": True},
            status="failed",
            format=fmt,
            ocr_applied=False,
            page_count=1,
        )
    except Exception as img_err:
        logger.warning("image_decoding_failed", error=str(img_err))
        return ExtractionResult(
            text="",
            metadata={"error": f"Failed to decode image: {img_err}"},
            status="failed",
            format=fmt,
            ocr_applied=False,
            page_count=1,
        )


def _extract_text(content: bytes, fmt: str) -> ExtractionResult:
    """Extracts text from structured and unstructured plain-text formats."""
    try:
        text = content.decode("utf-8")
        decode_fallback = False
    except UnicodeDecodeError:
        text = content.decode("utf-8", errors="replace")
        decode_fallback = True

    cleaned_text = text.strip()
    status = "completed" if cleaned_text else "empty"

    metadata: Dict[str, Any] = {
        "encoding": "utf-8",
        "decode_fallback": decode_fallback,
        "char_count": len(cleaned_text),
        "line_count": len(cleaned_text.splitlines()) if cleaned_text else 0,
    }

    if fmt == "json" and cleaned_text:
        try:
            parsed = json.loads(cleaned_text)
            if isinstance(parsed, dict):
                metadata["json_keys"] = list(parsed.keys())[:20]
            elif isinstance(parsed, list):
                metadata["json_array_length"] = len(parsed)
        except Exception:
            metadata["json_valid"] = False

    return ExtractionResult(
        text=cleaned_text,
        metadata=metadata,
        status=status,
        format=fmt,
        ocr_applied=False,
        page_count=1,
    )


def _extract_unknown_or_binary(content: bytes, fmt: str) -> ExtractionResult:
    """Handles unknown file extensions by attempting safe UTF-8 decoding before failing."""
    if b"\x00" in content[:1024]:
        return ExtractionResult(
            text="",
            metadata={"error": "Unsupported binary file format", "format": fmt},
            status="failed",
            format="binary",
            ocr_applied=False,
            page_count=0,
        )

    try:
        text = content.decode("utf-8")
        cleaned_text = text.strip()
        status = "completed" if cleaned_text else "empty"
        return ExtractionResult(
            text=cleaned_text,
            metadata={"encoding": "utf-8", "inferred_text": True},
            status=status,
            format="text",
            ocr_applied=False,
            page_count=1,
        )
    except UnicodeDecodeError:
        return ExtractionResult(
            text="",
            metadata={"error": "Non-text binary file format", "format": fmt},
            status="failed",
            format="binary",
            ocr_applied=False,
            page_count=0,
        )


__all__ = [
    "ExtractionResult",
    "SPARSE_TEXT_THRESHOLD_CHARS_PER_PAGE",
    "is_ocr_available",
    "extract_document_text",
    "extract_cas_document",
    "extract_cas_attachment",
]
