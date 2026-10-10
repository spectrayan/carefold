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

'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Copy, Check, RotateCcw } from 'lucide-react';

export interface MessageToolbarProps {
  role: 'user' | 'assistant';
  content: string;
  messageId: string;
  onRerun?: (prompt: string) => void;
  onRegenerate?: (messageId: string) => void;
  disabled?: boolean;
  isStreaming?: boolean;
}

export function MessageToolbar({
  role,
  content,
  messageId,
  onRerun,
  onRegenerate,
  disabled = false,
  isStreaming = false
}: MessageToolbarProps) {
  const [copied, setCopied] = useState(false);
  const copyTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current);
    };
  }, []);

  const handleCopy = async () => {
    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(content);
        setCopied(true);
      } else if (typeof document !== 'undefined') {
        const textArea = document.createElement('textarea');
        textArea.value = content;
        textArea.style.position = 'fixed';
        textArea.style.opacity = '0';
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
        setCopied(true);
      }
      if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current);
      copyTimeoutRef.current = setTimeout(() => {
        setCopied(false);
      }, 2000);
    } catch {
      // In non-secure contexts or testing environments without clipboard, fail gracefully
      setCopied(false);
    }
  };

  const isUser = role === 'user';

  const containerClasses = isUser
    ? 'flex items-center gap-0.5 bg-slate-200/80 dark:bg-zinc-700/80 rounded-lg p-0.5 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100 transition-opacity'
    : 'flex items-center gap-1 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100 transition-opacity';

  const buttonClasses = isUser
    ? 'min-w-[44px] min-h-[44px] p-2.5 rounded hover:bg-slate-300 dark:hover:bg-zinc-600 text-slate-700 dark:text-zinc-200 hover:text-slate-900 dark:hover:text-white transition flex items-center justify-center cursor-pointer'
    : 'min-w-[44px] min-h-[44px] p-2.5 rounded-lg hover:bg-slate-100 dark:hover:bg-zinc-800 text-slate-600 dark:text-zinc-300 hover:text-slate-900 dark:hover:text-zinc-100 transition flex items-center justify-center cursor-pointer';

  const rerunButtonClasses = isUser
    ? 'min-w-[44px] min-h-[44px] p-2.5 rounded hover:bg-slate-300 dark:hover:bg-zinc-600 text-slate-700 dark:text-zinc-200 hover:text-slate-900 dark:hover:text-white transition disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center cursor-pointer'
    : 'min-w-[44px] min-h-[44px] p-2.5 rounded-lg hover:bg-slate-100 dark:hover:bg-zinc-800 text-slate-600 dark:text-zinc-300 hover:text-slate-900 dark:hover:text-zinc-100 transition disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center cursor-pointer';

  return (
    <div
      data-testid="message-action-toolbar"
      role="toolbar"
      aria-label="Message actions"
      className={containerClasses}
    >
      <span data-testid="message-hover-toolbar" className="sr-only">Message Toolbar</span>

      {/* Copy Button */}
      <button
        type="button"
        data-testid="message-copy-btn"
        aria-label={copied ? 'Copied' : 'Copy message'}
        title={copied ? 'Copied!' : 'Copy message'}
        onClick={handleCopy}
        className={buttonClasses}
      >
        <span data-testid="copy-message-btn" className="sr-only">Copy</span>
        {copied ? (
          <Check
            data-testid="message-copy-success"
            className={isUser ? 'w-3.5 h-3.5 text-emerald-300' : 'w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400'}
          />
        ) : (
          <Copy data-testid="copy-icon" className="w-3.5 h-3.5" />
        )}
      </button>

      {/* User Rerun Button */}
      {isUser && onRerun && (
        <button
          type="button"
          data-testid="message-rerun-btn"
          data-action="rerun"
          aria-label="Rerun prompt"
          title="Rerun prompt"
          disabled={disabled}
          onClick={() => onRerun(content)}
          className={rerunButtonClasses}
        >
          <span data-testid="rerun-message-btn" className="sr-only">Rerun prompt</span>
          <RotateCcw className="w-3.5 h-3.5" />
        </button>
      )}

      {/* Assistant Regenerate Button */}
      {!isUser && onRegenerate && (
        <button
          type="button"
          data-testid="message-rerun-btn"
          data-action="regenerate"
          aria-label="Regenerate response"
          title="Regenerate response"
          disabled={disabled || isStreaming}
          onClick={() => onRegenerate(messageId)}
          className={rerunButtonClasses}
        >
          <span data-testid="rerun-message-btn" className="sr-only">Regenerate response</span>
          <RotateCcw className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
}
