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

"""Multi-format document intelligence and text extraction test suite (AU-22).

Covers:
- Plain text formats (.txt, .md, .json, .csv, .tsv, .yaml) and encoding fallback.
- Dense and sparse PDF extraction via pypdf with fallback to pure-Python regex stream.
- Corrupted and password-protected encrypted PDF handling without crashes.
- Raster image OCR handling and graceful degradation when OCR dependencies are absent.
- Unknown and binary format detection.
- Content-Addressed Storage (CAS) document extraction.
- Background extract_text job worker lifecycle, database status transitions, and downstream index_doc job enqueuing.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import MagicMock, patch
import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import pypdf

from carefold.db.models import Attachment, Base, Job as DBJob, Profile, User
from carefold.engine.job_runner import handle_extract_text_job
from carefold.storage.cas import read_cas_file, store_cas_file
from carefold.storage.extract import (
    ExtractionResult,
    extract_cas_document,
    extract_document_text,
    is_ocr_available,
)


@pytest.fixture
async def db_session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """In-memory SQLite database sessionmaker using StaticPool with schema initialized."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        u = User(
            id="user-extract-01",
            email="extract@carefold.local",
            username="extract_user",
            hashed_password="pw-hash-extract",
        )
        p = Profile(
            id="prof-extract-01",
            user_id="user-extract-01",
            name="Extract Profile",
            relationship="self",
        )
        session.add_all([u, p])
        await session.commit()

    yield session_factory
    await engine.dispose()


def _create_sample_pdf(text: str) -> bytes:
    """Creates a minimal valid PDF containing the specified text string."""
    encoded_text = text.replace("(", "\\(").replace(")", "\\)")
    stream_content = f"BT\n/F1 12 Tf\n50 700 Td\n({encoded_text}) Tj\nET\n".encode("latin1")
    stream_len = len(stream_content)

    pdf_body = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
        + f"4 0 obj << /Length {stream_len} >> stream\n".encode("ascii")
        + stream_content
        + b"endstream\nendobj\n"
        b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
        b"xref\n0 6\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"0000000244 00000 n \n"
        b"0000000380 00000 n \n"
        b"trailer << /Size 6 /Root 1 0 R >>\n"
        b"startxref\n450\n%%EOF\n"
    )
    return pdf_body


# =========================================================================
# 1. Plain Text Formats & Structured Text Tests
# =========================================================================

def test_extract_plain_text_files():
    """Verifies text extraction from .txt, .md, .csv, .tsv, and .yaml files."""
    # Plain text
    txt_content = b"Patient visited for routine cardiac checkup.\nBlood pressure: 120/80.\n"
    res_txt = extract_document_text(txt_content, filename="clinical_notes.txt")
    assert res_txt.status == "completed"
    assert res_txt.format == "text"
    assert "Patient visited for routine cardiac checkup" in res_txt.text
    assert res_txt.metadata["line_count"] == 2
    assert res_txt.metadata["char_count"] == len(txt_content.decode("utf-8").strip())
    assert res_txt.ocr_applied is False

    # Markdown
    md_content = b"# Cardiology Visit\n\n- Heart rate: 72 bpm\n- ECG: Normal sinus rhythm\n"
    res_md = extract_document_text(md_content, filename="summary.md")
    assert res_md.status == "completed"
    assert res_md.format == "markdown"
    assert "- Heart rate: 72 bpm" in res_md.text

    # CSV
    csv_content = b"Date,Test,Result\n2026-10-01,Hemoglobin,14.2\n2026-10-01,Platelets,250000\n"
    res_csv = extract_document_text(csv_content, filename="labs.csv")
    assert res_csv.status == "completed"
    assert res_csv.format == "csv"
    assert "Hemoglobin,14.2" in res_csv.text

    # TSV
    tsv_content = b"Medication\tDose\tFrequency\nLisinopril\t10mg\tOnce daily\n"
    res_tsv = extract_document_text(tsv_content, filename="meds.tsv")
    assert res_tsv.status == "completed"
    assert res_tsv.format == "tsv"
    assert "Lisinopril\t10mg" in res_tsv.text

    # YAML
    yaml_content = b"patient:\n  name: Jane Doe\n  condition: Hypertension\n"
    res_yaml = extract_document_text(yaml_content, filename="config.yaml")
    assert res_yaml.status == "completed"
    assert res_yaml.format == "yaml"
    assert "Hypertension" in res_yaml.text


