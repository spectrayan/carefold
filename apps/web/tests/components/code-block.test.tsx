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
import { CodeBlock, normalizeLanguage, tokenizeCode, getTokenClassName } from '@/components/chat/CodeBlock';
import { ChatMessageItem, type ChatMessage } from '@/components/ChatMessageItem';

describe('CodeBlock Component & Markdown Code Rendering', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('normalizes various language aliases cleanly', () => {
    expect(normalizeLanguage('py')).toBe('python');
    expect(normalizeLanguage('python3')).toBe('python');
    expect(normalizeLanguage('js')).toBe('javascript');
    expect(normalizeLanguage('ts')).toBe('typescript');
    expect(normalizeLanguage('sh')).toBe('bash');
    expect(normalizeLanguage('shell')).toBe('bash');
    expect(normalizeLanguage('zsh')).toBe('bash');
    expect(normalizeLanguage('yml')).toBe('yaml');
    expect(normalizeLanguage('md')).toBe('markdown');
    expect(normalizeLanguage('')).toBe('text');
    expect(normalizeLanguage(undefined)).toBe('text');
  });

  it('tokenizes Python code correctly into keywords, strings, numbers, and comments', () => {
    const pythonCode = `# Healthcare helper\ndef get_benefits(user_id: int = 42):\n    return "Approved"`;
    const tokens = tokenizeCode(pythonCode, 'python');

    const commentToken = tokens.find((t) => t.type === 'comment');
    expect(commentToken).toBeDefined();
    expect(commentToken?.text).toBe('# Healthcare helper');

    const defToken = tokens.find((t) => t.type === 'keyword' && t.text === 'def');
    expect(defToken).toBeDefined();

    const numToken = tokens.find((t) => t.type === 'number');
    expect(numToken?.text).toBe('42');

    const strToken = tokens.find((t) => t.type === 'string');
    expect(strToken?.text).toBe('"Approved"');
  });

  it('tokenizes JSON keys and values', () => {
    const jsonCode = '{\n  "status": "success",\n  "code": 200,\n  "verified": true\n}';
    const tokens = tokenizeCode(jsonCode, 'json');

    const keyToken = tokens.find((t) => t.type === 'property');
    expect(keyToken).toBeDefined();

    const boolToken = tokens.find((t) => t.type === 'boolean');
    expect(boolToken?.text).toBe('true');

    const numToken = tokens.find((t) => t.type === 'number');
    expect(numToken?.text).toBe('200');
  });

  it('renders language header bar with detected language tag and Terminal icon', () => {
    render(<CodeBlock language="python" code="def get_guidelines():\n    return 'Carefold'" />);

    const langEl = screen.getByTestId('code-block-language');
    expect(langEl).toBeInTheDocument();
    expect(langEl).toHaveTextContent(/python/i);
    expect(screen.getByText(/get_guidelines/)).toBeInTheDocument();
  });

  it('defaults language to text when language tag is omitted or empty', () => {
    render(<CodeBlock code="echo 'Simple shell script'" />);

    const langEl = screen.getByTestId('code-block-language');
    expect(langEl).toBeInTheDocument();
    expect(langEl).toHaveTextContent(/text/i);
  });

  it('copies code to clipboard and displays 2000ms checkmark confirmation feedback', async () => {
    const writeTextSpy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined);
    const sampleCode = 'const api = "https://carefold.internal/v1";\nfetch(api);';

    render(<CodeBlock language="typescript" code={sampleCode} />);

    const copyBtn = screen.getByTestId('copy-code-btn');
    expect(copyBtn).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(copyBtn);
    });

    expect(writeTextSpy).toHaveBeenCalledWith(sampleCode);
    expect(screen.getByTestId('copy-code-success')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(2000);
    });

    expect(screen.queryByTestId('copy-code-success')).not.toBeInTheDocument();
  });

  it('handles clipboard copy failure gracefully without throwing exceptions', async () => {
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('Permission denied'));

    render(<CodeBlock language="json" code='{"status": "denied"}' />);
    const copyBtn = screen.getByTestId('copy-code-btn');

    await act(async () => {
      fireEvent.click(copyBtn);
    });

    expect(screen.queryByTestId('copy-code-success')).not.toBeInTheDocument();
  });

  it('renders fenced code blocks within ChatMessageItem markdown with language and copy button', () => {
    const message: ChatMessage = {
      id: 'm-code-1',
      role: 'assistant',
      content: 'Here are your instructions:\n```bash\ncarefold run visit-steward "prep"\n```\nAll done.'
    };

    render(<ChatMessageItem message={message} />);

    expect(screen.getByTestId('code-block-language')).toHaveTextContent(/bash/i);
    expect(screen.getByTestId('copy-code-btn')).toBeInTheDocument();
    expect(screen.getByText(/carefold run visit-steward/)).toBeInTheDocument();
  });

  it('handles unclosed code block during active streaming without crashing', () => {
    const message: ChatMessage = {
      id: 'm-stream-code',
      role: 'assistant',
      content: 'Streaming snippet:\n```python\nimport carefold\ncarefold.init()',
      isStreaming: true
    };

    expect(() => render(<ChatMessageItem message={message} />)).not.toThrow();
    expect(screen.getByTestId('copy-code-btn')).toBeInTheDocument();
    expect(screen.getByTestId('code-block')).toHaveTextContent(/carefold\.init/);
  });

  it('maps all token types to high-contrast classes', () => {
    expect(getTokenClassName('keyword')).toContain('text-purple-700');
    expect(getTokenClassName('string')).toContain('text-emerald-700');
    expect(getTokenClassName('number')).toContain('text-amber-700');
    expect(getTokenClassName('boolean')).toContain('text-rose-700');
    expect(getTokenClassName('comment')).toContain('italic');
    expect(getTokenClassName('property')).toContain('text-sky-700');
    expect(getTokenClassName('function')).toContain('text-blue-700');
    expect(getTokenClassName('plain')).toBeNull();
  });
});
