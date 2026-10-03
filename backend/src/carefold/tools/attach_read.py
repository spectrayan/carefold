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

"""Closed Phase 0 tool: attach-read.

Reads text, CSV/TSV, or PDF files located strictly within attachments/.
CSV/TSV files are rendered as Markdown tables for downstream extraction.
Pure-Python PDF text extraction is included for 100% offline self-containment.
"""

from __future__ import annotations

import csv
import io
import os
import re
from pathlib import Path
from typing import Any, Dict, Set

from carefold.constants.defaults import (
    ALLOWED_ATTACHMENT_EXTENSIONS as CONST_ALLOWED_ATTACHMENT_EXTENSIONS,
    ALLOWED_TEXT_EXTENSIONS as CONST_ALLOWED_TEXT_EXTENSIONS,
    MAX_FILE_SIZE_BYTES,
)
from carefold.constants.paths import ATTACHMENTS_DIR
from carefold.schemas.tool import ToolResult
from carefold.tools.sandbox import SandboxSecurityError, resolve_sandboxed_path

ALLOWED_TEXT_EXTS: Set[str] = set(CONST_ALLOWED_TEXT_EXTENSIONS)
ALLOWED_ATTACHMENT_EXTENSIONS: Set[str] = set(CONST_ALLOWED_ATTACHMENT_EXTENSIONS)
MAX_FILE_SIZE: int = MAX_FILE_SIZE_BYTES

DELIMITED_FORMATS: Dict[str, str] = {".csv": "csv", ".tsv": "tsv"}
CSV_SNIFF_DELIMITERS = ",;\t"
CSV_SNIFF_SAMPLE_CHARS = 64 * 1024
HEADER_SNIFF_MAX_ROWS = 21


def extract_text_from_pdf_bytes(buffer: bytes) -> str:
    """Pure Python PDF text stream extractor.

    Extracts text objects enclosed in BT ... ET, extracting literal strings (Tj),
    hex strings <...>, and string arrays [(...) ... (...) TJ].
    """
    try:
        content = buffer.decode("latin1", errors="ignore")
    except Exception:
        content = str(buffer)

    text_chunks: list[str] = []

    # Match text objects BT (Begin Text) ... ET (End Text)
    bt_blocks = re.findall(r"BT[\s\S]*?ET", content)
    for block in bt_blocks:
        # 1. Match literal string operations: (Hello World) Tj
        tj_matches = re.findall(r"\(([^)]*)\)\s*Tj", block)
        for m in tj_matches:
            text_chunks.append(m)

        # 2. Match array operations: [(Hello) 10 (World)] TJ
        tj_arrays = re.findall(r"\[(.*?)\]\s*TJ", block)
        for arr in tj_arrays:
            inner_strs = re.findall(r"\(([^)]*)\)", arr)
            text_chunks.extend(inner_strs)

        # 3. Match hex strings: <48656c6c6f> Tj
        hex_matches = re.findall(r"<([0-9a-fA-F]+)>\s*Tj", block)
        for h in hex_matches:
            try:
                decoded = bytes.fromhex(h).decode("utf-8", errors="ignore")
                if decoded:
                    text_chunks.append(decoded)
            except Exception:
                pass

    if not text_chunks:
        return "[Notice: PDF document contains no extractable text layer or is image-scanned.]"

    # Clean unescaped sequences
    cleaned = " ".join(text_chunks)
    cleaned = re.sub(r"\\([()\\])", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


class _FixedDelimiterSniffer(csv.Sniffer):
    """Sniffer whose has_header() reuses the already-chosen delimiter instead of re-sniffing."""

    def __init__(self, delimiter: str) -> None:
        super().__init__()
        self._delimiter = delimiter

    def sniff(self, sample: str, delimiters: str | None = None) -> type[csv.Dialect]:
        class _Dialect(csv.excel):
            delimiter = self._delimiter

        return _Dialect


def _detect_header(rows: list[list[str]], delimiter: str) -> bool:
    """Conservatively decides whether the first row is a header.

    Sniffer.has_header() votes "header" when no other row matches the first row's
    width, so it is only consulted when at least one comparable data row exists.
    """
    sample_rows = rows[:HEADER_SNIFF_MAX_ROWS]
    if not any(len(row) == len(sample_rows[0]) for row in sample_rows[1:]):
        return False
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=delimiter).writerows(sample_rows)
    try:
        return _FixedDelimiterSniffer(delimiter).has_header(buffer.getvalue())
    except (csv.Error, StopIteration):
        return False