def test_extract_json_metadata():
    """Verifies that JSON documents are parsed to capture keys or array lengths in metadata."""
    # Valid JSON object
    json_obj = json.dumps({"patient_id": "P-1234", "diagnosis": "Asthma", "severity": "Mild"}).encode("utf-8")
    res_obj = extract_document_text(json_obj, filename="record.json")
    assert res_obj.status == "completed"
    assert res_obj.format == "json"
    assert "diagnosis" in res_obj.metadata.get("json_keys", [])
    assert "Asthma" in res_obj.text

    # Valid JSON array
    json_arr = json.dumps([{"code": "I10"}, {"code": "E11.9"}]).encode("utf-8")
    res_arr = extract_document_text(json_arr, filename="codes.json")
    assert res_arr.status == "completed"
    assert res_arr.format == "json"
    assert res_arr.metadata.get("json_array_length") == 2

    # Malformed JSON
    bad_json = b"{patient_id: P-1234, incomplete"
    res_bad = extract_document_text(bad_json, filename="bad.json")
    assert res_bad.status == "completed"
    assert res_bad.metadata.get("json_valid") is False
    assert "incomplete" in res_bad.text


def test_extract_encoding_fallback():
    """Verifies non-UTF-8 bytes degrade cleanly with replace fallback instead of crashing."""
    latin1_bytes = "Dr. Müller - résumé of patient care".encode("latin1")
    res = extract_document_text(latin1_bytes, filename="notes_latin1.txt")
    assert res.status == "completed"
    assert res.format == "text"
    assert res.metadata.get("decode_fallback") is True or res.metadata.get("encoding") == "utf-8"


def test_extract_empty_content():
    """Verifies handling of empty files."""
    res_empty_txt = extract_document_text(b"", filename="empty.txt")
    assert res_empty_txt.status == "empty"
    assert res_empty_txt.text == ""

    res_empty_bin = extract_document_text(b"", filename="empty.bin")
    assert res_empty_bin.status == "failed"
    assert res_empty_bin.text == ""


# =========================================================================
# 2. PDF Extraction Tests (Dense, Sparse, Corrupt, Encrypted)
# =========================================================================

def test_extract_dense_pdf():
    """Verifies pypdf text extraction on dense clinical text (>30 chars/page)."""
    dense_note = (
        "Comprehensive clinical assessment: Patient exhibits steady vitals with normal cardiac "
        "rhythm. Prescribed lisinopril 10mg daily. Scheduled follow-up visit in six weeks."
    )
    pdf_bytes = _create_sample_pdf(dense_note)
    res = extract_document_text(pdf_bytes, filename="chart.pdf")

    assert res.status == "completed"
    assert res.format == "pdf"
    assert res.page_count == 1
    assert "Comprehensive clinical assessment" in res.text
    assert res.metadata.get("parser") == "pypdf"
    assert res.metadata.get("avg_chars", 0) > 30.0
    assert res.ocr_applied is False


def test_extract_sparse_pdf_flag():
    """Verifies that PDFs with sparse text (<30 chars/page) are flagged with sparse_text=True."""
    sparse_note = "Hi"
    pdf_bytes = _create_sample_pdf(sparse_note)
    res = extract_document_text(pdf_bytes, filename="sparse.pdf")

    assert res.status == "completed"
    assert res.format == "pdf"
    assert res.text == "Hi"
    assert res.metadata.get("sparse_text") is True
    assert res.metadata.get("avg_chars", 0) < 30.0


def test_extract_corrupted_pdf_stream_fallback():
    """Verifies that corrupted PDFs with invalid headers fall back safely to regex stream parsing."""
    corrupted_pdf = (
        b"%PDF-1.4\n"
        b"corrupted header and broken xref table\n"
        b"stream\n"
        b"BT\n"
        b"(Recovered Fallback Emergency Clinical Note) Tj\n"
        b"ET\n"
        b"endstream\n"
    )
    res = extract_document_text(corrupted_pdf, filename="corrupted.pdf")

    assert res.status == "completed"
    assert res.format == "pdf"
    assert "Recovered Fallback Emergency Clinical Note" in res.text
    assert res.metadata.get("parser") == "regex_stream"
    assert res.metadata.get("fallback_from_pypdf") is True


def test_extract_encrypted_pdf_graceful_handling():
    """Verifies encrypted/password-protected PDFs return a failed result without crashing."""
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("confidential_pass")
    bio = io.BytesIO()
    writer.write(bio)
    encrypted_bytes = bio.getvalue()

    res = extract_document_text(encrypted_bytes, filename="encrypted.pdf")
    assert res.status == "failed"
    assert res.format == "pdf"
    assert res.text == ""
    assert res.metadata.get("encrypted") is True
    assert "password-protected" in res.metadata.get("error", "").lower() or "encrypted" in res.metadata.get("error", "").lower()


