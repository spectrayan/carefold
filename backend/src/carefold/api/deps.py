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

"""FastAPI dependency providers for Carefold runtime."""

from __future__ import annotations

from carefold.memory.factory import get_memory_port
from carefold.memory.ports.memory_port import MemoryPort


def get_current_memory_port() -> MemoryPort:
    """Dependency provider resolving the active MemoryPort adapter singleton.

    Can be overridden in tests via app.dependency_overrides[get_current_memory_port].
    """
    return get_memory_port()


__all__ = ["get_current_memory_port"]
