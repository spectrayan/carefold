# Carefold — Healthcare AI Agent Marketplace & Runtime
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""Closed Phase 0 tool: attach-read.

Reads text, CSV/TSV, or PDF files located strictly within attachments/.
CSV/TSV files are rendered as Markdown tables for downstream extraction.
Pure-Python PDF text extraction is included for 100% offline self-containment.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import os
from pathlib import Path
import re
from typing import Any, Dict, Optional, Set

from sqlalchemy import select

from carefold.config import settings
from carefold.constants.defaults import (
    ALLOWED_ATTACHMENT_EXTENSIONS as CONST_ALLOWED_ATTACHMENT_EXTENSIONS,
    ALLOWED_TEXT_EXTENSIONS as CONST_ALLOWED_TEXT_EXTENSIONS,
    MAX_FILE_SIZE_BYTES,
)
from carefold.constants.paths import ATTACHMENTS_DIR
from carefold.db.models import Attachment
from carefold.db.session import get_session_factory
from carefold.logging import get_logger
from carefold.schemas.tool import ToolResult
from carefold.storage.cas import get_cas_path
from carefold.tools.sandbox import SandboxSecurityError, resolve_sandboxed_path

logger = get_logger("carefold.tools.attach_read")

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
    """Executes the attach-read tool securely within the attachments sandbox.

    Enforces:
    1. Fail-closed ToolContext requirement: non-empty user_id and profile_id are mandatory.
    2. Zero root directory fallback: never falls back to root base_dir.
    3. Strict cross-profile blocking: reject cross-profile attempts immediately.
    4. Database-grounded resolution: verifies attachment record in carefold.db when DB is active.
    5. Content-Addressed Storage (CAS) resolution: queries <carefold_home>/data/files/<uid>/<pid>/<sha256>.
    6. Cached plain-text fast path: returns extracted_text from DB when available.
    """
    try:
        raw_path = params.get("path") or params.get("file_path") or params.get("filename") or params.get("id")
        if not raw_path or not isinstance(raw_path, str):
            return ToolResult(
                success=False,
                output=None,
                error='Parameter "path" must be a non-empty string.',
            )

        # 1. Enforce Fail-Closed Context: Non-empty user_id and profile_id are mandatory
        user_id = getattr(context, "user_id", None)
        profile_id = getattr(context, "profile_id", None)
        uid_str = user_id.strip() if (isinstance(user_id, str) and user_id.strip()) else None
        pid_str = profile_id.strip() if (isinstance(profile_id, str) and profile_id.strip()) else None

        if not pid_str:
            return ToolResult(
                success=False,
                output=None,
                error="Security violation: profile_id is required for attach_read (fail-closed). Execution denied.",
            )
        if not uid_str:
            return ToolResult(
                success=False,
                output=None,
                error="Security violation: user_id is required for attach_read (fail-closed). Execution denied.",
            )

        # 2. Determine base directory for scoped storage
        ws_root = getattr(context, "workspace_root", None)
        if ws_root:
            ws_path = Path(ws_root)
            if (ws_path / "uploads").is_dir():
                base_dir = ws_path / "uploads"
            elif (ws_path / ATTACHMENTS_DIR).is_dir():
                base_dir = ws_path / ATTACHMENTS_DIR
            else:
                base_dir = ws_path / ATTACHMENTS_DIR
        else:
            base_dir = settings.get_uploads_dir()

        # Invariant: Scoped attachments directory is strictly partitioned by user_id and profile_id.
        # NEVER fall back to root base_dir.
        attachments_dir = base_dir / uid_str / pid_str

        # 3. Path Traversal & Protocol Attacks Defense
        if "\0" in raw_path:
            return ToolResult(
                success=False,
                output=None,
                error="Path traversal forbidden: Null byte detected in path.",
            )
        for scheme in ("file://", "http://", "https://", "ftp://", "gopher://", "data:", "javascript:", "blob:", "about:"):
            if raw_path.lower().startswith(scheme):
                return ToolResult(
                    success=False,
                    output=None,
                    error="Path traversal forbidden: URI schemes are not permitted.",
                )

        # Reject absolute paths that escape the scoped attachments directory
        if (
            os.path.isabs(raw_path.strip())
            or raw_path.strip().startswith(("/", "\\"))
            or (len(raw_path.strip()) >= 2 and raw_path.strip()[1] == ":")
        ):
            try:
                candidate_abs = Path(raw_path.strip()).resolve()
                candidate_abs.relative_to(attachments_dir.resolve())
            except Exception:
                return ToolResult(
                    success=False,
                    output=None,
                    error=f'Path traversal forbidden: Path "{raw_path}" escapes allowed directory.',
                )

        clean_path = raw_path.strip().lstrip("/\\")
        norm_path = clean_path.replace("\\", "/")

        # Reject relative paths with traversal segments that escape the scoped directory
        if any(p.startswith("..") for p in norm_path.split("/") if p):
            return ToolResult(
                success=False,
                output=None,
                error=f'Path traversal forbidden: Path "{raw_path}" escapes allowed directory.',
            )

        # 4. Detect Cross-Tenant / Cross-Profile Access Attempts in Path Segments
        path_parts = [p for p in norm_path.split("/") if p and p != "." and p != ".."]

        # Check explicit root-prefixed paths: attachments/ or uploads/
        if path_parts and path_parts[0] in ("attachments", "uploads"):
            sub_parts = path_parts[1:]
            if len(sub_parts) >= 2:
                if sub_parts[0] != uid_str or sub_parts[1] != pid_str:
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"Security violation: Cross-profile attachment access denied for '{raw_path}'.",
                    )
            elif len(sub_parts) == 1 and sub_parts[0] != uid_str and sub_parts[0] != pid_str:
                # Check if sub_parts[0] exists as another partition on disk
                if (base_dir / sub_parts[0]).is_dir():
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"Security violation: Cross-profile attachment access denied for '{raw_path}'.",
                    )

        # Detect paths beginning with explicit foreign user/profile prefix (e.g. user_alice/profile_alice/chart.txt)
        if len(path_parts) >= 3:
            part_u, part_p = path_parts[0], path_parts[1]
            if part_u != uid_str or part_p != pid_str:
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Security violation: Cross-profile attachment access denied for '{raw_path}'.",
                )

        # Detect paths beginning with a foreign user directory on disk
        if len(path_parts) >= 2:
            part_u = path_parts[0]
            if part_u != uid_str and (base_dir / part_u).is_dir():
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Security violation: Cross-profile attachment access denied for '{raw_path}'.",
                )

        # Strip caller's own user/profile prefix if explicitly qualified
        prefixes_to_strip: list[str] = [
            f"attachments/{uid_str}/{pid_str}/",
            f"attachments\\{uid_str}\\{pid_str}\\",
            f"uploads/{uid_str}/{pid_str}/",
            f"uploads\\{uid_str}\\{pid_str}\\",
            f"{uid_str}/{pid_str}/",
            f"{uid_str}\\{pid_str}\\",
            "attachments/",
            "attachments\\",
            "uploads/",
            "uploads\\",
        ]
        for prefix in prefixes_to_strip:
            if clean_path.startswith(prefix):
                clean_path = clean_path[len(prefix):]
                break

        target_ident = os.path.basename(clean_path.replace("\\", "/"))

        # 5. Database-Backed Resolution Scoped to (user_id, profile_id)
        att_record: Optional[Attachment] = None
        db_active = False

        try:
            session_factory = get_session_factory()
            async with session_factory() as db:
                # 5a. Lookup attachment belonging to active profile FIRST
                stmt = (
                    select(Attachment)
                    .where(
                        (Attachment.profile_id == pid_str)
                        & (
                            (Attachment.id == target_ident)
                            | (Attachment.id == clean_path)
                            | (Attachment.filename == target_ident)
                            | (Attachment.original_name == target_ident)
                            | (Attachment.sha256_hash == target_ident)
                            | (Attachment.storage_key == clean_path)
                        )
                    )
                    .limit(1)
                )
                res = await db.execute(stmt)
                att_record = res.scalars().first()
                db_active = True

                # 5b. If NOT found in active profile, check if this is an attempt to access a foreign attachment
                if att_record is None:
                    cross_stmt = (
                        select(Attachment.id)
                        .where(
                            (Attachment.profile_id != pid_str)
                            & (
                                (Attachment.id == target_ident)
                                | (Attachment.id == clean_path)
                                | (Attachment.filename == target_ident)
                                | (Attachment.original_name == target_ident)
                                | (Attachment.sha256_hash == target_ident)
                                | (Attachment.storage_key == clean_path)
                            )
                        )
                        .limit(1)
                    )
                    cross_res = await db.execute(cross_stmt)
                    if cross_res.scalars().first() is not None:
                        return ToolResult(
                            success=False,
                            output=None,
                            error=f"Security violation: Cross-profile attachment access denied for '{raw_path}'.",
                        )
        except Exception as db_err:
            logger.debug("Database attachment query skipped: %s", db_err)
            db_active = False
            att_record = None


        # 6. Fast-path: Return cached plain text if available
        if att_record is not None and att_record.extracted_text:
            ext_lower = Path(att_record.filename).suffix.lower()
            if ext_lower not in DELIMITED_FORMATS:
                return ToolResult(
                    success=True,
                    output={
                        "path": raw_path,
                        "format": "pdf" if ext_lower == ".pdf" else "text",
                        "size_bytes": att_record.size_bytes,
                        "content": att_record.extracted_text,
                    },
                )

        # 7. Physical File Resolution: Content-Addressed Storage (CAS) or scoped directory
        safe_file_path: Optional[Path] = None

        # Check CAS path first
        target_sha256 = att_record.sha256_hash if att_record else None
        if target_sha256:
            try:
                cas_path = get_cas_path(
                    settings.home_dir,
                    att_record.user_id or uid_str,
                    att_record.profile_id or pid_str,
                    target_sha256,
                )
                if cas_path.is_file():
                    safe_file_path = cas_path
            except ValueError:
                pass

        if safe_file_path is None:
            target_filename = att_record.filename if att_record else clean_path
            safe_file_path = resolve_sandboxed_path(attachments_dir, target_filename, must_exist=True)

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
        if att_record and not ext:
            ext = Path(att_record.filename).suffix.lower()

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
            if att_record and not att_record.extracted_text:
                try:
                    session_factory = get_session_factory()
                    async with session_factory() as db:
                        rec = await db.get(Attachment, att_record.id)
                        if rec:
                            rec.extracted_text = text
                            rec.extraction_status = "completed"
                            rec.updated_at = datetime.now(timezone.utc)
                            await db.commit()
                except Exception:
                    pass
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
            if att_record and not att_record.extracted_text:
                try:
                    session_factory = get_session_factory()
                    async with session_factory() as db:
                        rec = await db.get(Attachment, att_record.id)
                        if rec:
                            rec.extracted_text = extracted_text
                            rec.extraction_status = "completed"
                            rec.updated_at = datetime.now(timezone.utc)
                            await db.commit()
                except Exception:
                    pass
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