# =========================================================================
# 3. Image OCR Tests & Graceful Degradation
# =========================================================================

def test_extract_image_degradation_without_ocr():
    """Verifies image extraction handles absence of OCR dependencies gracefully."""
    fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"

    with patch("carefold.storage.extract.is_ocr_available", return_value=False):
        res = extract_document_text(fake_png, filename="scan.png")
        assert res.status == "empty"
        assert res.format == "png"
        assert res.ocr_applied is False
        assert res.metadata.get("ocr_available") is False


def test_extract_image_with_mocked_ocr():
    """Verifies OCR execution path when OCR engine is available."""
    fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    mock_img = MagicMock()
    mock_img.format = "PNG"
    mock_img.size = (800, 600)
    mock_img.mode = "RGB"

    with patch("carefold.storage.extract.is_ocr_available", return_value=True), \
         patch("carefold.storage.extract.Image") as mock_pil, \
         patch("carefold.storage.extract.pytesseract") as mock_tess:
        mock_pil.open.return_value = mock_img
        mock_tess.image_to_string.return_value = "Blood Glucose: 95 mg/dL"

        res = extract_document_text(fake_png, filename="glucometer.png")
        assert res.status == "completed"
        assert res.format == "png"
        assert "Blood Glucose: 95 mg/dL" in res.text
        assert res.ocr_applied is True
        assert res.metadata.get("engine") == "pytesseract"


def test_extract_image_tesseract_not_found():
    """Verifies handling when pytesseract throws TesseractNotFoundError."""
    fake_jpg = b"\xff\xd8\xff\xe0\x00\x10JFIF"
    mock_img = MagicMock()
    mock_img.format = "JPEG"
    mock_img.size = (400, 400)
    mock_img.mode = "RGB"

    class MockTesseractNotFoundError(OSError):
        pass

    mock_tess = MagicMock()
    mock_tess.TesseractNotFoundError = MockTesseractNotFoundError
    mock_tess.image_to_string.side_effect = MockTesseractNotFoundError("Tesseract is not installed")

    with patch("carefold.storage.extract.is_ocr_available", return_value=True), \
         patch("carefold.storage.extract.Image") as mock_pil, \
         patch("carefold.storage.extract.pytesseract", mock_tess):
        mock_pil.open.return_value = mock_img

        res = extract_document_text(fake_jpg, filename="scan.jpg")
        assert res.status == "empty"
        assert res.format == "jpeg"
        assert "not found" in res.metadata.get("error", "").lower()


# =========================================================================
# 4. Unknown and Binary Format Tests
# =========================================================================

def test_extract_unknown_binary_rejection():
    """Verifies that non-text binary files containing null bytes are safely rejected."""
    binary_data = b"\x00\x01\x02\x03\x04\xff\xfe\x00\x00executable_or_dump"
    res = extract_document_text(binary_data, filename="unknown.dat")
    assert res.status == "failed"
    assert res.format == "binary"
    assert "Unsupported binary file format" in res.metadata.get("error", "")


def test_extract_unknown_text_extension_inferred():
    """Verifies that files with unknown extensions but clean UTF-8 text are inferred as text."""
    plain_text = b"Record identifier: 9982\nSummary: Patient in good health."
    res = extract_document_text(plain_text, filename="custom_export.xyz")
    assert res.status == "completed"
    assert res.format == "text"
    assert res.metadata.get("inferred_text") is True
    assert "Record identifier: 9982" in res.text


# =========================================================================
# 5. CAS Document Extraction Tests
# =========================================================================

def test_extract_cas_document_success_and_missing(tmp_path: Path):
    """Verifies reading documents from CAS storage and handling missing CAS files."""
    home_dir = tmp_path / "carefold_home"
    user_id = "user-extract-01"
    profile_id = "prof-extract-01"
    doc_content = b"Content-Addressed Storage clinical document test."

    _, sha256_hash, _ = store_cas_file(
        content=doc_content,
        carefold_home=home_dir,
        user_id=user_id,
        profile_id=profile_id,
    )

    # 1. Existing CAS file extraction
    res = extract_cas_document(
        carefold_home=home_dir,
        user_id=user_id,
        profile_id=profile_id,
        sha256_hash=sha256_hash,
        filename="cas_doc.txt",
    )
    assert res.status == "completed"
    assert "Content-Addressed Storage clinical document test" in res.text

    # 2. Missing CAS file extraction
    missing_hash = "0" * 64
    res_missing = extract_cas_document(
        carefold_home=home_dir,
        user_id=user_id,
        profile_id=profile_id,
        sha256_hash=missing_hash,
        filename="missing.txt",
    )
    assert res_missing.status == "failed"
    assert "not found" in res_missing.metadata.get("error", "").lower()


