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

"""Carefold test fixtures package.

Houses test doubles, fake chat models, and mock client implementations:
- FakeListChatModel: Deterministic sequential response generation.
- FakeChatModel: Configurable mock chat model.
- MockChatModel: LangChain ChatModel implementation of Carefold rule-based mock.
- MockModelClient: Legacy ModelClient implementation for streaming tests.
"""

from tests.fixtures.fake_model import (
    FakeChatModel,
    FakeListChatModel,
    MockChatModel,
    MockModelClient,
    extract_text_from_content,
)

__all__ = [
    "FakeChatModel",
    "FakeListChatModel",
    "MockChatModel",
    "MockModelClient",
    "extract_text_from_content",
]
