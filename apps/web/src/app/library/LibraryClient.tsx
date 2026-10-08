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

import React, { useState, useRef, useMemo } from 'react';
import Link from 'next/link';
import { useSearchParams, useRouter } from 'next/navigation';
import {
  ShieldCheck,
  FileText,
  BookOpen,
  Upload,
  Download,
  Copy,
  Check,
  Search,
  MessageSquare,
  AlertCircle,
  X,
  File,
  Bot,
  RefreshCw
} from 'lucide-react';
import type { AttachmentItem, WorkspaceNoteDetail, WorkspaceNoteSummary } from '@/types/api';
import {
  fetchAttachments,
  fetchNoteDetail,
  uploadAttachment,
  formatDate,
  formatFileSize,
  getFileFormat
} from '@/lib/library';
import { ChatMarkdown } from '@/components/chat/ChatMarkdown';

interface LibraryClientProps {
  initialAttachments: AttachmentItem[];
  initialNotes: WorkspaceNoteSummary[];
}

export function LibraryClient({ initialAttachments, initialNotes }: LibraryClientProps) {
  const searchParams = useSearchParams();
  const router = useRouter();

  const tabParam = searchParams.get('tab');
  const [activeTab, setActiveTab] = useState<'documents' | 'notes'>(
    tabParam === 'notes' ? 'notes' : 'documents'
  );

  const [attachments, setAttachments] = useState<AttachmentItem[]>(initialAttachments);
  const [notes] = useState<WorkspaceNoteSummary[]>(initialNotes);
  const [searchQuery, setSearchQuery] = useState('');

  // Selected note for modal viewer
  const [selectedNote, setSelectedNote] = useState<WorkspaceNoteDetail | null>(null);
  const [isLoadingNote, setIsLoadingNote] = useState(false);
  const [noteError, setNoteError] = useState<string | null>(null);
  const [copiedNote, setCopiedNote] = useState(false);

  // Upload state
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [duplicateWarning, setDuplicateWarning] = useState<{
    file: File;
    existingName: string;
  } | null>(null);

  // Synchronize tab state with URL search param
  const handleTabChange = (tab: 'documents' | 'notes') => {
    setActiveTab(tab);
    setSearchQuery('');
    const newParams = new URLSearchParams(searchParams.toString());
    newParams.set('tab', tab);
    router.replace(`/library?${newParams.toString()}`);
  };

  // Filtered documents
  const filteredAttachments = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    if (!q) return attachments;
    return attachments.filter((doc) => doc.filename.toLowerCase().includes(q));
  }, [attachments, searchQuery]);

  // Filtered notes
  const filteredNotes = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    if (!q) return notes;
    return notes.filter(
      (n) =>
        n.title.toLowerCase().includes(q) ||
        n.slug.toLowerCase().includes(q) ||
        (n.agent && n.agent.toLowerCase().includes(q))
    );
  }, [notes, searchQuery]);

  // Open note reader
  const handleOpenNote = async (slug: string) => {
    setIsLoadingNote(true);
    setNoteError(null);
    setCopiedNote(false);
    try {
      const detail = await fetchNoteDetail(slug);
      setSelectedNote(detail);
    } catch (err: any) {
      setNoteError(err.message || 'Failed to load note');
    } finally {
      setIsLoadingNote(false);
    }
  };

  // Copy note markdown to clipboard
  const handleCopyNote = async () => {
    if (!selectedNote) return;
    try {
      await navigator.clipboard.writeText(selectedNote.content);
      setCopiedNote(true);
      setTimeout(() => setCopiedNote(false), 2000);
    } catch (err) {
      console.error('Failed to copy note:', err);
    }
  };

  // Export note as .md file
  const handleExportNote = () => {
    if (!selectedNote) return;
    const blob = new Blob([selectedNote.raw_content || selectedNote.content], {
      type: 'text/markdown;charset=utf-8'
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${selectedNote.slug}.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  // Handle file selection for upload
  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Check for duplicate name
    const existing = attachments.find(
      (a) => a.filename.toLowerCase() === file.name.toLowerCase()
    );
    if (existing) {
      setDuplicateWarning({ file, existingName: existing.filename });
      if (fileInputRef.current) fileInputRef.current.value = '';
      return;
    }

    await performUpload(file);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const performUpload = async (file: File) => {
    setIsUploading(true);
    setUploadError(null);
    try {
      await uploadAttachment(file);
      // Refresh list
      const updated = await fetchAttachments();
      setAttachments(updated);
      setDuplicateWarning(null);
    } catch (err: any) {
      setUploadError(err.message || 'Failed to upload document');
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold text-slate-900 dark:text-zinc-100 tracking-tight">
            Library
          </h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-zinc-400">
            Browse medical documents and clinical consultation notes in your local workspace.
          </p>
        </div>

        {/* Data Residency Notice */}
        <div
          data-testid="data-residency-notice"
          className="inline-flex items-center gap-2.5 px-3.5 py-2 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-300 text-xs sm:text-sm font-medium shadow-sm"
        >
          <ShieldCheck className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
          <span>Stored on this computer in your Carefold workspace</span>
        </div>
      </div>

      {/* Tabs Navigation */}
      <div className="border-b border-slate-200 dark:border-zinc-800 flex items-center justify-between">
        <nav className="flex gap-8 -mb-px" aria-label="Library tabs">
          <button
            type="button"
            data-testid="tab-documents"
            onClick={() => handleTabChange('documents')}
            className={`flex items-center gap-2 py-4 px-1 text-sm font-semibold border-b-2 transition ${
              activeTab === 'documents'
                ? 'border-emerald-600 text-emerald-600 dark:border-emerald-400 dark:text-emerald-400'
                : 'border-transparent text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-200 hover:border-slate-300'
            }`}
          >
            <FileText className="w-4 h-4" />
            <span>Documents</span>
            <span className="ml-1.5 px-2 py-0.5 rounded-full text-xs bg-slate-100 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300">
              {attachments.length}
            </span>
          </button>

          <button
            type="button"
            data-testid="tab-notes"
            onClick={() => handleTabChange('notes')}
            className={`flex items-center gap-2 py-4 px-1 text-sm font-semibold border-b-2 transition ${
              activeTab === 'notes'
                ? 'border-emerald-600 text-emerald-600 dark:border-emerald-400 dark:text-emerald-400'
                : 'border-transparent text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-200 hover:border-slate-300'
            }`}
          >
            <BookOpen className="w-4 h-4" />
            <span>Notes</span>
            <span className="ml-1.5 px-2 py-0.5 rounded-full text-xs bg-slate-100 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300">
              {notes.length}
            </span>
          </button>
        </nav>
      </div>

      {/* Search and Action Bar */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 dark:text-zinc-500" />
          <input
            type="text"
            data-testid="library-search-input"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={
              activeTab === 'documents'
                ? 'Search documents by filename...'
                : 'Search notes by title, agent, or slug...'
            }
            className="w-full pl-10 pr-4 py-2 text-sm rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-slate-900 dark:text-zinc-100 placeholder:text-slate-400 dark:placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-emerald-500"
          />
        </div>

        {activeTab === 'documents' && (
          <div>
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileSelect}
              className="hidden"
              accept=".txt,.pdf,.md,.json,.csv,.tsv,.yaml,.yml"
            />
            <button
              type="button"
              data-testid="upload-document-button"
              disabled={isUploading}
              onClick={() => fileInputRef.current?.click()}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 active:bg-emerald-800 text-white font-medium text-sm transition shadow-sm disabled:opacity-50"
            >
              {isUploading ? (
                <RefreshCw className="w-4 h-4 animate-spin" />
              ) : (
                <Upload className="w-4 h-4" />
              )}
              <span>{isUploading ? 'Uploading...' : 'Upload document'}</span>
            </button>
          </div>
        )}
      </div>

      {/* Upload error alert */}
      {uploadError && (
        <div
          data-testid="upload-error-alert"
          className="p-4 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-rose-800 dark:text-rose-200 text-sm flex items-center justify-between"
        >
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0 text-rose-600 dark:text-rose-400" />
            <span>{uploadError}</span>
          </div>
          <button
            type="button"
            onClick={() => setUploadError(null)}
            className="text-rose-600 dark:text-rose-400 hover:text-rose-800"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Duplicate warning modal */}
      {duplicateWarning && (
        <div
          data-testid="duplicate-warning-modal"
          className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-sm flex items-center justify-center p-4"
        >
          <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl max-w-md w-full p-6 shadow-xl space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-amber-100 dark:bg-amber-950/50 flex items-center justify-center text-amber-600 dark:text-amber-400">
                <AlertCircle className="w-5 h-5" />
              </div>
              <div>
                <h3 className="font-semibold text-slate-900 dark:text-zinc-100">
                  Document already exists
                </h3>
                <p className="text-xs text-slate-500 dark:text-zinc-400">
                  {duplicateWarning.existingName}
                </p>
              </div>
            </div>

            <p className="text-sm text-slate-600 dark:text-zinc-300">
              A file named <strong>&quot;{duplicateWarning.existingName}&quot;</strong> is already in your workspace. Carefold will preserve the existing file and save this document as a new version.
            </p>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setDuplicateWarning(null)}
                className="px-4 py-2 rounded-xl text-sm font-medium text-slate-700 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-800 transition"
              >
                Cancel
              </button>
              <button
                type="button"
                data-testid="confirm-duplicate-upload-button"
                onClick={() => performUpload(duplicateWarning.file)}
                className="px-4 py-2 rounded-xl text-sm font-medium bg-emerald-600 hover:bg-emerald-700 text-white transition"
              >
                Save as new version
              </button>
            </div>
          </div>
        </div>
      )}

      {/* TAB CONTENT: DOCUMENTS */}
      {activeTab === 'documents' && (
        <div>
          {filteredAttachments.length === 0 ? (
            <div
              data-testid="documents-empty-state"
              className="text-center py-16 px-4 rounded-2xl border-2 border-dashed border-slate-200 dark:border-zinc-800"
            >
              <div className="w-12 h-12 mx-auto rounded-2xl bg-emerald-50 dark:bg-emerald-950/40 flex items-center justify-center text-emerald-600 dark:text-emerald-400 mb-4">
                <FileText className="w-6 h-6" />
              </div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-zinc-100">
                {searchQuery ? 'No documents found' : 'No documents uploaded yet'}
              </h3>
              <p className="mt-1 text-sm text-slate-600 dark:text-zinc-400 max-w-sm mx-auto">
                {searchQuery
                  ? `No uploaded files match "${searchQuery}".`
                  : 'Upload medical records, lab reports, or insurance summaries in the chat composer to review them here.'}
              </p>
              {!searchQuery && (
                <div className="mt-6">
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-sm transition"
                  >
                    <Upload className="w-4 h-4" />
                    <span>Upload your first document</span>
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl overflow-hidden shadow-sm">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm" data-testid="documents-table">
                  <thead className="bg-slate-50 dark:bg-zinc-800/50 border-b border-slate-200 dark:border-zinc-800 text-xs font-semibold text-slate-600 dark:text-zinc-400 uppercase tracking-wider">
                    <tr>
                      <th scope="col" className="px-6 py-3.5">
                        Document
                      </th>
                      <th scope="col" className="px-6 py-3.5">
                        Format
                      </th>
                      <th scope="col" className="px-6 py-3.5">
                        Size
                      </th>
                      <th scope="col" className="px-6 py-3.5">
                        Uploaded
                      </th>
                      <th scope="col" className="px-6 py-3.5 text-right">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-zinc-800">
                    {filteredAttachments.map((doc) => {
                      const format = getFileFormat(doc.filename);
                      return (
                        <tr
                          key={doc.filename}
                          data-testid={`document-row-${doc.filename}`}
                          className="hover:bg-slate-50/75 dark:hover:bg-zinc-800/40 transition"
                        >
                          <td className="px-6 py-4">
                            <div className="flex items-center gap-3">
                              <div className="w-9 h-9 rounded-lg bg-slate-100 dark:bg-zinc-800 flex items-center justify-center text-slate-600 dark:text-zinc-300 shrink-0">
                                <File className="w-4 h-4" />
                              </div>
                              <div className="truncate max-w-xs sm:max-w-md">
                                <span className="font-medium text-slate-900 dark:text-zinc-100 block truncate">
                                  {doc.filename}
                                </span>
                                <span className="text-xs text-slate-500 dark:text-zinc-400">
                                  {doc.path}
                                </span>
                              </div>
                            </div>
                          </td>
                          <td className="px-6 py-4">
                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 dark:bg-zinc-800 text-slate-800 dark:text-zinc-200">
                              {format}
                            </span>
                          </td>
                          <td className="px-6 py-4 text-slate-600 dark:text-zinc-400">
                            {formatFileSize(doc.size)}
                          </td>
                          <td className="px-6 py-4 text-slate-600 dark:text-zinc-400">
                            {formatDate(doc.timestamp)}
                          </td>
                          <td className="px-6 py-4 text-right">
                            <Link
                              href={`/chat?attach=${encodeURIComponent(doc.filename)}`}
                              data-testid={`use-in-chat-${doc.filename}`}
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-50 dark:bg-emerald-950/50 hover:bg-emerald-100 dark:hover:bg-emerald-900/50 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 transition"
                            >
                              <MessageSquare className="w-3.5 h-3.5" />
                              <span>Use in chat</span>
                            </Link>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB CONTENT: NOTES */}
      {activeTab === 'notes' && (
        <div>
          {filteredNotes.length === 0 ? (
            <div
              data-testid="notes-empty-state"
              className="text-center py-16 px-4 rounded-2xl border-2 border-dashed border-slate-200 dark:border-zinc-800"
            >
              <div className="w-12 h-12 mx-auto rounded-2xl bg-emerald-50 dark:bg-emerald-950/40 flex items-center justify-center text-emerald-600 dark:text-emerald-400 mb-4">
                <BookOpen className="w-6 h-6" />
              </div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-zinc-100">
                {searchQuery ? 'No notes found' : 'No notes saved yet'}
              </h3>
              <p className="mt-1 text-sm text-slate-600 dark:text-zinc-400 max-w-md mx-auto">
                {searchQuery
                  ? `No saved notes match "${searchQuery}".`
                  : 'When Carefold specialist agents (like Visit Steward or Cardiology Guide) prepare visit agendas or checklists, they save them as structured notes in your local workspace.'}
              </p>
              {!searchQuery && (
                <div className="mt-6">
                  <Link
                    href="/chat"
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-sm transition"
                  >
                    <MessageSquare className="w-4 h-4" />
                    <span>Start a consultation</span>
                  </Link>
                </div>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5" data-testid="notes-grid">
              {filteredNotes.map((note) => (
                <div
                  key={note.slug}
                  data-testid={`note-card-${note.slug}`}
                  onClick={() => handleOpenNote(note.slug)}
                  className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl p-5 shadow-sm hover:border-emerald-500/50 dark:hover:border-emerald-500/50 hover:shadow-md transition cursor-pointer flex flex-col justify-between gap-4 group"
                >
                  <div className="space-y-3">
                    {/* Primary Note Title */}
                    <div className="flex items-start justify-between gap-2">
                      <h2
                        data-testid={`note-title-${note.slug}`}
                        className="text-base sm:text-lg font-semibold text-slate-900 dark:text-zinc-100 group-hover:text-emerald-600 dark:group-hover:text-emerald-400 transition line-clamp-2"
                      >
                        {note.title}
                      </h2>
                    </div>

                    {/* Agent badge */}
                    {note.agent && (
                      <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">
                        <Bot className="w-3.5 h-3.5" />
                        <span>@{note.agent}</span>
                      </div>
                    )}
                  </div>

                  {/* Metadata and action */}
                  <div className="pt-3 border-t border-slate-100 dark:border-zinc-800 flex items-center justify-between text-xs text-slate-500 dark:text-zinc-400">
                    <div className="space-y-0.5">
                      <div>{formatDate(note.created_at)}</div>
                      <div className="font-mono text-[11px] text-slate-400 dark:text-zinc-500">
                        {note.slug}.md • {formatFileSize(note.size_bytes)}
                      </div>
                    </div>
                    <button
                      type="button"
                      data-testid={`read-note-${note.slug}`}
                      className="px-3 py-1.5 rounded-lg bg-slate-100 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300 font-medium group-hover:bg-emerald-600 group-hover:text-white transition"
                    >
                      Read Note
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Note Detail Modal */}
      {(selectedNote || isLoadingNote || noteError) && (
        <div
          data-testid="note-detail-modal"
          className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center p-4 sm:p-6"
        >
          <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl max-w-3xl w-full max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
            {/* Modal Header */}
            <div className="p-5 sm:p-6 border-b border-slate-200 dark:border-zinc-800 flex items-start justify-between gap-4">
              <div className="space-y-1.5 flex-1 min-w-0">
                <h3
                  data-testid="modal-note-title"
                  className="text-lg sm:text-xl font-bold text-slate-900 dark:text-zinc-100 truncate"
                >
                  {selectedNote?.title || 'Loading note...'}
                </h3>
                {selectedNote && (
                  <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500 dark:text-zinc-400">
                    {selectedNote.agent && (
                      <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400 font-medium">
                        <Bot className="w-3.5 h-3.5" />
                        @{selectedNote.agent}
                      </span>
                    )}
                    <span>{formatDate(selectedNote.created_at)}</span>
                    <span className="font-mono bg-slate-100 dark:bg-zinc-800 px-2 py-0.5 rounded text-[11px]">
                      {selectedNote.slug}.md
                    </span>
                    <span>{formatFileSize(selectedNote.size_bytes)}</span>
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2 shrink-0">
                {selectedNote && (
                  <>
                    <button
                      type="button"
                      data-testid="modal-copy-note"
                      onClick={handleCopyNote}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-700 dark:text-zinc-200 text-xs font-medium hover:bg-slate-50 dark:hover:bg-zinc-700 transition"
                    >
                      {copiedNote ? (
                        <>
                          <Check className="w-3.5 h-3.5 text-emerald-600" />
                          <span>Copied!</span>
                        </>
                      ) : (
                        <>
                          <Copy className="w-3.5 h-3.5" />
                          <span>Copy</span>
                        </>
                      )}
                    </button>
                    <button
                      type="button"
                      data-testid="modal-export-note"
                      onClick={handleExportNote}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-700 dark:text-zinc-200 text-xs font-medium hover:bg-slate-50 dark:hover:bg-zinc-700 transition"
                    >
                      <Download className="w-3.5 h-3.5" />
                      <span>Export .md</span>
                    </button>
                  </>
                )}
                <button
                  type="button"
                  data-testid="modal-close-note"
                  onClick={() => {
                    setSelectedNote(null);
                    setNoteError(null);
                  }}
                  className="p-1.5 rounded-lg text-slate-500 hover:text-slate-800 dark:text-zinc-400 dark:hover:text-zinc-100 hover:bg-slate-100 dark:hover:bg-zinc-800 transition"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* Modal Body */}
            <div className="p-6 overflow-y-auto flex-1">
              {isLoadingNote ? (
                <div className="py-12 flex flex-col items-center justify-center gap-3 text-slate-500 dark:text-zinc-400">
                  <RefreshCw className="w-6 h-6 animate-spin text-emerald-600" />
                  <span>Loading note contents...</span>
                </div>
              ) : noteError ? (
                <div className="p-4 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-rose-800 dark:text-rose-200 text-sm">
                  {noteError}
                </div>
              ) : selectedNote ? (
                <div className="prose dark:prose-invert max-w-none text-slate-800 dark:text-zinc-200">
                  <ChatMarkdown content={selectedNote.content} />
                </div>
              ) : null}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