# =========================================================================
# 6. Background extract_text Job Lifecycle & Downstream Enqueuing Tests
# =========================================================================

@pytest.mark.asyncio
async def test_handle_extract_text_job_success_lifecycle(
    db_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
):
    """Verifies full extract_text lifecycle:
    pending -> extracting -> completed with extracted_text populated,
    and downstream index_doc job enqueued with idempotency key.
    """
    home_dir = tmp_path / "carefold_home"
    user_id = "user-extract-01"
    profile_id = "prof-extract-01"
    doc_bytes = b"Cardiology follow-up dossier. Blood pressure 118/76. Medication renewed."

    _, sha256_hash, _ = store_cas_file(
        content=doc_bytes,
        carefold_home=home_dir,
        user_id=user_id,
        profile_id=profile_id,
    )

    att_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    async with db_session_factory() as session:
        att = Attachment(
            id=att_id,
            user_id=user_id,
            profile_id=profile_id,
            filename="cardio_note.txt",
            original_name="cardio_note.txt",
            content_type="text/plain",
            size_bytes=len(doc_bytes),
            sha256_hash=sha256_hash,
            storage_key=f"{user_id}/{profile_id}/cardio_note.txt",
            extraction_status="pending",
        )
        session.add(att)
        await session.commit()

    # Create dummy job object
    job = DBJob(
        id=job_id,
        profile_id=profile_id,
        kind="extract_text",
        payload=json.dumps({"attachment_id": att_id, "user_id": user_id, "profile_id": profile_id}),
        timezone="UTC",
        next_run_at=datetime.now(timezone.utc),
        status="active",
    )

    # Execute extract_text job handler
    await handle_extract_text_job(
        job=job,
        session_factory=db_session_factory,
        carefold_home=home_dir,
    )

    # Verify Attachment is completed with extracted text
    async with db_session_factory() as session:
        res = await session.execute(select(Attachment).where(Attachment.id == att_id))
        updated_att = res.scalar_one()
        assert updated_att.extraction_status == "completed"
        assert "Cardiology follow-up dossier" in (updated_att.extracted_text or "")

        # Verify downstream index_doc job was enqueued
        expected_idempotency = f"index:attachment:{att_id}:{sha256_hash}"
        job_res = await session.execute(
            select(DBJob).where(DBJob.idempotency_key == expected_idempotency)
        )
        index_job = job_res.scalar_one_or_none()
        assert index_job is not None
        assert index_job.kind == "index_doc"
        assert index_job.profile_id == profile_id
        assert index_job.status == "pending"

        index_payload = json.loads(index_job.payload)
        assert index_payload["document_id"] == att_id
        assert index_payload["sha256"] == sha256_hash

    # Run again to verify idempotency (should not duplicate index_doc job)
    await handle_extract_text_job(
        job=job,
        session_factory=db_session_factory,
        carefold_home=home_dir,
    )

    async with db_session_factory() as session:
        job_res = await session.execute(
            select(DBJob).where(DBJob.idempotency_key == expected_idempotency)
        )
        matching_jobs = job_res.scalars().all()
        assert len(matching_jobs) == 1


@pytest.mark.asyncio
async def test_handle_extract_text_job_failure_state(
    db_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
):
    """Verifies that if extraction fails (missing CAS file), Attachment status is marked failed."""
    home_dir = tmp_path / "carefold_home"
    user_id = "user-extract-01"
    profile_id = "prof-extract-01"
    missing_hash = "f" * 64

    att_id = str(uuid.uuid4())
    async with db_session_factory() as session:
        att = Attachment(
            id=att_id,
            user_id=user_id,
            profile_id=profile_id,
            filename="missing_doc.txt",
            original_name="missing_doc.txt",
            content_type="text/plain",
            size_bytes=100,
            sha256_hash=missing_hash,
            storage_key=f"{user_id}/{profile_id}/missing_doc.txt",
            extraction_status="pending",
        )
        session.add(att)
        await session.commit()

    job = DBJob(
        id=str(uuid.uuid4()),
        profile_id=profile_id,
        kind="extract_text",
        payload=json.dumps({"attachment_id": att_id, "user_id": user_id, "profile_id": profile_id}),
        timezone="UTC",
        next_run_at=datetime.now(timezone.utc),
        status="active",
    )

    # Should raise RuntimeError because extraction failed
    with pytest.raises(RuntimeError) as exc_info:
        await handle_extract_text_job(
            job=job,
            session_factory=db_session_factory,
            carefold_home=home_dir,
        )
    assert "Text extraction failed" in str(exc_info.value)

    # Verify attachment extraction_status was transitioned to failed
    async with db_session_factory() as session:
        res = await session.execute(select(Attachment).where(Attachment.id == att_id))
        failed_att = res.scalar_one()
        assert failed_att.extraction_status == "failed"