def _markdown_cell(value: str) -> str:
    return re.sub(r"\r\n|\r|\n", " ", value).replace("|", "\\|")


def format_delimited_as_markdown(text: str, ext: str) -> str | None:
    """Renders CSV/TSV text as a Markdown table.

    Returns None when the content is empty or cannot be parsed, so callers can
    fall back to returning the raw text.
    """
    if not text.strip():
        return None
    # A leading UTF-8 BOM is an encoding artifact, not part of the first cell.
    text = text.removeprefix("\ufeff")

    if ext == ".tsv":
        delimiter = "\t"
    else:
        try:
            delimiter = csv.Sniffer().sniff(
                text[:CSV_SNIFF_SAMPLE_CHARS], delimiters=CSV_SNIFF_DELIMITERS
            ).delimiter
        except csv.Error:
            delimiter = ","

    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
        rows = [row for row in reader if row]
    except csv.Error:
        return None
    if not rows:
        return None

    width = max(len(row) for row in rows)
    if _detect_header(rows, delimiter):
        header, body = rows[0], rows[1:]
    else:
        header, body = [f"Column {i}" for i in range(1, width + 1)], rows

    def render(cells: list[str]) -> str:
        padded = cells + [""] * (width - len(cells))
        return "| " + " | ".join(_markdown_cell(cell) for cell in padded) + " |"

    lines = [render(header), "| " + " | ".join(["---"] * width) + " |"]
    lines.extend(render(row) for row in body)
    return "\n".join(lines)


async def execute_attach_read(params: Dict[str, Any], context: Any) -> ToolResult:
    """Executes the attach-read tool securely within the attachments sandbox."""
    try:
        raw_path = params.get("path") or params.get("file_path")
        if not raw_path or not isinstance(raw_path, str):
            return ToolResult(
                success=False,
                output=None,
                error='Parameter "path" must be a non-empty string.',
            )

        # Determine workspace root and attachments directory
        ws_root = getattr(context, "workspace_root", None) or Path.cwd()
        attachments_dir = Path(ws_root) / ATTACHMENTS_DIR

        safe_file_path = resolve_sandboxed_path(attachments_dir, raw_path, must_exist=True)

        if not safe_file_path.is_file():
            return ToolResult(
                success=False,
                output=None,
                error=f'Path "{raw_path}" is a directory, not a file.',
            )

        file_size = safe_file_path.stat().st_size
        if file_size > MAX_FILE_SIZE:
            return ToolResult(
                success=False,
                output=None,
                error="File size exceeds maximum allowed limit (10MB).",
            )

        ext = safe_file_path.suffix.lower()

        # CSV/TSV handling: render as a Markdown table, falling back to raw text
        if ext in DELIMITED_FORMATS:
            buffer = safe_file_path.read_bytes()
            try:
                text = buffer.decode("utf-8")
                table = format_delimited_as_markdown(text, ext)
            except UnicodeDecodeError:
                text = buffer.decode("utf-8", errors="replace")
                table = None
            return ToolResult(
                success=True,
                output={
                    "path": raw_path,
                    "format": DELIMITED_FORMATS[ext] if table is not None else "text",
                    "size_bytes": file_size,
                    "content": table if table is not None else text,
                },
            )

        # Text file handling
        if ext in ALLOWED_TEXT_EXTS:
            text = safe_file_path.read_text(encoding="utf-8", errors="replace")
            return ToolResult(
                success=True,
                output={
                    "path": raw_path,
                    "format": "text",
                    "size_bytes": file_size,
                    "content": text,
                },
            )

        # PDF file handling
        if ext == ".pdf":
            buffer = safe_file_path.read_bytes()
            extracted_text = extract_text_from_pdf_bytes(buffer)
            return ToolResult(
                success=True,
                output={
                    "path": raw_path,
                    "format": "pdf",
                    "size_bytes": file_size,
                    "content": extracted_text,
                },
            )

        return ToolResult(
            success=False,
            output=None,
            error=f'Unsupported file format "{ext}": only PDF and plain text documents are permitted.',
        )

    except SandboxSecurityError as sec_err:
        return ToolResult(success=False, output=None, error=str(sec_err))
    except FileNotFoundError as fnf_err:
        return ToolResult(success=False, output=None, error=str(fnf_err))
    except Exception as err:
        return ToolResult(success=False, output=None, error=f"Failed to read attachment: {err}")


# Alias for compatibility with tests and tool runner
attach_read_tool = execute_attach_read

