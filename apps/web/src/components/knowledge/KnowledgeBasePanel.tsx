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

import React, { useState, useEffect, useCallback } from 'react';
import {
  BookOpen,
  FileText,
  Plus,
  Trash2,
  Edit3,
  X,
  AlertCircle,
  Eye,
  Layers,
} from 'lucide-react';
import type { DocSummary, DocDetailResponse } from '@/types/api';

interface KnowledgeBasePanelProps {
  targetType: 'skill' | 'agent';
  targetId: string;
  isBundled?: boolean;
}

export function KnowledgeBasePanel({
  targetType,
  targetId,
  isBundled = false,
}: KnowledgeBasePanelProps) {
  const [docs, setDocs] = useState<DocSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Active viewing/editing modal state
  const [activeDoc, setActiveDoc] = useState<DocDetailResponse | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [isCreating, setIsCreating] = useState(false);

  // Form states
  const [formName, setFormName] = useState('');
  const [formTitle, setFormTitle] = useState('');
  const [formContent, setFormContent] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const fetchDocs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const endpoint = `/api/${targetType}s/${encodeURIComponent(targetId)}/docs`;
      const res = await fetch(endpoint, { cache: 'no-store' });
      if (!res.ok) {
        throw new Error(`Failed to load knowledge base: HTTP ${res.status}`);
      }
      const data = await res.json();
      setDocs(Array.isArray(data) ? data : data.docs || []);
    } catch (err: any) {
      setError(err.message || 'Error loading knowledge base');
    } finally {
      setLoading(false);
    }
  }, [targetType, targetId]);

  useEffect(() => {
    fetchDocs();
  }, [fetchDocs]);

  const handleOpenDoc = async (docName: string) => {
    setFormError(null);
    try {
      const endpoint = `/api/${targetType}s/${encodeURIComponent(targetId)}/docs/${encodeURIComponent(docName)}`;
      const res = await fetch(endpoint, { cache: 'no-store' });
      if (!res.ok) {
        throw new Error(`Failed to load doc detail: HTTP ${res.status}`);
      }
      const data: DocDetailResponse = await res.json();
      setActiveDoc(data);
      setFormTitle(data.title || data.name);
      setFormContent(data.content || '');
      setIsEditing(false);
      setIsCreating(false);
    } catch (err: any) {
      setFormError(err.message || 'Error loading document');
    }
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formName.trim() || !formContent.trim()) {
      setFormError('Name and content are required.');
      return;
    }

    setSubmitting(true);
    setFormError(null);
    try {
      const endpoint = `/api/${targetType}s/${encodeURIComponent(targetId)}/docs`;
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: formName.trim(),
          title: formTitle.trim() || formName.trim(),
          content: formContent,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${res.status} creating document`);
      }

      setIsCreating(false);
      setFormName('');
      setFormTitle('');
      setFormContent('');
      await fetchDocs();
    } catch (err: any) {
      setFormError(err.message || 'Failed to create document');
    } finally {
      setSubmitting(false);
    }
  };

  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeDoc) return;

    setSubmitting(true);
    setFormError(null);
    try {
      const endpoint = `/api/${targetType}s/${encodeURIComponent(targetId)}/docs/${encodeURIComponent(activeDoc.name)}`;
      const res = await fetch(endpoint, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: formTitle.trim() || activeDoc.name,
          content: formContent,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${res.status} updating document`);
      }

      const updated = await res.json();
      setActiveDoc(updated);
      setIsEditing(false);
      await fetchDocs();
    } catch (err: any) {
      setFormError(err.message || 'Failed to update document');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (docName: string) => {
    if (!window.confirm(`Are you sure you want to delete "${docName}" from knowledge base?`)) {
      return;
    }

    try {
      const endpoint = `/api/${targetType}s/${encodeURIComponent(targetId)}/docs/${encodeURIComponent(docName)}`;
      const res = await fetch(endpoint, { method: 'DELETE' });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${res.status} deleting document`);
      }
      if (activeDoc?.name === docName) {
        setActiveDoc(null);
      }
      await fetchDocs();
    } catch (err: any) {
      alert(`Delete failed: ${err.message}`);
    }
  };

  return (
    <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl p-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-100 dark:border-zinc-800 pb-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-indigo-50 dark:bg-indigo-950/40 text-indigo-600 dark:text-indigo-400 flex items-center justify-center border border-indigo-200/60 dark:border-indigo-800/40">
            <BookOpen className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-bold text-slate-900 dark:text-zinc-100">
                Knowledge Base & Clinical Guidelines
              </h3>
              {isBundled && (
                <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400 border border-slate-200 dark:border-zinc-700">
                  Bundled
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500 dark:text-zinc-400">
              Reference documents ingested and ground-truth verified for this {targetType}.
            </p>
          </div>
        </div>

        <button
          onClick={() => {
            setIsCreating(true);
            setActiveDoc(null);
            setFormName('');
            setFormTitle('');
            setFormContent('');
            setFormError(null);
          }}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-semibold bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm transition"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>Add Document</span>
        </button>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="flex items-center gap-2 p-3 text-xs rounded-xl bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Loading state */}
      {loading ? (
        <div className="py-8 text-center text-xs text-slate-400 dark:text-zinc-500">
          Loading knowledge base documents...
        </div>
      ) : docs.length === 0 ? (
        <div className="py-10 text-center space-y-2 border-2 border-dashed border-slate-100 dark:border-zinc-800/80 rounded-xl">
          <FileText className="w-8 h-8 mx-auto text-slate-300 dark:text-zinc-600" />
          <p className="text-sm font-medium text-slate-600 dark:text-zinc-400">
            No knowledge base documents found
          </p>
          <p className="text-xs text-slate-400 dark:text-zinc-500 max-w-sm mx-auto">
            Add clinical prep guides, formulary notes, or navigational references to empower AI reasoning.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {docs.map((d) => {
            const isInherited = d.source === 'skill' && targetType === 'agent';
            return (
              <div
                key={d.id || d.name}
                className="group flex items-start justify-between p-3.5 rounded-xl bg-slate-50 dark:bg-zinc-800/50 hover:bg-slate-100 dark:hover:bg-zinc-800 border border-slate-200/70 dark:border-zinc-700/60 transition"
              >
                <div
                  className="flex-1 cursor-pointer pr-3"
                  onClick={() => handleOpenDoc(d.name)}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <FileText className="w-3.5 h-3.5 text-indigo-500 shrink-0" />
                    <span className="text-xs font-bold text-slate-800 dark:text-zinc-200 group-hover:text-indigo-600 dark:group-hover:text-indigo-400 transition truncate">
                      {d.title || d.name}
                    </span>
                    {isInherited && (
                      <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800/50">
                        <Layers className="w-2.5 h-2.5" />
                        <span>skill:{d.source_id}</span>
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-[11px] text-slate-400 dark:text-zinc-500 font-mono">
                    <span>{d.name}</span>
                    <span>•</span>
                    <span>{(d.size_bytes / 1024).toFixed(1)} KB</span>
                  </div>
                </div>

                <div className="flex items-center gap-1 opacity-80 group-hover:opacity-100 transition">
                  <button
                    onClick={() => handleOpenDoc(d.name)}
                    className="p-1.5 rounded-lg text-slate-500 hover:text-indigo-600 dark:text-zinc-400 dark:hover:text-indigo-400 hover:bg-white dark:hover:bg-zinc-700 transition"
                    title="View Document"
                  >
                    <Eye className="w-3.5 h-3.5" />
                  </button>

                  {!isInherited && (
                    <button
                      onClick={() => handleDelete(d.name)}
                      className="p-1.5 rounded-lg text-slate-400 hover:text-rose-600 dark:text-zinc-500 dark:hover:text-rose-400 hover:bg-white dark:hover:bg-zinc-700 transition"
                      title="Delete Document"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Create Document Modal */}
      {isCreating && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm">
          <div className="w-full max-w-2xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-3xl shadow-xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between p-5 border-b border-slate-100 dark:border-zinc-800">
              <div className="flex items-center gap-2.5">
                <BookOpen className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                <h4 className="text-sm font-bold text-slate-900 dark:text-zinc-100">
                  Add Knowledge Base Document
                </h4>
              </div>
              <button
                onClick={() => setIsCreating(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-zinc-200"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleCreateSubmit} className="p-5 space-y-4">
              {formError && (
                <div className="p-3 text-xs rounded-xl bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900">
                  {formError}
                </div>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
                    Filename (e.g. guidelines.md)
                  </label>
                  <input
                    type="text"
                    required
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                    placeholder="clinical-reference.md"
                    className="w-full px-3 py-2 text-xs rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 font-mono focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
                    Human-Readable Title
                  </label>
                  <input
                    type="text"
                    value={formTitle}
                    onChange={(e) => setFormTitle(e.target.value)}
                    placeholder="Clinical Reference Guidelines"
                    className="w-full px-3 py-2 text-xs rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
                  Markdown Content
                </label>
                <textarea
                  rows={10}
                  required
                  value={formContent}
                  onChange={(e) => setFormContent(e.target.value)}
                  placeholder="# Clinical Guidelines&#10;&#10;Reference clinical knowledge here..."
                  className="w-full p-3 text-xs rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 font-mono focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none leading-relaxed"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsCreating(false)}
                  className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-600 dark:text-zinc-400 hover:bg-slate-100 dark:hover:bg-zinc-800 transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="px-4 py-2 rounded-xl text-xs font-semibold bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm transition disabled:opacity-50"
                >
                  {submitting ? 'Saving...' : 'Add Document'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* View / Edit Document Modal */}
      {activeDoc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm">
          <div className="w-full max-w-3xl max-h-[85vh] flex flex-col bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-3xl shadow-xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between p-5 border-b border-slate-100 dark:border-zinc-800">
              <div className="flex items-center gap-3">
                <FileText className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                <div>
                  <h4 className="text-sm font-bold text-slate-900 dark:text-zinc-100">
                    {activeDoc.title || activeDoc.name}
                  </h4>
                  <p className="text-[11px] text-slate-400 font-mono">
                    {activeDoc.name} • {(activeDoc.size_bytes / 1024).toFixed(1)} KB
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                {!isEditing ? (
                  <button
                    onClick={() => setIsEditing(true)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-slate-100 hover:bg-slate-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-slate-700 dark:text-zinc-300 transition"
                  >
                    <Edit3 className="w-3.5 h-3.5" />
                    <span>Edit</span>
                  </button>
                ) : (
                  <button
                    onClick={() => setIsEditing(false)}
                    className="px-3 py-1.5 rounded-xl text-xs font-semibold text-slate-500 hover:bg-slate-100 dark:hover:bg-zinc-800 transition"
                  >
                    Cancel Edit
                  </button>
                )}

                <button
                  onClick={() => setActiveDoc(null)}
                  className="p-1 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-zinc-200"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            <div className="p-6 overflow-y-auto flex-1 space-y-4">
              {formError && (
                <div className="p-3 text-xs rounded-xl bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900">
                  {formError}
                </div>
              )}

              {isEditing ? (
                <form onSubmit={handleEditSubmit} className="space-y-4">
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
                      Title
                    </label>
                    <input
                      type="text"
                      value={formTitle}
                      onChange={(e) => setFormTitle(e.target.value)}
                      className="w-full px-3 py-2 text-xs rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
                      Markdown Content
                    </label>
                    <textarea
                      rows={14}
                      value={formContent}
                      onChange={(e) => setFormContent(e.target.value)}
                      className="w-full p-3 text-xs rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 font-mono focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none leading-relaxed"
                    />
                  </div>

                  <div className="flex justify-end gap-2 pt-2">
                    <button
                      type="button"
                      onClick={() => setIsEditing(false)}
                      className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-600 dark:text-zinc-400 hover:bg-slate-100 dark:hover:bg-zinc-800 transition"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={submitting}
                      className="px-4 py-2 rounded-xl text-xs font-semibold bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm transition disabled:opacity-50"
                    >
                      {submitting ? 'Saving...' : 'Save Changes'}
                    </button>
                  </div>
                </form>
              ) : (
                <pre className="p-4 rounded-2xl bg-slate-50 dark:bg-zinc-950 border border-slate-200/80 dark:border-zinc-800 text-xs font-mono text-slate-800 dark:text-zinc-200 whitespace-pre-wrap leading-relaxed overflow-x-auto">
                  {activeDoc.content}
                </pre>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