def test_extract_text_decode_fallback_flag():
    """Verifies decode_fallback flag is specifically set to True for invalid UTF-8 bytes."""
    corrupted_bytes = b"Clinical observation: \x80\x81\xfe\xff invalid utf-8 sequences"
    res = extract_document_text(corrupted_bytes, filename="chart_corrupt.txt")
    assert res.status == "completed"
    assert res.metadata.get("decode_fallback") is True
    assert "Clinical observation:" in res.text


def test_extract_cas_attachment_alias(tmp_path: Path):
    """Verifies that extract_cas_attachment alias behaves identically to extract_cas_document."""
    from carefold.storage.extract import extract_cas_attachment
    home_dir = tmp_path / "carefold_home"
    user_id = "user-extract-01"
    profile_id = "prof-extract-01"
    doc_content = b"Alias verification document."

    _, sha256_hash, _ = store_cas_file(
        content=doc_content,
        carefold_home=home_dir,
        user_id=user_id,
        profile_id=profile_id,
    )

    res = extract_cas_attachment(
        carefold_home=home_dir,
        user_id=user_id,
        profile_id=profile_id,
        sha256_hash=sha256_hash,
        filename="alias.txt",
    )
    assert res.status == "completed"
    assert "Alias verification document" in res.text


@pytest.mark.asyncio
async def test_create_extract_text_handler_factory(
    db_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
):
    """Verifies create_extract_text_handler factory produces working bound coroutine."""
    from carefold.engine.job_runner import create_extract_text_handler

    home_dir = tmp_path / "carefold_home"
    user_id = "user-extract-01"
    profile_id = "prof-extract-01"
    doc_bytes = b"Factory created handler text."

    _, sha256_hash, _ = store_cas_file(
        content=doc_bytes,
        carefold_home=home_dir,
        user_id=user_id,
        profile_id=profile_id,
    )

    att_id = str(uuid.uuid4())
    async with db_session_factory() as session:
        att = Attachment(
            id=att_id,
            user_id=user_id,
            profile_id=profile_id,
            filename="factory_test.txt",
            original_name="factory_test.txt",
            content_type="text/plain",
            size_bytes=len(doc_bytes),
            sha256_hash=sha256_hash,
            storage_key=f"{user_id}/{profile_id}/factory_test.txt",
            extraction_status="pending",
        )
        session.add(att)
        await session.commit()

    handler = create_extract_text_handler(
        session_factory=db_session_factory,
        carefold_home=home_dir,
    )

    job = DBJob(
        id=str(uuid.uuid4()),
        profile_id=profile_id,
        kind="extract_text",
        payload=json.dumps({"attachment_id": att_id}),
        timezone="UTC",
        next_run_at=datetime.now(timezone.utc),
        status="active",
    )

    await handler(job)

    async with db_session_factory() as session:
        res = await session.execute(select(Attachment).where(Attachment.id == att_id))
        updated_att = res.scalar_one()
        assert updated_att.extraction_status == "completed"
        assert "Factory created handler text" in (updated_att.extracted_text or "")


@pytest.mark.asyncio
async def test_handle_extract_text_job_missing_attachment_in_db(
    db_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
):
    """Verifies that referencing a non-existent attachment raises ValueError."""
    non_existent_id = str(uuid.uuid4())
    job = DBJob(
        id=str(uuid.uuid4()),
        profile_id="prof-extract-01",
        kind="extract_text",
        payload=json.dumps({"attachment_id": non_existent_id}),
        timezone="UTC",
        next_run_at=datetime.now(timezone.utc),
        status="active",
    )

    with pytest.raises(ValueError) as exc:
        await handle_extract_text_job(
            job=job,
            session_factory=db_session_factory,
            carefold_home=tmp_path,
        )
    assert f"Attachment '{non_existent_id}' not found" in str(exc.value)


# =========================================================================
# 7. Adversarial Stress Tests (Empirical Challenge Suite)
# =========================================================================

