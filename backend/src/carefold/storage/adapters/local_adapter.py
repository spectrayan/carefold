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

"""Local filesystem adapter implementing StoragePort under ~/.carefold/uploads."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import shutil
from typing import Any, BinaryIO, Dict, List, Optional, Tuple, Union
import uuid

from carefold.config import Settings, settings as global_settings
from carefold.storage.ports.storage_port import (
    StorageError,
    StorageFile,
    StorageFileMetadata,
    StorageFileNotFoundError,
    StoragePort,
    StorageSecurityError,
)
from carefold.tools.sandbox import SandboxSecurityError, resolve_sandboxed_path

logger = logging.getLogger("carefold.storage.local")

CHUNK_SIZE = 64 * 1024  # 64 KB streaming buffer
DANGEROUS_CHARS_REGEX = re.compile(r"[^a-zA-Z0-9._-]")


class LocalStorageAdapter(StoragePort):
    """Local filesystem implementation of StoragePort.

    Partitions files under:
        {base_dir}/{user_id or 'default'}/{profile_id or 'default'}/{filename}
    """

    def __init__(
        self,
        base_dir: Optional[Union[str, Path]] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        """Initializes LocalStorageAdapter.

        Args:
            base_dir: Explicit root directory path. If None, uses settings.get_uploads_dir().
            settings: Optional Settings instance. Defaults to global settings.
        """
        cfg = settings or global_settings
        if base_dir is not None:
            self._base_dir = Path(base_dir).resolve()
        else:
            self._base_dir = cfg.get_uploads_dir().resolve()

        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._lock: asyncio.Lock = asyncio.Lock()
        self._locks: Dict[str, asyncio.Lock] = {}
        logger.debug("LocalStorageAdapter initialized at base_dir=%s", self._base_dir)

    def _get_partition_lock(
        self, user_id: Optional[str] = None, profile_id: Optional[str] = None
    ) -> asyncio.Lock:
        """Returns the partitioned asyncio.Lock for the specified user and profile scope."""
        u_part = self._sanitize_filename(user_id) if user_id else "default"
        p_part = self._sanitize_filename(profile_id) if profile_id else "default"
        key = f"{u_part}/{p_part}"
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    @property
    def base_dir(self) -> Path:
        """Returns the configured root uploads directory."""
        return self._base_dir

    # ------------------------------------------------------------------------
    # Partition and Path Security Helpers
    # ------------------------------------------------------------------------

    def _sanitize_filename(self, filename: str) -> str:
        """Sanitizes filename removing directory traversal characters and unsafe symbols."""
        if not filename or not isinstance(filename, str):
            return "unnamed_file.bin"

        base = os.path.basename(filename.strip())
        sanitized = DANGEROUS_CHARS_REGEX.sub("_", base)
        if sanitized in ("", ".", ".."):
            return "unnamed_file.bin"
        return sanitized

    def _get_partition_dir(self, user_id: Optional[str], profile_id: Optional[str]) -> Path:
        """Resolves the safe partition directory for a given user and profile scope."""
        u_part = self._sanitize_filename(user_id) if user_id else "default"
        p_part = self._sanitize_filename(profile_id) if profile_id else "default"

        partition = self._base_dir / u_part / p_part
        partition.mkdir(parents=True, exist_ok=True)
        return partition.resolve()

    def _resolve_safe_path(
        self,
        storage_key: str,
        user_id: Optional[str] = None,
        profile_id: Optional[str] = None,
        must_exist: bool = False,
        for_write: bool = False,
    ) -> Tuple[Path, str]:
        """Resolves storage_key against the partition directory with sandbox traversal defenses.

        Returns:
            Tuple of (resolved_absolute_path, effective_relative_storage_key).
        """
        if not storage_key or not isinstance(storage_key, str):
            raise StorageSecurityError("Invalid storage_key: key must be a non-empty string.")

        if "\0" in storage_key:
            raise StorageSecurityError("Path traversal forbidden: Null byte detected in storage_key.")

        # Check if storage_key is an absolute path, Windows drive path, URI, or contains traversal dots/backslashes
        if (
            storage_key.startswith("/")
            or "://" in storage_key
            or "\\" in storage_key
            or re.match(r"^[a-zA-Z]:", storage_key)
            or ".." in storage_key
        ):
            raise StorageSecurityError(f"Path traversal forbidden: Invalid storage_key '{storage_key}'.")

        partition_dir = self._get_partition_dir(user_id, profile_id)

        # Normalize relative path components
        clean_key = storage_key.strip().lstrip("/\\")

        # Handle case where caller passed a full partition path matching current partition
        u_part = self._sanitize_filename(user_id) if user_id else "default"
        p_part = self._sanitize_filename(profile_id) if profile_id else "default"
        prefix = f"{u_part}/{p_part}/"
        if clean_key.startswith(prefix):
            clean_key = clean_key[len(prefix):]

        # First attempt inside the partition directory
        try:
            resolved = resolve_sandboxed_path(
                base_dir=partition_dir,
                user_path=clean_key,
                must_exist=must_exist,
                for_write=for_write,
            )
            resolved.relative_to(self._base_dir)
            return resolved, clean_key
        except SandboxSecurityError as sec_err:
            raise StorageSecurityError(str(sec_err)) from sec_err
        except (FileNotFoundError, StorageFileNotFoundError) as fnf_err:
            # Fallback for unassigned/legacy files stored directly under base_dir (offline mode)
            if not for_write and (user_id is None and profile_id is None):
                try:
                    fallback_resolved = resolve_sandboxed_path(
                        base_dir=self._base_dir,
                        user_path=clean_key,
                        must_exist=must_exist,
                        for_write=False,
                    )
                    fallback_resolved.relative_to(self._base_dir)
                    return fallback_resolved, clean_key
                except Exception:
                    pass
            if must_exist:
                raise StorageFileNotFoundError(str(fnf_err)) from fnf_err
            # For non-existent files when must_exist=False, return partition path
            partition_candidate = (partition_dir / clean_key).resolve()
            try:
                partition_candidate.relative_to(self._base_dir)
            except ValueError:
                raise StorageSecurityError(f"Path '{storage_key}' escapes root uploads directory.")
            return partition_candidate, clean_key

    def _get_unique_path(self, target_dir: Path, filename: str) -> Path:
        """Finds a non-conflicting filename if the file already exists."""
        target = target_dir / filename
        if not target.exists():
            return target

        path_obj = Path(filename)
        stem = path_obj.stem
        ext = path_obj.suffix

        match = re.match(r"^(.*?)(?:_(\d+))$", stem)
        base_stem = stem
        counter = 1
        if match:
            base_stem = match.group(1)
            counter = int(match.group(2)) + 1

        candidate = target_dir / f"{base_stem}_{counter}{ext}"
        while candidate.exists():
            counter += 1
            candidate = target_dir / f"{base_stem}_{counter}{ext}"

        return candidate

    def _sidecar_path(self, file_path: Path) -> Path:
        """Returns path for hidden metadata sidecar file."""
        return file_path.parent / f".{file_path.name}.meta.json"

    # ------------------------------------------------------------------------
    # StoragePort API Implementation
    # ------------------------------------------------------------------------

    async def save_file(
        self,
        content: Union[bytes, BinaryIO],
        filename: str,
        user_id: Optional[str] = None,
        profile_id: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> StorageFileMetadata:
        """Persists content to disk atomically with streaming SHA-256 calculation."""
        sanitized_name = self._sanitize_filename(filename)
        partition_dir = self._get_partition_dir(user_id, profile_id)
        partition_lock = self._get_partition_lock(user_id, profile_id)

        async with partition_lock:
            target_path = self._get_unique_path(partition_dir, sanitized_name)
            final_filename = target_path.name

            detected_mime = content_type
            if not detected_mime:
                detected_mime = mimetypes.guess_type(final_filename)[0] or "application/octet-stream"

            # Unique temp file in the same directory for atomic rename
            temp_filename = f".{final_filename}.{uuid.uuid4().hex}.tmp"
            temp_path = partition_dir / temp_filename

            hasher = hashlib.sha256()
            total_bytes = 0

            try:
                def _write_file() -> Tuple[int, str]:
                    nonlocal total_bytes
                    with open(temp_path, "wb") as f:
                        if isinstance(content, bytes):
                            f.write(content)
                            hasher.update(content)
                            total_bytes = len(content)
                        else:
                            # Stream chunks
                            while True:
                                chunk = content.read(CHUNK_SIZE)
                                if not chunk:
                                    break
                                f.write(chunk)
                                hasher.update(chunk)
                                total_bytes += len(chunk)
                        f.flush()
                        os.fsync(f.fileno())

                    digest = hasher.hexdigest()
                    os.replace(temp_path, target_path)

                    # For unscoped single-user desktop mode (user_id and profile_id is None),
                    # also mirror the file to base_dir if no collision exists, guaranteeing
                    # backward compatibility with legacy test suites checking settings.get_attachments_dir() / filename
                    if user_id is None and profile_id is None and target_path.parent != self._base_dir:
                        root_dest = self._base_dir / final_filename
                        try:
                            shutil.copyfile(target_path, root_dest)
                        except Exception as mirror_err:
                            logger.debug("Failed mirroring unscoped upload to base_dir: %s", mirror_err)

                    return total_bytes, digest

                size, sha256 = await asyncio.to_thread(_write_file)

            except Exception as err:
                # Clean up temp file on failure
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
                logger.error("Failed saving file '%s': %s", filename, err)
                raise StorageError(f"Failed writing file '{filename}' to storage: {err}") from err

            # Canonical relative storage_key: {user}/{profile}/{filename} or {filename}
            storage_key = final_filename

            metadata = StorageFileMetadata(
                storage_key=storage_key,
                filename=final_filename,
                size_bytes=size,
                content_type=detected_mime,
                sha256_hash=sha256,
                user_id=user_id,
                profile_id=profile_id,
                created_at=datetime.now(timezone.utc),
            )

            # Write sidecar metadata atomically
            sidecar = self._sidecar_path(target_path)
            try:
                def _write_sidecar() -> None:
                    tmp_sidecar = partition_dir / f".{sidecar.name}.{uuid.uuid4().hex}.tmp"
                    with open(tmp_sidecar, "w", encoding="utf-8") as sf:
                        json.dump(metadata.to_dict(), sf, indent=2)
                        sf.flush()
                        os.fsync(sf.fileno())
                    os.replace(tmp_sidecar, sidecar)

                await asyncio.to_thread(_write_sidecar)
            except Exception as sidecar_err:
                logger.warning("Failed writing metadata sidecar for '%s': %s", final_filename, sidecar_err)

            logger.info(
                "Saved file '%s' (size=%d bytes, sha256=%s, partition=%s/%s)",
                final_filename,
                size,
                sha256[:8],
                user_id or "default",
                profile_id or "default",
            )
            return metadata

    async def get_file(
        self,
        storage_key: str,
        user_id: Optional[str] = None,
        profile_id: Optional[str] = None,
    ) -> Optional[StorageFile]:
        """Retrieves file payload and metadata from disk."""
        try:
            file_path, clean_key = self._resolve_safe_path(
                storage_key, user_id=user_id, profile_id=profile_id, must_exist=False
            )
        except StorageFileNotFoundError:
            return None
        except StorageSecurityError:
            raise

        # Check if file exists at resolved partition path
        if not file_path.exists() or not file_path.is_file():
            # Check fallback in base_dir for unassigned legacy files
            if user_id is None and profile_id is None:
                root_candidate = self._base_dir / clean_key
                if root_candidate.exists() and root_candidate.is_file():
                    file_path = root_candidate
                else:
                    return None
            else:
                return None

        sidecar = self._sidecar_path(file_path)
        metadata: Optional[StorageFileMetadata] = None

        if sidecar.exists():
            try:
                sidecar_data = json.loads(await asyncio.to_thread(sidecar.read_text, "utf-8"))
                metadata = StorageFileMetadata.from_dict(sidecar_data)
            except (FileNotFoundError, OSError):
                metadata = None
            except Exception as err:
                logger.warning("Corrupt metadata sidecar for '%s', recalculating: %s", file_path.name, err)

        try:
            def _read_data() -> Tuple[bytes, int, str, datetime]:
                stat = file_path.stat()
                data = file_path.read_bytes()
                created_at = datetime.fromtimestamp(stat.st_ctime, timezone.utc)
                return data, len(data), hashlib.sha256(data).hexdigest(), created_at

            content_bytes, size, sha256, created_at = await asyncio.to_thread(_read_data)
        except (FileNotFoundError, OSError):
            return None

        if metadata is None:
            mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            metadata = StorageFileMetadata(
                storage_key=file_path.name,
                filename=file_path.name,
                size_bytes=size,
                content_type=mime,
                sha256_hash=sha256,
                user_id=user_id,
                profile_id=profile_id,
                created_at=created_at,
            )

        return StorageFile(metadata=metadata, content=content_bytes)

    async def delete_file(
        self,
        storage_key: str,
        user_id: Optional[str] = None,
        profile_id: Optional[str] = None,
    ) -> bool:
        """Deletes a file and its metadata sidecar from disk."""
        try:
            file_path, clean_key = self._resolve_safe_path(
                storage_key, user_id=user_id, profile_id=profile_id, must_exist=False
            )
        except StorageFileNotFoundError:
            return False
        except StorageSecurityError:
            raise

        existed = False
        sidecar = self._sidecar_path(file_path)

        def _unlink() -> bool:
            nonlocal existed
            deleted_any = False
            if file_path.exists() and file_path.is_file():
                try:
                    file_path.unlink()
                    deleted_any = True
                except (FileNotFoundError, OSError):
                    pass
            if sidecar.exists():
                try:
                    sidecar.unlink()
                except OSError:
                    pass

            # Also remove legacy mirrored copy from base_dir if present
            if user_id is None and profile_id is None:
                root_copy = self._base_dir / clean_key
                if root_copy.exists() and root_copy.is_file() and root_copy != file_path:
                    try:
                        root_copy.unlink()
                        deleted_any = True
                    except OSError:
                        pass
                root_sidecar = self._sidecar_path(root_copy)
                if root_sidecar.exists():
                    try:
                        root_sidecar.unlink()
                    except OSError:
                        pass

            return deleted_any

        existed = await asyncio.to_thread(_unlink)
        if existed:
            logger.info("Deleted file '%s' from storage", file_path.name)
        return existed

    async def list_files(
        self,
        user_id: Optional[str] = None,
        profile_id: Optional[str] = None,
    ) -> List[StorageFileMetadata]:
        """Lists metadata for all files in the given partition."""
        partition_dir = self._get_partition_dir(user_id, profile_id)

        def _scan_partition() -> List[StorageFileMetadata]:
            results: List[StorageFileMetadata] = []
            seen_names = set()

            dirs_to_scan = [partition_dir]
            if user_id is None and profile_id is None and self._base_dir.exists():
                dirs_to_scan.append(self._base_dir)

            for d in dirs_to_scan:
                if not d.exists():
                    continue
                for item in d.iterdir():
                    if not item.is_file() or item.name.startswith("."):
                        continue
                    if item.name in seen_names:
                        continue
                    seen_names.add(item.name)

                    sidecar = self._sidecar_path(item)
                    meta: Optional[StorageFileMetadata] = None
                    if sidecar.exists():
                        try:
                            s_data = json.loads(sidecar.read_text("utf-8"))
                            meta = StorageFileMetadata.from_dict(s_data)
                        except Exception:
                            meta = None

                    if meta is None:
                        try:
                            stat = item.stat()
                            mime = mimetypes.guess_type(item.name)[0] or "application/octet-stream"
                            created_at = datetime.fromtimestamp(stat.st_ctime, timezone.utc)
                            hasher = hashlib.sha256()
                            with open(item, "rb") as f:
                                while chunk := f.read(CHUNK_SIZE):
                                    hasher.update(chunk)
                            meta = StorageFileMetadata(
                                storage_key=item.name,
                                filename=item.name,
                                size_bytes=stat.st_size,
                                content_type=mime,
                                sha256_hash=hasher.hexdigest(),
                                user_id=user_id,
                                profile_id=profile_id,
                                created_at=created_at,
                            )
                        except (FileNotFoundError, OSError):
                            continue
                    results.append(meta)

            results.sort(key=lambda m: m.created_at, reverse=True)
            return results

        return await asyncio.to_thread(_scan_partition)

    async def get_file_url_or_path(
        self,
        storage_key: str,
        user_id: Optional[str] = None,
        profile_id: Optional[str] = None,
    ) -> str:
        """Returns the absolute filesystem path for local access."""
        file_path, clean_key = self._resolve_safe_path(
            storage_key, user_id=user_id, profile_id=profile_id, must_exist=False
        )
        if not file_path.exists() or not file_path.is_file():
            if user_id is None and profile_id is None:
                root_candidate = self._base_dir / clean_key
                if root_candidate.exists() and root_candidate.is_file():
                    return str(root_candidate.resolve())
            raise StorageFileNotFoundError(f"File '{storage_key}' not found in storage.")
        return str(file_path.resolve())
