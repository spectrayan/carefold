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

import React, { useState, useEffect, useRef } from 'react';
import { Network, Code2, Copy, Check, AlertCircle } from 'lucide-react';

export interface MermaidDiagramProps {
  chart: string;
  className?: string;
}

let idCounter = 0;

export function MermaidDiagram({ chart, className = '' }: MermaidDiagramProps) {
  const [svgHtml, setSvgHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'diagram' | 'source'>('diagram');
  const [copied, setCopied] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const copyTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Re-render when chart content or DOM dark mode changes
  useEffect(() => {
    let isCancelled = false;
    const cleanChart = chart.trim();

    if (!cleanChart) {
      setSvgHtml(null);
      setError(null);
      setIsLoading(false);
      return;
    }

    async function renderChart() {
      setIsLoading(true);
      setError(null);

      try {
        const mermaid = (await import('mermaid')).default;
        const isDark = typeof document !== 'undefined' && document.documentElement.classList.contains('dark');

        mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'loose',
          theme: isDark ? 'dark' : 'neutral',
          fontFamily: 'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
          themeVariables: isDark
            ? {
                background: '#18181b',
                primaryColor: '#2563eb',
                primaryTextColor: '#f4f4f5',
                primaryBorderColor: '#3f3f46',
                lineColor: '#71717a',
                secondaryColor: '#27272a',
                tertiaryColor: '#18181b',
              }
            : undefined,
        });

        idCounter += 1;
        const renderId = `carefold-mermaid-${idCounter}-${Date.now().toString(36)}`;
        const { svg } = await mermaid.render(renderId, cleanChart);

        if (!isCancelled) {
          setSvgHtml(svg);
          setError(null);
          setIsLoading(false);
        }
      } catch (err: unknown) {
        if (!isCancelled) {
          const errMsg = err instanceof Error ? err.message : String(err);
          setError(errMsg);
          setIsLoading(false);
        }
      }
    }

    renderChart();

    // Listen for theme class changes on <html>
    const observer = new MutationObserver(() => {
      renderChart();
    });

    if (typeof document !== 'undefined') {
      observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['class', 'data-theme'],
      });
    }

    return () => {
      isCancelled = true;
      observer.disconnect();
    };
  }, [chart]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(chart);
      setCopied(true);
      if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current);
      copyTimeoutRef.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access denied
    }
  };

  useEffect(() => {
    return () => {
      if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current);
    };
  }, []);

  return (
    <div
      data-testid="mermaid-diagram-container"
      className={`my-3 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950/70 overflow-hidden shadow-sm transition-colors ${className}`}
    >
      {/* Header bar */}
      <div className="flex items-center justify-between px-3.5 py-2 border-b border-zinc-100 dark:border-zinc-800/80 bg-zinc-50/80 dark:bg-zinc-900/60 text-xs text-zinc-600 dark:text-zinc-400 select-none">
        <div className="flex items-center gap-2">
          <Network className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />
          <span className="font-semibold text-zinc-700 dark:text-zinc-300">Mermaid Diagram</span>
          {error && (
            <span className="inline-flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400">
              <AlertCircle className="w-3 h-3" />
              <span>Previewing source</span>
            </span>
          )}
        </div>

        <div className="flex items-center gap-1">
          {/* Toggle View Mode */}
          {!error && (
            <div className="flex items-center rounded-lg border border-zinc-200 dark:border-zinc-700 p-0.5 bg-zinc-100/60 dark:bg-zinc-800/60">
              <button
                type="button"
                onClick={() => setViewMode('diagram')}
                aria-pressed={viewMode === 'diagram'}
                className={`flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium transition cursor-pointer ${
                  viewMode === 'diagram'
                    ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-zinc-100 shadow-sm'
                    : 'text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200'
                }`}
              >
                <Network className="w-3 h-3" />
                Diagram
              </button>
              <button
                type="button"
                onClick={() => setViewMode('source')}
                aria-pressed={viewMode === 'source'}
                className={`flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium transition cursor-pointer ${
                  viewMode === 'source'
                    ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-zinc-100 shadow-sm'
                    : 'text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200'
                }`}
              >
                <Code2 className="w-3 h-3" />
                Source
              </button>
            </div>
          )}

          {/* Copy Source */}
          <button
            type="button"
            onClick={handleCopy}
            title={copied ? 'Copied chart source!' : 'Copy chart source'}
            className="flex items-center gap-1 px-2 py-1 rounded-md text-xs text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 hover:bg-zinc-200/50 dark:hover:bg-zinc-800 transition cursor-pointer"
          >
            {copied ? (
              <>
                <Check className="w-3 h-3 text-emerald-600 dark:text-emerald-400" />
                <span className="text-emerald-600 dark:text-emerald-400 font-medium">Copied</span>
              </>
            ) : (
              <>
                <Copy className="w-3 h-3" />
                <span>Copy</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Body content */}
      <div className="p-4">
        {viewMode === 'source' || error ? (
          <div className="space-y-2">
            {error && (
              <p className="text-xs text-zinc-500 dark:text-zinc-400 italic">
                Diagram is compiling or contains incomplete streaming tokens. Showing source:
              </p>
            )}
            <pre className="p-3 rounded-lg bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-xs font-mono overflow-x-auto text-zinc-800 dark:text-zinc-200 leading-relaxed">
              <code>{chart}</code>
            </pre>
          </div>
        ) : isLoading ? (
          <div className="py-8 flex flex-col items-center justify-center gap-2 text-zinc-400 dark:text-zinc-500">
            <div className="w-5 h-5 border-2 border-blue-600 dark:border-blue-400 border-t-transparent rounded-full animate-spin" />
            <span className="text-xs">Rendering diagram...</span>
          </div>
        ) : svgHtml ? (
          <div
            ref={containerRef}
            data-testid="mermaid-svg-container"
            className="overflow-x-auto flex justify-center items-center py-2 [&>svg]:max-w-full [&>svg]:h-auto"
            dangerouslySetInnerHTML={{ __html: svgHtml }}
          />
        ) : null}
      </div>
    </div>
  );
}