def test_adversarial_malformed_truncated_pdf_streams():
    """Adversarially tests malformed and truncated PDF byte streams.

    Verifies fallback to regex stream parser and safe handling without crashes
    across corrupted headers, broken objects, circular structures, and truncation.
    """
    # 1. Header only with no body or EOF
    res_hdr = extract_document_text(b"%PDF-1.4\n", filename="header_only.pdf")
    assert res_hdr.status == "empty"
    assert res_hdr.format == "pdf"
    assert res_hdr.text == ""

    # 2. Corrupted PDF with BT...ET text stream outside object wrappers
    stream_no_obj = (
        b"%PDF-1.4\n"
        b"corrupted header and missing catalog\n"
        b"stream\n"
        b"BT\n"
        b"/F1 12 Tf\n"
        b"(Adversarial Stream Fallback Recovery) Tj\n"
        b"ET\n"
        b"endstream\n"
    )
    res_stream = extract_document_text(stream_no_obj, filename="unwrapped_stream.pdf")
    assert res_stream.status == "completed"
    assert res_stream.format == "pdf"
    assert "Adversarial Stream Fallback Recovery" in res_stream.text
    assert res_stream.metadata.get("parser") == "regex_stream"
    assert res_stream.metadata.get("fallback_from_pypdf") is True

    # 3. Hex-encoded strings inside PDF stream: <48656c6c6f> Tj -> "Hello"
    hex_stream = b"%PDF-1.4\nBT /F1 12 Tf <48656c6c6f20576f726c64> Tj ET\n"
    res_hex = extract_document_text(hex_stream, filename="hex.pdf")
    assert res_hex.status == "completed"
    assert "Hello World" in res_hex.text
    assert res_hex.metadata.get("fallback_from_pypdf") is True

    # 4. Array string TJ operations: [(Adversarial) 10 ( Array)] TJ
    array_stream = b"%PDF-1.4\nBT /F1 12 Tf [(Adversarial) 10 ( Array)] TJ ET\n"
    res_array = extract_document_text(array_stream, filename="array.pdf")
    assert res_array.status == "completed"
    assert "Adversarial Array" in res_array.text

    # 5. Unterminated BT block
    res_unterminated = extract_document_text(b"%PDF-1.4\nBT (Unterminated text", filename="unterminated.pdf")
    assert res_unterminated.status == "empty"
    assert res_unterminated.format == "pdf"

    # 6. Bad xref pointer and invalid trailer
    bad_xref = b"%PDF-1.4\ntrailer << /Size 1 /Root 1 0 R >> startxref 99999 %%EOF"
    res_bad_xref = extract_document_text(bad_xref, filename="bad_xref.pdf")
    assert res_bad_xref.status == "empty"
    assert res_bad_xref.format == "pdf"

    # 7. Incremental truncation attack across a valid PDF
    sample_pdf = _create_sample_pdf("Patient chart vital signs: BP 120/80 HR 72.")
    assert len(sample_pdf) > 100
    for trunc_len in range(5, len(sample_pdf), 15):
        truncated_bytes = sample_pdf[:trunc_len]
        res_trunc = extract_document_text(truncated_bytes, filename=f"trunc_{trunc_len}.pdf")
        assert res_trunc is not None
        assert res_trunc.status in ("completed", "empty", "failed")
        assert res_trunc.format == "pdf"


def test_adversarial_zero_byte_files_all_formats():
    """Adversarially verifies handling of zero-byte files across all supported formats."""
    # Text formats should return status="empty"
    text_extensions = [
        "empty.txt", "empty.md", "empty.json", "empty.csv",
        "empty.tsv", "empty.yaml", "empty.yml", "empty.html", "empty.xml",
    ]
    for filename in text_extensions:
        res = extract_document_text(b"", filename=filename)
        assert res.status == "empty", f"Expected empty status for {filename}, got {res.status}"
        assert res.text == ""
        assert res.page_count == 0
        assert res.metadata.get("reason") == "empty_content"
        assert res.metadata.get("byte_size") == 0

    # Binary and complex formats should return status="failed" with clear error
    binary_extensions = [
        "empty.pdf", "empty.png", "empty.jpg", "empty.jpeg",
        "empty.tiff", "empty.bmp", "empty.webp", "empty_unknown", "",
    ]
    for filename in binary_extensions:
        res = extract_document_text(b"", filename=filename)
        assert res.status == "failed", f"Expected failed status for {filename}, got {res.status}"
        assert res.text == ""
        assert res.page_count == 0
        assert res.metadata.get("error") == "Empty file content"
        assert res.metadata.get("byte_size") == 0


