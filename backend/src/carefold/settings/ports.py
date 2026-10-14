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

"""Hexagonal Port Interface for Runtime System Configuration and Settings."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

SECRET_MASK: str = "••••••••"


class SettingsPort(ABC):
    """Hexagonal Port Interface for System Configuration and Secrets Management."""

    @abstractmethod
    async def get_setting(self, key: str, default: Optional[Any] = None) -> Any:
        """Retrieves and deserializes configuration value for key.

        Args:
            key: Configuration key identifier (e.g. 'auth.provider', 'models.default_provider').
            default: Default value returned if the setting key is not set.

        Returns:
            Deserialized Python value (str, int, bool, dict, list) or default.
        """
        ...

    @abstractmethod
    async def set_setting(
        self,
        key: str,
        value: Any,
        is_secret: Optional[bool] = None,
        updated_by: Optional[str] = None,
    ) -> None:
        """Serializes and persists configuration value in storage.

        Args:
            key: Configuration key identifier.
            value: JSON-serializable value.
            is_secret: Whether this value is sensitive (e.g. API keys) and should be masked on export.
                If None and updating an existing setting, preserves the existing is_secret flag.
            updated_by: Optional identifier of the user or system component making the modification.
        """
        ...

    @abstractmethod
    async def get_all_settings(
        self,
        mask_secrets: bool = True,
        include_secrets: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Returns all configuration key-value pairs.

        Args:
            mask_secrets: If True, secret values are replaced with '••••••••'.
            include_secrets: If provided, inverts mask_secrets (include_secrets=True -> mask_secrets=False).

        Returns:
            Dictionary mapping configuration keys to their deserialized values.
        """
        ...

    @abstractmethod
    async def delete_setting(self, key: str) -> bool:
        """Removes a configuration setting from storage.

        Args:
            key: Configuration key identifier.

        Returns:
            True if setting existed and was removed, False otherwise.
        """
        ...
