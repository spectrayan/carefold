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

"""Unit tests for Attachment declarative model, storage_key, sha256_hash, and backward-compatible aliases."""

from __future__ import annotations

from pathlib import Path
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from carefold.db.models import Attachment, Profile, User
from carefold.db.session import create_db_engine, get_session_factory, init_db


@pytest.fixture
async def db_session(tmp_path: Path):
    """Provides an isolated async database session with initialized schemas."""
    db_file = tmp_path / "attachment_models_test.db"
    url = f"sqlite+aiosqlite:///{db_file.resolve()}"
    engine = create_db_engine(url)
    await init_db(engine)

    factory = get_session_factory(engine)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_attachment_model_instantiation_and_persistence(db_session: AsyncSession):
    """Verifies that storage_key and sha256_hash persist and query accurately in SQLite."""
    sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    key = "u123/p456/lab_report.pdf"

    attachment = Attachment(
        filename="lab_report.pdf",
        original_name="Lab Report 2026.pdf",
        content_type="application/pdf",
        size_bytes=1048576,
        storage_key=key,
        sha256_hash=sha,
    )
    db_session.add(attachment)
    await db_session.commit()
    await db_session.refresh(attachment)

    assert attachment.id is not None
    assert attachment.storage_key == key
    assert attachment.sha256_hash == sha
    assert attachment.filename == "lab_report.pdf"
    assert attachment.size_bytes == 1048576
    assert attachment.content_type == "application/pdf"

    # Query by storage_key (verifying index usability)
    stmt = select(Attachment).where(Attachment.storage_key == key)
    res = await db_session.execute(stmt)
    fetched = res.scalar_one_or_none()
    assert fetched is not None
    assert fetched.id == attachment.id
    assert fetched.sha256_hash == sha


@pytest.mark.asyncio
async def test_attachment_backward_compatibility_properties_and_setters(db_session: AsyncSession):
    """Verifies that legacy property aliases (file_name, file_size, file_path, mime_type, byte_size) function properly."""
    attachment = Attachment(
        filename="ecg_chart.png",
        original_name="ecg_chart.png",
        content_type="image/png",
        size_bytes=512000,
        storage_key="u1/p1/ecg_chart.png",
    )
    db_session.add(attachment)
    await db_session.commit()

    # Getters
    assert attachment.file_name == "ecg_chart.png"
    assert attachment.file_size == 512000
    assert attachment.byte_size == 512000
    assert attachment.mime_type == "image/png"
    assert attachment.file_path == "u1/p1/ecg_chart.png"

    # Setters
    attachment.file_name = "ecg_updated.png"
    attachment.file_size = 600000
    attachment.mime_type = "image/webp"
    attachment.file_path = "u1/p1/ecg_updated.png"
    await db_session.commit()

    refetched = await db_session.get(Attachment, attachment.id)
    assert refetched.filename == "ecg_updated.png"
    assert refetched.size_bytes == 600000
    assert refetched.content_type == "image/webp"
    assert refetched.storage_key == "u1/p1/ecg_updated.png"


def test_attachment_constructor_legacy_kwargs():
    """Verifies that Attachment constructor safely normalizes legacy keyword arguments."""
    att = Attachment(
        file_name="legacy_doc.txt",
        file_size=2048,
        mime_type="text/plain",
        file_path="uploads/legacy_doc.txt",
        original_name="legacy_doc.txt",
    )
    assert att.filename == "legacy_doc.txt"
    assert att.size_bytes == 2048
    assert att.content_type == "text/plain"
    assert att.storage_key == "uploads/legacy_doc.txt"


def test_attachment_get_storage_key_fallback_scenarios():
    """Verifies dynamic synthesis of storage_key when storage_key is None."""
    # 1. Full scoping
    att1 = Attachment(filename="f1.pdf", user_id="u1", profile_id="p1", original_name="f1.pdf")
    assert att1.get_storage_key() == "u1/p1/f1.pdf"
    assert att1.file_path == "u1/p1/f1.pdf"

    # 2. User only
    att2 = Attachment(filename="f2.pdf", user_id="u1", original_name="f2.pdf")
    assert att2.get_storage_key() == "u1/f2.pdf"

    # 3. Profile only
    att3 = Attachment(filename="f3.pdf", profile_id="p1", original_name="f3.pdf")
    assert att3.get_storage_key() == "p1/f3.pdf"

    # 4. Offline / Root
    att4 = Attachment(filename="f4.pdf", original_name="f4.pdf")
    assert att4.get_storage_key() == "f4.pdf"