def test_adversarial_encrypted_password_protected_pdfs():
    """Adversarially tests password-protected and encrypted PDFs across algorithms."""
    import pypdf

    def _generate_encrypted_pdf(user_pwd: str, owner_pwd: str = "owner_key", algorithm: str = "AES-128") -> bytes:
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=200, height=200)
        bio = io.BytesIO()
        writer.encrypt(user_password=user_pwd, owner_password=owner_pwd, algorithm=algorithm)
        writer.write(bio)
        return bio.getvalue()

    # 1. AES-128 encrypted PDF
    enc_aes128 = _generate_encrypted_pdf("patient_secret_128", algorithm="AES-128")
    res_aes128 = extract_document_text(enc_aes128, filename="chart_aes128.pdf")
    assert res_aes128.status == "failed"
    assert res_aes128.format == "pdf"
    assert res_aes128.metadata.get("encrypted") is True
    assert "password-protected" in res_aes128.metadata.get("error", "").lower() or "encrypted" in res_aes128.metadata.get("error", "").lower()

    # 2. AES-256 encrypted PDF
    enc_aes256 = _generate_encrypted_pdf("patient_secret_256", algorithm="AES-256")
    res_aes256 = extract_document_text(enc_aes256, filename="chart_aes256.pdf")
    assert res_aes256.status == "failed"
    assert res_aes256.format == "pdf"
    assert res_aes256.metadata.get("encrypted") is True

    # 3. RC4-128 encrypted PDF
    enc_rc4 = _generate_encrypted_pdf("patient_secret_rc4", algorithm="RC4-128")
    res_rc4 = extract_document_text(enc_rc4, filename="chart_rc4.pdf")
    assert res_rc4.status == "failed"
    assert res_rc4.format == "pdf"
    assert res_rc4.metadata.get("encrypted") is True

    # 4. Encrypted PDF with empty user password (unlocked with "")
    unlocked_enc = _generate_encrypted_pdf("", owner_pwd="owner_only", algorithm="AES-128")
    res_unlocked = extract_document_text(unlocked_enc, filename="unlocked.pdf")
    assert res_unlocked.status in ("completed", "empty")
    assert res_unlocked.format == "pdf"
    assert res_unlocked.metadata.get("encrypted") is not True


def test_adversarial_high_entropy_binary_junk():
    """Adversarially passes high-entropy random binary junk across all format extensions."""
    import os
    junk = os.urandom(1024)

    # 1. Plain text and Markdown: decodes with replacement characters without crashing
    res_txt = extract_document_text(junk, filename="junk.txt")
    assert res_txt.status == "completed"
    assert res_txt.format == "text"
    assert res_txt.metadata.get("decode_fallback") is True
    assert len(res_txt.text) > 0

    res_md = extract_document_text(junk, filename="junk.md")
    assert res_md.status == "completed"
    assert res_md.format == "markdown"
    assert res_md.metadata.get("decode_fallback") is True

    # 2. JSON: decodes with replacement characters, flags invalid JSON
    res_json = extract_document_text(junk, filename="junk.json")
    assert res_json.status == "completed"
    assert res_json.format == "json"
    assert res_json.metadata.get("json_valid") is False

    # 3. PDF: rejected as invalid PDF stream without crash
    res_pdf = extract_document_text(junk, filename="junk.pdf")
    assert res_pdf.status == "failed"
    assert res_pdf.format == "pdf"
    assert res_pdf.metadata.get("error") == "Invalid or corrupt PDF stream"

    # 4. Images: handled safely without crash
    for img_name in ("junk.png", "junk.jpg", "junk.tiff"):
        res_img = extract_document_text(junk, filename=img_name)
        assert res_img is not None
        assert res_img.status in ("empty", "failed")
        assert res_img.text == ""

    # 5. CSV, TSV, YAML
    res_csv = extract_document_text(junk, filename="junk.csv")
    assert res_csv.status == "completed"
    res_tsv = extract_document_text(junk, filename="junk.tsv")
    assert res_tsv.status == "completed"
    res_yaml = extract_document_text(junk, filename="junk.yaml")
    assert res_yaml.status == "completed"


