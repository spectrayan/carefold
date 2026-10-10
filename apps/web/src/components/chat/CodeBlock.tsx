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

import React, { useState, useRef, useEffect, useMemo } from 'react';
import { Terminal, Copy, Check } from 'lucide-react';

export interface CodeBlockProps {
  code: string;
  language?: string;
  className?: string;
}

export type TokenType =
  | 'keyword'
  | 'string'
  | 'number'
  | 'boolean'
  | 'comment'
  | 'property'
  | 'function'
  | 'operator'
  | 'plain';

export interface CodeToken {
  type: TokenType;
  text: string;
}

/**
 * Normalizes input language tags to clean standard identifiers.
 */
export function normalizeLanguage(lang?: string): string {
  if (!lang) return 'text';
  const clean = lang.trim().toLowerCase().split(/\s+/)[0];
  switch (clean) {
    case 'py':
    case 'python3':
      return 'python';
    case 'js':
    case 'mjs':
    case 'cjs':
      return 'javascript';
    case 'ts':
      return 'typescript';
    case 'jsx':
    case 'tsx':
      return clean;
    case 'sh':
    case 'shell':
    case 'zsh':
      return 'bash';
    case 'yml':
      return 'yaml';
    case 'md':
      return 'markdown';
    default:
      return clean || 'text';
  }
}

/**
 * Lightweight, pure regex syntax tokenizer.
 * 100% compatible with React 19, zero external dependencies, deterministic isomorphic SSR.
 */
export function tokenizeCode(code: string, language: string): CodeToken[] {
  if (!code) return [];
  const lang = normalizeLanguage(language);

  // Fast path for plain text or markdown
  if (lang === 'text' || lang === 'markdown' || lang === 'txt') {
    return [{ type: 'plain', text: code }];
  }

  const isPy = lang === 'python';
  const isBash = lang === 'bash';
  const isSql = lang === 'sql';
  const isJson = lang === 'json';
  const isYaml = lang === 'yaml';

  // Comments
  const comment = isBash || isPy || isYaml
    ? '#[^\\n]*'
    : isSql
    ? '--[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/'
    : '\\/\\/[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/';

  // Strings
  const str = isPy
    ? '"""[\\s\\S]*?"""|\'\'\'[\\s\\S]*?\'\'\'|"(?:\\\\.|[^"\\\\])*"|\'(?:\\\\.|[^\'\\\\])*\''
    : '"(?:\\\\.|[^"\\\\])*"|\'(?:\\\\.|[^\'\\\\])*\'|`(?:\\\\.|[^`\\\\])*`';

  // Numbers
  const num = '\\b\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?\\b|\\b0x[0-9a-fA-F]+\\b';

  // Booleans / Null / None
  const bool = '\\b(true|false|null|undefined|None|True|False|nil)\\b';

  // JSON / YAML property keys
  const jsonKey = isJson
    ? '"(?:\\\\.|[^"\\\\])*"(?=\\s*:)'
    : isYaml
    ? '^[ \\t]*[\\w.-]+(?=\\s*:)'
    : '(?!)';

  // Keywords
  const kw = isPy
    ? '\\b(def|class|return|if|elif|else|for|while|try|except|finally|raise|import|from|as|with|lambda|yield|async|await|pass|break|continue|in|is|not|and|or|global|nonlocal|assert|del)\\b'
    : isBash
    ? '\\b(if|then|else|elif|fi|case|esac|for|while|until|do|done|in|function|select|time|return|exit|export|source|alias|echo|cd|ls|cat|grep|sed|awk|curl|git|pnpm|npm|yarn|docker|kubectl|chmod|chown|mkdir|rm|cp|mv)\\b'
    : isSql
    ? '\\b(SELECT|FROM|WHERE|INSERT|INTO|UPDATE|DELETE|JOIN|LEFT|RIGHT|INNER|OUTER|ON|GROUP|BY|ORDER|HAVING|LIMIT|OFFSET|CREATE|TABLE|DROP|ALTER|INDEX|AND|OR|NOT|NULL|IS|AS|UNION|ALL|DISTINCT|CASE|WHEN|THEN|ELSE|END)\\b'
    : '\\b(const|let|var|function|return|if|else|for|while|do|switch|case|break|continue|try|catch|finally|throw|import|export|from|default|class|extends|new|this|super|async|await|yield|interface|type|enum|implements|public|private|protected|readonly|abstract|as|in|of|typeof|instanceof|void|debugger)\\b';

  // Functions
  const fn = '\\b([a-zA-Z_]\\w*)(?=\\s*\\()';

  let masterRegex: RegExp;
  try {
    masterRegex = new RegExp(
      `(?<comment>${comment})|(?<jsonKey>${jsonKey})|(?<string>${str})|(?<keyword>${kw})|(?<boolean>${bool})|(?<number>${num})|(?<fn>${fn})`,
      isSql ? 'gim' : 'gm'
    );
  } catch {
    return [{ type: 'plain', text: code }];
  }

  let lastIndex = 0;
  const tokens: CodeToken[] = [];
  let match: RegExpExecArray | null;

  while ((match = masterRegex.exec(code)) !== null) {
    if (match.index > lastIndex) {
      tokens.push({ type: 'plain', text: code.slice(lastIndex, match.index) });
    }

    if (match[0].length === 0) {
      masterRegex.lastIndex++;
      continue;
    }

    if (match.groups) {
      const matchedGroup = Object.entries(match.groups).find(([, val]) => val !== undefined);
      if (matchedGroup) {
        const [groupName] = matchedGroup;
        const type: TokenType =
          groupName === 'jsonKey' ? 'property' :
          groupName === 'fn' ? 'function' :
          (groupName as TokenType);
        tokens.push({ type, text: match[0] });
      } else {
        tokens.push({ type: 'plain', text: match[0] });
      }
    } else {
      tokens.push({ type: 'plain', text: match[0] });
    }

    lastIndex = masterRegex.lastIndex;
  }

  if (lastIndex < code.length) {
    tokens.push({ type: 'plain', text: code.slice(lastIndex) });
  }

  return tokens;
}

