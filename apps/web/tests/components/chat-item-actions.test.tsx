/*
 * Carefold — Healthcare AI Agent Marketplace & Runtime
 * Copyright 2026 Spectrayan
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import React from 'react';
import { ChatMessageItem, type ChatMessage } from '@/components/ChatMessageItem';

describe('ChatMessageItem Hover Action Toolbar', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('copies user message text to clipboard and displays checkmark visual feedback for 2000ms', async () => {
    const writeTextSpy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined);

    const userMessage: ChatMessage = {
      id: 'msg-u1',
      role: 'user',
      content: 'Can you summarize my visit checklist?'
    };

    render(<ChatMessageItem message={userMessage} />);

    const copyBtn = screen.getByTestId('message-copy-btn');
    expect(copyBtn).toBeInTheDocument();

    // Click copy
    await act(async () => {
      fireEvent.click(copyBtn);
    });

    expect(writeTextSpy).toHaveBeenCalledWith('Can you summarize my visit checklist?');

    // Visual feedback checkmark is rendered
    expect(screen.getByTestId('message-copy-success')).toBeInTheDocument();

    // Fast-forward 2000ms
    act(() => {
      vi.advanceTimersByTime(2000);
    });

    // Checkmark reverts back
    expect(screen.queryByTestId('message-copy-success')).not.toBeInTheDocument();
  });

  it('invokes onRerun with message content when user message rerun button is clicked', () => {
    const handleRerun = vi.fn();
    const userMessage: ChatMessage = {
      id: 'msg-u2',
      role: 'user',
      content: 'Explain my deductible in simple terms.'
    };

    render(<ChatMessageItem message={userMessage} onRerun={handleRerun} />);

    const rerunBtn = screen.getByTestId('message-rerun-btn');
    expect(rerunBtn).toHaveAttribute('title', 'Rerun prompt');

    fireEvent.click(rerunBtn);
    expect(handleRerun).toHaveBeenCalledTimes(1);
    expect(handleRerun).toHaveBeenCalledWith('Explain my deductible in simple terms.');
  });

  it('invokes onRegenerate with message id when assistant message regenerate button is clicked', () => {
    const handleRegenerate = vi.fn();
    const assistantMessage: ChatMessage = {
      id: 'msg-a1',
      role: 'assistant',
      content: 'Here is an explanation of your insurance deductible...'
    };

    render(<ChatMessageItem message={assistantMessage} onRegenerate={handleRegenerate} />);

    const regenerateBtn = screen.getByTestId('message-rerun-btn');
    expect(regenerateBtn).toHaveAttribute('title', 'Regenerate response');

    fireEvent.click(regenerateBtn);
    expect(handleRegenerate).toHaveBeenCalledTimes(1);
    expect(handleRegenerate).toHaveBeenCalledWith('msg-a1');
  });

  it('handles clipboard write rejection gracefully without throwing unhandled exceptions', async () => {
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('Permission denied'));

    const message: ChatMessage = {
      id: 'msg-u3',
      role: 'user',
      content: 'Test content'
    };

    render(<ChatMessageItem message={message} />);
    const copyBtn = screen.getByTestId('message-copy-btn');

    await act(async () => {
      fireEvent.click(copyBtn);
    });

    // Should not crash and should not display false positive success
    expect(screen.queryByTestId('message-copy-success')).not.toBeInTheDocument();
  });
});