def test_adversarial_missing_ocr_environment_and_tesseract_errors():
    """Adversarially tests missing OCR environment and TesseractNotFoundError handling."""
    # 1. OCR completely unavailable (libraries missing)
    fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    with patch("carefold.storage.extract.is_ocr_available", return_value=False):
        res_no_ocr = extract_document_text(fake_png, filename="scan.png")
        assert res_no_ocr.status == "empty"
        assert res_no_ocr.format == "png"
        assert res_no_ocr.metadata.get("ocr_available") is False
        assert "not installed" in res_no_ocr.metadata.get("note", "").lower()

    # 2. OCR libraries present, but Tesseract binary missing (TesseractNotFoundError)
    class MockTesseractNotFoundError(OSError):
        pass

    mock_tess = MagicMock()
    mock_tess.TesseractNotFoundError = MockTesseractNotFoundError
    mock_tess.image_to_string.side_effect = MockTesseractNotFoundError("tesseract binary missing from PATH")

    mock_img = MagicMock()
    mock_img.format = "PNG"
    mock_img.size = (100, 100)
    mock_img.mode = "RGB"

    mock_pil = MagicMock()
    mock_pil.open.return_value = mock_img

    with patch("carefold.storage.extract.is_ocr_available", return_value=True), \
         patch("carefold.storage.extract.Image", mock_pil), \
         patch("carefold.storage.extract.pytesseract", mock_tess):
        res_tess_err = extract_document_text(fake_png, filename="scan.png")
        assert res_tess_err.status == "empty"
        assert res_tess_err.format == "png"
        assert res_tess_err.metadata.get("ocr_available") is False
        assert "not found" in res_tess_err.metadata.get("error", "").lower()

    # 3. Sparse PDF with OCR raising TesseractNotFoundError
    sparse_pdf = _create_sample_pdf("Cardio note")
    with patch("carefold.storage.extract.is_ocr_available", return_value=True), \
         patch("carefold.storage.extract.Image", mock_pil), \
         patch("carefold.storage.extract.pytesseract", mock_tess):
        res_sparse = extract_document_text(sparse_pdf, filename="sparse_report.pdf")
        assert res_sparse.status == "completed"
        assert res_sparse.format == "pdf"
        assert res_sparse.text == "Cardio note"
        assert res_sparse.metadata.get("sparse_text") is True
        assert res_sparse.ocr_applied is False


def test_adversarial_cas_path_traversal_and_partition_escapes(tmp_path: Path):
    """Adversarially tests path traversal and partition escape attempts through extract_cas_document."""
    home_dir = tmp_path / "cas_test_home"
    valid_sha = "e" * 64

    traversal_attacks = [
        # user_id traversal attacks
        {"user_id": "../../etc", "profile_id": "prof1", "sha256": valid_sha, "desc": "user_id double-dot slash"},
        {"user_id": "../../../", "profile_id": "prof1", "sha256": valid_sha, "desc": "user_id triple-dot slash"},
        {"user_id": "/etc", "profile_id": "prof1", "sha256": valid_sha, "desc": "user_id absolute path"},
        {"user_id": "user\\..\\escape", "profile_id": "prof1", "sha256": valid_sha, "desc": "user_id backslash traversal"},
        {"user_id": "user\0null", "profile_id": "prof1", "sha256": valid_sha, "desc": "user_id null byte"},
        {"user_id": "..", "profile_id": "prof1", "sha256": valid_sha, "desc": "user_id dot dot"},
        # profile_id traversal attacks
        {"user_id": "user1", "profile_id": "../../etc", "sha256": valid_sha, "desc": "profile_id double-dot slash"},
        {"user_id": "user1", "profile_id": "../../../etc/passwd", "sha256": valid_sha, "desc": "profile_id deep traversal"},
        {"user_id": "user1", "profile_id": "/var/run", "sha256": valid_sha, "desc": "profile_id absolute path"},
        {"user_id": "user1", "profile_id": "prof\0null", "sha256": valid_sha, "desc": "profile_id null byte"},
        {"user_id": "user1", "profile_id": "..", "sha256": valid_sha, "desc": "profile_id dot dot"},
        # sha256_hash traversal and malformed attacks
        {"user_id": "user1", "profile_id": "prof1", "sha256": "../../../etc/passwd", "desc": "sha256 traversal path"},
        {"user_id": "user1", "profile_id": "prof1", "sha256": valid_sha + "/../escaped", "desc": "sha256 append slash"},
        {"user_id": "user1", "profile_id": "prof1", "sha256": "g" * 64, "desc": "sha256 non-hex characters"},
        {"user_id": "user1", "profile_id": "prof1", "sha256": "0" * 63, "desc": "sha256 63 chars (too short)"},
        {"user_id": "user1", "profile_id": "prof1", "sha256": "0" * 65, "desc": "sha256 65 chars (too long)"},
        {"user_id": "user1", "profile_id": "prof1", "sha256": "", "desc": "sha256 empty string"},
        {"user_id": "user1", "profile_id": "prof1", "sha256": "0" * 64 + "\0", "desc": "sha256 null byte injection"},
    ]

    for attack in traversal_attacks:
        res = extract_cas_document(
            carefold_home=home_dir,
            user_id=attack["user_id"],
            profile_id=attack["profile_id"],
            sha256_hash=attack["sha256"],
            filename="document.txt",
        )
        assert res.status == "failed", f"Attack '{attack['desc']}' did not fail: {res.status}"
        assert res.text == "", f"Attack '{attack['desc']}' returned non-empty text"
        assert res.page_count == 0
        error_msg = res.metadata.get("error", "").lower()
        assert "cas read error" in error_msg or "invalid" in error_msg, f"Attack '{attack['desc']}' missing expected error: {res.metadata}"


