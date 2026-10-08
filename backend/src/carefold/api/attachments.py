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

"""Attachments management and upload REST endpoint."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
from typing import Any, Dict, List
from fastapi import APIRouter, File, HTTPException, UploadFile

from carefold.config import settings
from carefold.constants.api import (
    HTTP_400_BAD_REQUEST,
    ROUTE_ATTACHMENTS,
)
from carefold.logging import get_logger

logger = get_logger("carefold.api.attachments")

router = APIRouter(tags=["Attachments"])

ALLOWED_EXTENSIONS: set[str] = {
    ".txt",
    ".pdf",
    ".md",
    ".json",
    ".csv",
    ".tsv",
    ".yaml",
    ".yml",
}
MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10 MB


def _sanitize_filename(name: str) -> str:
    """Sanitizes filename removing directory traversal and dangerous characters."""
    base = os.path.basename(name)
    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "_", base)
    return sanitized if sanitized not in (".", "..", "") else "unnamed_attachment.txt"


def _get_unique_filename(attachments_dir: Path, filename: str) -> tuple[str, bool]:
    """Finds a non-conflicting filename if the file already exists, returning (filename, renamed)."""
    target = attachments_dir / filename
    if not target.exists():
        return filename, False

    path_obj = Path(filename)
    stem = path_obj.stem
    ext = path_obj.suffix

    # Check if stem already ends with _<number>
    match = re.match(r"^(.*?)(?:_(\d+))$", stem)
    base_stem = stem
    counter = 1
    if match:
        base_stem = match.group(1)
        counter = int(match.group(2)) + 1

    candidate_name = f"{base_stem}_{counter}{ext}"
    while (attachments_dir / candidate_name).exists():
        counter += 1
        candidate_name = f"{base_stem}_{counter}{ext}"

    return candidate_name, True


@router.post(ROUTE_ATTACHMENTS, status_code=201)
async def upload_attachment(
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    """Uploads a document to the workspace attachments directory."""
    if not file or not file.filename:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="No file uploaded or missing filename.",
        )

    # Validate extension
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Allowed formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}.",
        )

    sanitized_name = _sanitize_filename(file.filename)
    attachments_dir = settings.get_attachments_dir()
    attachments_dir.mkdir(parents=True, exist_ok=True)

    final_name, renamed = _get_unique_filename(attachments_dir, sanitized_name)
    dest_path = attachments_dir / final_name

    # Read and check size
    content = await file.read()
    file_size = len(content)

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File size exceeds maximum limit of 10MB ({(file_size / (1024 * 1024)):.2f}MB).",
        )

    dest_path.write_bytes(content)

    rel_path = f"attachments/{final_name}"
    timestamp = datetime.now(timezone.utc).isoformat()

    logger.info(
        "attachment_uploaded",
        filename=final_name,
        original_filename=sanitized_name,
        renamed=renamed,
        size_bytes=file_size,
        path=rel_path,
    )

    return {
        "success": True,
        "filename": final_name,
        "path": rel_path,
        "size": file_size,
        "type": file.content_type or "application/octet-stream",
        "timestamp": timestamp,
        "renamed": renamed,
    }


@router.get(ROUTE_ATTACHMENTS)
async def list_attachments() -> List[Dict[str, Any]]:
    """Lists all files in the workspace attachments directory."""
    attachments_dir = settings.get_attachments_dir()
    if not attachments_dir.is_dir():
        return []

    results: List[Dict[str, Any]] = []
    for item in attachments_dir.iterdir():
        if item.is_file() and not item.name.startswith("."):
            stat = item.stat()
            results.append({
                "filename": item.name,
                "path": f"attachments/{item.name}",
                "size": stat.st_size,
                "timestamp": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            })

    results.sort(key=lambda x: x["timestamp"], reverse=True)
    return results


__all__ = ["router", "upload_attachment", "list_attachments"]