/**
 * Returns accessible, high-contrast Tailwind classes for each token type.
 */
export function getTokenClassName(type: TokenType): string | null {
  switch (type) {
    case 'keyword':
      return 'text-purple-700 dark:text-purple-400 font-semibold';
    case 'string':
      return 'text-emerald-700 dark:text-emerald-400';
    case 'number':
      return 'text-amber-700 dark:text-amber-400 font-mono';
    case 'boolean':
      return 'text-rose-700 dark:text-rose-400 font-semibold';
    case 'comment':
      return 'text-slate-500 dark:text-zinc-500 italic';
    case 'property':
      return 'text-sky-700 dark:text-sky-300 font-medium';
    case 'function':
      return 'text-blue-700 dark:text-blue-400';
    case 'operator':
      return 'text-slate-700 dark:text-zinc-300';
    case 'plain':
    default:
      return null;
  }
}

export function CodeBlock({ code, language = 'text', className = '' }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const copyTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (copyTimeoutRef.current) {
        clearTimeout(copyTimeoutRef.current);
      }
    };
  }, []);

  const handleCopy = async () => {
    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(code);
        setCopied(true);
      } else if (typeof document !== 'undefined') {
        const textArea = document.createElement('textarea');
        textArea.value = code;
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
      // Fail gracefully without unhandled rejection
      setCopied(false);
    }
  };

  const normalizedLanguage = useMemo(() => normalizeLanguage(language), [language]);

  const tokens = useMemo(() => {
    return tokenizeCode(code, normalizedLanguage);
  }, [code, normalizedLanguage]);

  return (
    <div
      data-testid="code-block"
      className={`my-3 rounded-xl border border-slate-200 dark:border-zinc-800 bg-slate-50 dark:bg-zinc-950 overflow-hidden shadow-sm ${className}`}
    >
      {/* Language Header Bar */}
      <div className="flex items-center justify-between px-3.5 py-1.5 bg-slate-100/90 dark:bg-zinc-900 border-b border-slate-200 dark:border-zinc-800 text-xs select-none">
        <div className="flex items-center gap-1.5">
          <Terminal className="w-3.5 h-3.5 text-slate-500 dark:text-zinc-400" aria-hidden="true" />
          <span
            data-testid="code-block-language"
            className="font-mono text-xs font-semibold text-slate-600 dark:text-zinc-400 lowercase tracking-wider"
          >
            {normalizedLanguage}
          </span>
        </div>
        <button
          type="button"
          data-testid="copy-code-btn"
          aria-label={copied ? 'Copied code' : 'Copy code'}
          title={copied ? 'Copied!' : 'Copy code'}
          onClick={handleCopy}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs text-slate-600 dark:text-zinc-300 hover:text-slate-900 dark:hover:text-white bg-white/70 dark:bg-zinc-800/60 hover:bg-white dark:hover:bg-zinc-800 border border-slate-200/80 dark:border-zinc-700/60 transition cursor-pointer shadow-sm"
        >
          {copied ? (
            <>
              <Check data-testid="copy-code-success" className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
              <span className="text-xs font-medium text-emerald-600 dark:text-emerald-400">Copied!</span>
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5 text-slate-500 dark:text-zinc-400" />
              <span className="text-xs font-medium">Copy</span>
            </>
          )}
        </button>
      </div>

      {/* Code body with horizontal scrolling */}
      <pre className="p-3.5 overflow-x-auto font-mono text-xs leading-relaxed text-slate-900 dark:text-zinc-100 selection:bg-blue-100 dark:selection:bg-blue-900/40">
        <code>
          {tokens.map((token, idx) => {
            const tokenClass = getTokenClassName(token.type);
            return tokenClass ? (
              <span key={idx} className={tokenClass}>
                {token.text}
              </span>
            ) : (
              token.text
            );
          })}
        </code>
      </pre>
    </div>
  );
}
