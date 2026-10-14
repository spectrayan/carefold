/*
 * Carefold — Healthcare AI Agent Marketplace & Runtime
 * Copyright 2026 Spectrayan (https://spectrayan.com)
 *
 * Licensed under the PolyForm Noncommercial License 1.0.0 and the
 * Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
 * Personal and household local use only. Commercial use, hosted service
 * offering, rebranding, white-labeling, and redistribution of modified
 * forks are prohibited without a written commercial license from Spectrayan.
 *
 * Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)
 */

'use client';

import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { CodeBlock } from './CodeBlock';
import { MermaidDiagram } from './MermaidDiagram';

export interface ChatMarkdownProps {
  content: string;
  className?: string;
}

export function ChatMarkdown({ content, className = '' }: ChatMarkdownProps) {
  if (!content) return null;

  return (
    <div className={`markdown-body text-sm leading-relaxed ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Code block interception vs inline code
          pre({ children }) {
            if (React.isValidElement(children)) {
              const { className: codeClassName, children: rawCode } = children.props as {
                className?: string;
                children?: React.ReactNode;
              };
              const match = /language-(\w+)/.exec(codeClassName || '');
              const lang = match ? match[1] : 'text';
              const codeString = String(rawCode || '').replace(/\n$/, '');

              if (lang === 'mermaid') {
                return <MermaidDiagram chart={codeString} />;
              }

              return <CodeBlock code={codeString} language={lang} />;
            }
            return (
              <pre className="p-3 my-2 rounded-xl bg-zinc-100 dark:bg-zinc-800 text-xs overflow-x-auto">
                {children}
              </pre>
            );
          },

          // Inline code formatting
          code({ children, className: codeClassName, ...props }) {
            return (
              <code
                className="px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 font-mono text-xs text-blue-600 dark:text-blue-400 font-medium"
                {...props}
              >
                {children}
              </code>
            );
          },

          // Responsive GFM Tables with vertical column separators and isolated horizontal scroll
          table({ children }) {
            return (
              <div className="my-3 w-full max-w-full overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900/60 shadow-sm overscroll-x-contain">
                <table className="w-full min-w-max border-collapse text-left text-sm">
                  {children}
                </table>
              </div>
            );
          },
          thead({ children }) {
            return (
              <thead className="bg-zinc-100/90 dark:bg-zinc-800/90 text-zinc-900 dark:text-zinc-100 font-semibold border-b border-zinc-200 dark:border-zinc-700">
                {children}
              </thead>
            );
          },
          tbody({ children }) {
            return (
              <tbody className="divide-y divide-zinc-200/70 dark:divide-zinc-800 bg-white dark:bg-zinc-900/60">
                {children}
              </tbody>
            );
          },
          tr({ children }) {
            return (
              <tr className="border-b last:border-b-0 border-zinc-200/70 dark:border-zinc-800 even:bg-zinc-50/50 dark:even:bg-zinc-800/30 hover:bg-zinc-100/60 dark:hover:bg-zinc-800/60 transition-colors">
                {children}
              </tr>
            );
          },
          th({ children, style }) {
            return (
              <th
                style={style}
                className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-zinc-800 dark:text-zinc-200 border-r last:border-r-0 border-zinc-200 dark:border-zinc-700 whitespace-nowrap bg-zinc-100/90 dark:bg-zinc-800/80"
              >
                {children}
              </th>
            );
          },
          td({ children, style }) {
            return (
              <td
                style={style}
                className="px-4 py-2.5 text-sm text-zinc-800 dark:text-zinc-200 border-r last:border-r-0 border-zinc-200/80 dark:border-zinc-800 align-top whitespace-nowrap"
              >
                {children}
              </td>
            );
          },

          // Typography
          h1({ children }) {
            return (
              <h1 className="text-xl font-bold mt-4 mb-2 text-zinc-900 dark:text-zinc-100 border-b border-zinc-200 dark:border-zinc-800 pb-1">
                {children}
              </h1>
            );
          },
          h2({ children }) {
            return (
              <h2 className="text-lg font-bold mt-3 mb-1.5 text-zinc-900 dark:text-zinc-100">
                {children}
              </h2>
            );
          },
          h3({ children }) {
            return (
              <h3 className="text-base font-semibold mt-2.5 mb-1 text-zinc-800 dark:text-zinc-200">
                {children}
              </h3>
            );
          },
          h4({ children }) {
            return (
              <h4 className="text-sm font-semibold mt-2 mb-1 text-zinc-800 dark:text-zinc-200">
                {children}
              </h4>
            );
          },
          p({ children }) {
            return <p className="text-sm leading-relaxed mb-2 last:mb-0">{children}</p>;
          },
          ul({ children }) {
            return (
              <ul className="list-disc pl-5 my-2 space-y-1 text-sm text-zinc-800 dark:text-zinc-200">
                {children}
              </ul>
            );
          },
          ol({ children }) {
            return (
              <ol className="list-decimal pl-5 my-2 space-y-1 text-sm text-zinc-800 dark:text-zinc-200">
                {children}
              </ol>
            );
          },
          li({ children }) {
            return <li className="text-sm leading-relaxed">{children}</li>;
          },
          blockquote({ children }) {
            return (
              <blockquote className="pl-3.5 border-l-2 border-blue-500/60 dark:border-blue-400/60 text-zinc-600 dark:text-zinc-300 italic text-sm my-2 bg-blue-50/20 dark:bg-blue-950/20 py-1.5 rounded-r-md">
                {children}
              </blockquote>
            );
          },
          hr() {
            return <hr className="my-3 border-zinc-200 dark:border-zinc-700/80" />;
          },
          a({ href, children }) {
            return (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 dark:text-blue-400 underline underline-offset-2 hover:opacity-80 transition-opacity font-medium"
              >
                {children}
              </a>
            );
          },
          strong({ children }) {
            return (
              <strong className="font-semibold text-zinc-900 dark:text-zinc-100">
                {children}
              </strong>
            );
          },
          del({ children }) {
            return <del className="line-through opacity-70">{children}</del>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
