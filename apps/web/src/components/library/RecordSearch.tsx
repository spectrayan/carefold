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

import React, { useState } from 'react';
import Link from 'next/link';
import { Search, FileText, BookOpen, RefreshCw, AlertCircle, ArrowUpRight, Sparkles } from 'lucide-react';

export interface SearchResultItem {
  document_id: string;
  chunk_id?: string | null;
  content: string;
  score: number;
  lexical_score?: number;
  semantic_score?: number;
  metadata?: Record<string, any>;
  profile_id: string;
}

interface RecordSearchProps {
  profileId?: string;
  onSelectNote?: (slug: string) => void;
}

export function RecordSearch({ profileId = 'me', onSelectNote }: RecordSearchProps) {
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<'hybrid' | 'lexical' | 'semantic'>('hybrid');
  const [results, setResults] = useState<SearchResultItem[] | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const cleanQuery = query.trim();
    if (!cleanQuery) return;

    setIsLoading(true);
    setError(null);

    try {
      const res = await fetch(
        `/api/profiles/${encodeURIComponent(profileId)}/search?q=${encodeURIComponent(cleanQuery)}&mode=${mode}&limit=10`,
        { headers: { accept: 'application/json' } }
      );

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || errorData.error || `Search failed with status ${res.status}`);
      }

      const data: SearchResultItem[] = await res.json();
      setResults(data);
    } catch (err: any) {
      setError(err.message || 'An error occurred during search');
      setResults(null);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div data-testid="record-search-container" className="space-y-6">
      {/* Search Controls */}
      <form onSubmit={handleSearch} className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 dark:text-zinc-500" />
          <input
            type="text"
            data-testid="record-search-input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search records, lab results, clinical impressions..."
            className="w-full pl-10 pr-4 py-2.5 text-sm rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-slate-900 dark:text-zinc-100 placeholder:text-slate-500 dark:placeholder:text-zinc-400 focus:outline-none focus:ring-2 focus:ring-emerald-500 shadow-sm"
          />
        </div>

        <div className="flex items-center gap-2">
          <select
            data-testid="record-search-mode-select"
            value={mode}
            onChange={(e) => setMode(e.target.value as any)}
            className="py-2.5 px-3 text-sm rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-slate-700 dark:text-zinc-300 focus:outline-none focus:ring-2 focus:ring-emerald-500 shadow-sm"
          >
            <option value="hybrid">Hybrid (BM25 + Semantic)</option>
            <option value="lexical">Exact Keyword (BM25)</option>
            <option value="semantic">Conceptual (Dense Vector)</option>
          </select>

          <button
            type="submit"
            data-testid="record-search-submit"
            disabled={isLoading || !query.trim()}
            className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl bg-emerald-700 hover:bg-emerald-800 active:bg-emerald-900 dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-[#04201a] text-white font-medium text-sm transition shadow-sm disabled:opacity-50 shrink-0"
          >
            {isLoading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            <span>Search</span>
          </button>
        </div>
      </form>

      {/* Error Alert */}
      {error && (
        <div
          data-testid="record-search-error"
          className="p-4 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-rose-800 dark:text-rose-200 text-sm flex items-center gap-3"
        >
          <AlertCircle className="w-4 h-4 shrink-0 text-rose-600 dark:text-rose-400" />
          <span>{error}</span>
        </div>
      )}

      {/* Results Section */}
      {results !== null && (
        <div data-testid="record-search-results" className="space-y-4">
          <div className="flex items-center justify-between text-xs text-slate-500 dark:text-zinc-400 px-1">
            <span>Found {results.length} relevant record{results.length === 1 ? '' : 's'}</span>
            <span className="capitalize">{mode} retrieval mode</span>
          </div>

          {results.length === 0 ? (
            <div
              data-testid="record-search-empty"
              className="text-center py-12 px-4 rounded-2xl border border-dashed border-slate-200 dark:border-zinc-800 bg-slate-50/50 dark:bg-zinc-900/50"
            >
              <Search className="w-8 h-8 mx-auto text-slate-400 dark:text-zinc-500 mb-2" />
              <p className="text-sm font-medium text-slate-800 dark:text-zinc-200">No matching records found</p>
              <p className="text-xs text-slate-500 dark:text-zinc-400 mt-1 max-w-sm mx-auto">
                Try refining your search terms, changing the retrieval mode to Keyword or Semantic, or uploading new clinical notes.
              </p>
            </div>
          ) : (
            <div className="grid gap-3">
              {results.map((item, idx) => {
                const source = item.metadata?.source || 'document';
                const filename = item.metadata?.filename || item.metadata?.title || item.document_id;
                const isNote = source === 'note' || item.document_id.endsWith('.md');

                return (
                  <div
                    key={item.chunk_id || `${item.document_id}-${idx}`}
                    data-testid="record-search-result-item"
                    className="p-4 rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 hover:border-emerald-300 dark:hover:border-emerald-800 transition shadow-sm"
                  >
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <div className="flex items-center gap-2 min-w-0">
                        {isNote ? (
                          <BookOpen className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
                        ) : (
                          <FileText className="w-4 h-4 text-blue-600 dark:text-blue-400 shrink-0" />
                        )}
                        <span className="text-sm font-semibold text-slate-900 dark:text-zinc-100 truncate">
                          {filename}
                        </span>
                        <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400 uppercase">
                          {source}
                        </span>
                      </div>

                      <div className="flex items-center gap-2 shrink-0">
                        <span className="text-xs font-mono px-2 py-0.5 rounded-md bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-900">
                          score: {item.score.toFixed(3)}
                        </span>
                        {isNote && onSelectNote && (
                          <button
                            type="button"
                            onClick={() => onSelectNote(item.document_id.replace(/\.md$/, ''))}
                            className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700 dark:text-emerald-400 hover:underline"
                          >
                            <span>Read</span>
                            <ArrowUpRight className="w-3 h-3" />
                          </button>
                        )}
                        {!isNote && filename && (
                          <Link
                            href={`/chat?attach=${encodeURIComponent(filename)}`}
                            className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700 dark:text-emerald-400 hover:underline"
                          >
                            <span>Use in Chat</span>
                            <ArrowUpRight className="w-3 h-3" />
                          </Link>
                        )}
                      </div>
                    </div>

                    <p className="text-xs text-slate-600 dark:text-zinc-300 line-clamp-3 font-sans leading-relaxed bg-slate-50 dark:bg-zinc-950/50 p-2.5 rounded-lg border border-slate-100 dark:border-zinc-800/80">
                      {item.content}
                    </p>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Initial Callout if no search performed */}
      {results === null && !isLoading && (
        <div className="p-6 rounded-2xl border border-slate-200 dark:border-zinc-800 bg-slate-50/50 dark:bg-zinc-900/30 text-center space-y-2">
          <Sparkles className="w-6 h-6 text-emerald-600 dark:text-emerald-400 mx-auto" />
          <h3 className="text-sm font-semibold text-slate-800 dark:text-zinc-200">
            Cognitive Hybrid Search
          </h3>
          <p className="text-xs text-slate-600 dark:text-zinc-400 max-w-md mx-auto">
            Combines SIMD-accelerated BM25 exact keyword matching with dense semantic embeddings to locate dosages, diagnoses, and lab values across your uploaded records and notes.
          </p>
        </div>
      )}
    </div>
  );
}
