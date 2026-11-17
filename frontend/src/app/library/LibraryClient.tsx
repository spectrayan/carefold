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

import React, { useState, useMemo, useRef, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { useSearchParams, useRouter } from 'next/navigation';
import {
  FileText,
  BookOpen,
  Search,
  Upload,
  Copy,
  Download,
  X,
  Check,
  File,
  AlertCircle,
  MessageSquare,
  Bot,
  RefreshCw,
  Plus,
  Trash2,
  Edit2,
  Tag,
} from 'lucide-react';
import {
  fetchAttachments,
  fetchNotes,
  fetchNoteDetail,
  uploadAttachment,
  createNote,
  updateNote,
  deleteNote,
  deleteAttachment,
  formatFileSize,
  formatDate,
  getFileFormat,
  CreateNoteRequest,
} from '@/lib/library';
import { RecordSearch } from '@/components/library/RecordSearch';
import { ChatMarkdown } from '@/components/chat/ChatMarkdown';
import type {
  AttachmentItem,
  WorkspaceNoteDetail,
  WorkspaceNoteSummary
} from '@/types/api';
import { useI18n } from '@/i18n';

export interface LibraryClientProps {
  initialAttachments: AttachmentItem[];
  initialNotes: WorkspaceNoteSummary[];
  profileId?: string;
}

const NOTE_CATEGORIES = [
  { id: 'visit_prep', label: 'Visit Preparation' },
  { id: 'after_visit', label: 'After Visit Summary' },
  { id: 'medication_notes', label: 'Medication Notes' },
  { id: 'insurance_call', label: 'Insurance Call' },
  { id: 'symptom_log', label: 'Symptom Log' },
  { id: 'scratchpad', label: 'Scratchpad' },
  { id: 'general', label: 'General Note' },
];

function deduplicateAttachments(items: AttachmentItem[]): AttachmentItem[] {
  const seen = new Set<string>();
  const result: AttachmentItem[] = [];
  for (const item of items) {
    const key = item.filename.toLowerCase();
    if (!seen.has(key)) {
      seen.add(key);
      result.push(item);
    }
  }
  return result;
}

function deduplicateNotes(items: WorkspaceNoteSummary[]): WorkspaceNoteSummary[] {
  const seen = new Set<string>();
  const result: WorkspaceNoteSummary[] = [];
  for (const item of items) {
    const key = `${item.slug}-${item.profile_id || ''}`;
    if (!seen.has(key)) {
      seen.add(key);
      result.push(item);
    }
  }
  return result;
}

export function LibraryClient({ initialAttachments, initialNotes, profileId }: LibraryClientProps) {
  const searchParams = useSearchParams();
  const router = useRouter();
  useI18n();
  const baseLibraryPath = profileId ? `/p/${encodeURIComponent(profileId)}/library` : '/library';
  const baseChatPath = profileId ? `/p/${encodeURIComponent(profileId)}/chat` : '/chat';

  const tabParam = searchParams.get('tab');
  const noteIdParam = searchParams.get('noteId');
  const typeParam = searchParams.get('type');

  const [activeTab, setActiveTab] = useState<'documents' | 'notes' | 'search'>(() => {
    if (tabParam === 'notes' || noteIdParam || typeParam) return 'notes';
    if (tabParam === 'search') return 'search';
    return 'documents';
  });

  const [selectedTypeFilter, setSelectedTypeFilter] = useState<string>(() => typeParam || 'all');

  const [attachments, setAttachments] = useState<AttachmentItem[]>(() =>
    deduplicateAttachments(initialAttachments)
  );
  const [notes, setNotes] = useState<WorkspaceNoteSummary[]>(() =>
    deduplicateNotes(initialNotes)
  );
  const [searchQuery, setSearchQuery] = useState('');

  const refreshNotes = useCallback(async () => {
    try {
      const items = await fetchNotes(profileId);
      if (Array.isArray(items)) {
        setNotes(deduplicateNotes(items));
      }
    } catch {}
  }, [profileId]);

  const refreshAttachments = useCallback(async () => {
    try {
      const items = await fetchAttachments(profileId);
      if (Array.isArray(items)) {
        setAttachments(deduplicateAttachments(items));
      }
    } catch {}
  }, [profileId]);

  useEffect(() => {
    if (process.env.NODE_ENV === 'test') return;
    if (initialNotes.length === 0) {
      refreshNotes();
    }
    if (initialAttachments.length === 0) {
      refreshAttachments();
    }
  }, [initialNotes.length, initialAttachments.length, refreshNotes, refreshAttachments]);

  // Selected note for modal viewer
  const [selectedNote, setSelectedNote] = useState<WorkspaceNoteDetail | null>(null);
  const [isLoadingNote, setIsLoadingNote] = useState(false);
  const [noteError, setNoteError] = useState<string | null>(null);
  const [copiedNote, setCopiedNote] = useState(false);

  // Note CRUD Modals
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [noteToDelete, setNoteToDelete] = useState<WorkspaceNoteSummary | WorkspaceNoteDetail | null>(null);

  // Create note form
  const [newTitle, setNewTitle] = useState('');
  const [newContent, setNewContent] = useState('');
  const [newType, setNewType] = useState('general');
  const [newTags, setNewTags] = useState('');
  const [newLinkedAppointment, setNewLinkedAppointment] = useState('');
  const [isCreatingNote, setIsCreatingNote] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Edit note form
  const [editTitle, setEditTitle] = useState('');
  const [editContent, setEditContent] = useState('');
  const [editType, setEditType] = useState('general');
  const [editTags, setEditTags] = useState('');
  const [isEditingNote, setIsEditingNote] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  // Attachment delete state
  const [attachmentToDelete, setAttachmentToDelete] = useState<AttachmentItem | null>(null);
  const [isDeletingAttachment, setIsDeletingAttachment] = useState(false);

  // Upload state
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [duplicateWarning, setDuplicateWarning] = useState<{
    file: File;
    existingName: string;
  } | null>(null);

  // Open note reader
  const handleOpenNote = useCallback(async (slug: string) => {
    setIsLoadingNote(true);
    setNoteError(null);
    setCopiedNote(false);
    try {
      const detail = await fetchNoteDetail(slug, profileId);
      setSelectedNote(detail);
    } catch (err: any) {
      setNoteError(err.message || 'Failed to load note');
    } finally {
      setIsLoadingNote(false);
    }
  }, [profileId]);

  // Handle Deep Linking
  useEffect(() => {
    if (typeParam) {
      setSelectedTypeFilter(typeParam);
      setActiveTab('notes');
    }
    if (noteIdParam) {
      setActiveTab('notes');
      handleOpenNote(noteIdParam);
    }
  }, [typeParam, noteIdParam, handleOpenNote]);

  // Live SSE Invalidation Listener
  useEffect(() => {
    const handleEntityChanged = (event: Event) => {
      const customEvent = event as CustomEvent;
      const detail = customEvent?.detail;
      if (
        !detail ||
        !detail.entity_type ||
        detail.entity_type === 'note' ||
        detail.entity_type === 'attachment' ||
        detail.entity_type === 'vitals'
      ) {
        refreshNotes();
        refreshAttachments();
      }
    };
    window.addEventListener('carefold:entity_changed', handleEntityChanged);
    window.addEventListener('carefold:entity-changed', handleEntityChanged);
    return () => {
      window.removeEventListener('carefold:entity_changed', handleEntityChanged);
      window.removeEventListener('carefold:entity-changed', handleEntityChanged);
    };
  }, [refreshNotes, refreshAttachments]);

  // Synchronize tab state with URL search param
  const handleTabChange = (tab: 'documents' | 'notes' | 'search') => {
    setActiveTab(tab);
    setSearchQuery('');
    const newParams = new URLSearchParams(searchParams.toString());
    newParams.set('tab', tab);
    router.replace(`${baseLibraryPath}?${newParams.toString()}`);
  };

  // Filtered documents
  const filteredAttachments = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    if (!q) return attachments;
    return attachments.filter((doc) => doc.filename.toLowerCase().includes(q));
  }, [attachments, searchQuery]);

  // Filtered notes
  const filteredNotes = useMemo(() => {
    let list = notes;
    if (selectedTypeFilter && selectedTypeFilter !== 'all') {
      list = list.filter((n) => (n.type || '').toLowerCase() === selectedTypeFilter.toLowerCase());
    }
    const q = searchQuery.toLowerCase().trim();
    if (!q) return list;
    return list.filter(
      (n) =>
        n.title.toLowerCase().includes(q) ||
        n.slug.toLowerCase().includes(q) ||
        (n.agent && n.agent.toLowerCase().includes(q)) ||
        (n.tags && n.tags.some((t) => t.toLowerCase().includes(q)))
    );
  }, [notes, searchQuery, selectedTypeFilter]);

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

  // Create Note Submission
  const handleCreateNoteSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim() || !newContent.trim()) {
      setCreateError('Title and content are required.');
      return;
    }
    setIsCreatingNote(true);
    setCreateError(null);
    try {
      const tagList = newTags
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean);
      const payload: CreateNoteRequest = {
        title: newTitle.trim(),
        content: newContent.trim(),
        type: newType,
        tags: tagList,
        linked_appointment_id: newLinkedAppointment.trim() || undefined,
      };
      await createNote(profileId || 'me', payload);
      await refreshNotes();
      setIsCreateModalOpen(false);
      setNewTitle('');
      setNewContent('');
      setNewType('general');
      setNewTags('');
      setNewLinkedAppointment('');
    } catch (err: any) {
      setCreateError(err.message || 'Failed to create note');
    } finally {
      setIsCreatingNote(false);
    }
  };

  // Start Note Edit
  const handleStartEditNote = () => {
    if (!selectedNote) return;
    setEditTitle(selectedNote.title || '');
    setEditContent(selectedNote.content || '');
    setEditType((selectedNote as any).type || 'general');
    setEditTags(Array.isArray((selectedNote as any).tags) ? (selectedNote as any).tags.join(', ') : '');
    setEditError(null);
    setIsEditModalOpen(true);
  };

  // Save Note Edit
  const handleSaveEditNote = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedNote) return;
    if (!editTitle.trim() || !editContent.trim()) {
      setEditError('Title and content are required.');
      return;
    }
    setIsEditingNote(true);
    setEditError(null);
    try {
      const tagList = editTags
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean);
      await updateNote(profileId || 'me', selectedNote.slug, {
        title: editTitle.trim(),
        content: editContent.trim(),
        type: editType,
        tags: tagList,
      });
      await refreshNotes();
      const updated = await fetchNoteDetail(selectedNote.slug, profileId);
      setSelectedNote(updated);
      setIsEditModalOpen(false);
    } catch (err: any) {
      setEditError(err.message || 'Failed to update note');
    } finally {
      setIsEditingNote(false);
    }
  };

  // Delete Note Execution
  const handleConfirmDeleteNote = async () => {
    const target = noteToDelete || selectedNote;
    if (!target) return;
    try {
      await deleteNote(profileId || 'me', target.slug);
      await refreshNotes();
      setIsDeleteModalOpen(false);
      setNoteToDelete(null);
      if (selectedNote && selectedNote.slug === target.slug) {
        setSelectedNote(null);
      }
    } catch (err: any) {
      alert(err.message || 'Failed to delete note');
    }
  };

  // Delete Attachment Execution
  const handleConfirmDeleteAttachment = async () => {
    if (!attachmentToDelete) return;
    setIsDeletingAttachment(true);
    try {
      await deleteAttachment(attachmentToDelete.filename);
      await refreshAttachments();
      setAttachmentToDelete(null);
    } catch (err: any) {
      alert(err.message || 'Failed to delete document');
    } finally {
      setIsDeletingAttachment(false);
    }
  };

  // Handle file selection for upload
  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

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
      await uploadAttachment(file, profileId);
      await refreshAttachments();
      setDuplicateWarning(null);
    } catch (err: any) {
      setUploadError(err.message || 'Upload failed');
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Header section */}
      <div className="space-y-2">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900 dark:text-zinc-100">
          Library
        </h1>
        <p className="text-sm text-slate-600 dark:text-zinc-400">
          Workspace documents, uploaded clinical records, and structured specialist consultation notes.
        </p>

        {/* Local Storage & Data Residency Banner */}
        <div
          data-testid="data-residency-notice"
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200/80 dark:border-emerald-800/80 text-xs text-emerald-800 dark:text-emerald-300 font-medium"
        >
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          <span>Stored on this computer in your Carefold workspace. Zero telemetry.</span>
        </div>
      </div>

      {/* Tabs and Controls */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4 border-b border-slate-200 dark:border-zinc-800 pb-4">
        {/* Navigation Tabs */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-testid="tab-documents"
            onClick={() => handleTabChange('documents')}
            className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition ${
              activeTab === 'documents'
                ? 'bg-emerald-700 text-white dark:bg-emerald-500 dark:text-[#04201a] shadow-sm'
                : 'text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-100 hover:bg-slate-100 dark:hover:bg-zinc-800'
            }`}
          >
            <FileText className="w-4 h-4" />
            <span>Documents ({attachments.length})</span>
          </button>

          <button
            type="button"
            data-testid="tab-notes"
            onClick={() => handleTabChange('notes')}
            className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition ${
              activeTab === 'notes'
                ? 'bg-emerald-700 text-white dark:bg-emerald-500 dark:text-[#04201a] shadow-sm'
                : 'text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-100 hover:bg-slate-100 dark:hover:bg-zinc-800'
            }`}
          >
            <BookOpen className="w-4 h-4" />
            <span>Consultation Notes ({notes.length})</span>
          </button>

          <button
            type="button"
            data-testid="tab-search"
            onClick={() => handleTabChange('search')}
            className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition ${
              activeTab === 'search'
                ? 'bg-emerald-700 text-white dark:bg-emerald-500 dark:text-[#04201a] shadow-sm'
                : 'text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-100 hover:bg-slate-100 dark:hover:bg-zinc-800'
            }`}
          >
            <Search className="w-4 h-4" />
            <span>Search Records</span>
          </button>
        </div>

        {/* Search, Action, and Filter Controls */}
        <div className="flex flex-wrap items-center gap-3">
          {activeTab !== 'search' && (
            <div className="relative flex-1 sm:w-64">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-zinc-500" />
              <input
                type="text"
                data-testid="library-search-input"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={
                  activeTab === 'documents'
                    ? 'Search documents by filename...'
                    : 'Search notes by title, slug, tag...'
                }
                className="w-full pl-9 pr-4 py-2 text-sm rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-slate-900 dark:text-zinc-100 placeholder:text-slate-400 dark:placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 transition"
              />
            </div>
          )}

          {activeTab === 'notes' && (
            <div className="flex items-center gap-2">
              <select
                data-testid="note-type-filter"
                value={selectedTypeFilter}
                onChange={(e) => setSelectedTypeFilter(e.target.value)}
                className="px-3 py-2 text-xs rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-slate-700 dark:text-zinc-300 font-medium focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
              >
                <option value="all">All Categories</option>
                {NOTE_CATEGORIES.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </select>

              <button
                type="button"
                data-testid="create-note-button"
                onClick={() => setIsCreateModalOpen(true)}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-[#04201a] font-medium text-xs transition"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>New Note</span>
              </button>
            </div>
          )}

          {activeTab === 'documents' && (
            <div>
              <input
                ref={fileInputRef}
                type="file"
                data-testid="file-upload-input"
                className="hidden"
                onChange={handleFileSelect}
                accept=".pdf,.txt,.md,.json,.csv,.tsv,.yaml,.yml"
              />
              <button
                type="button"
                data-testid="upload-document-button"
                disabled={isUploading}
                onClick={() => fileInputRef.current?.click()}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-700 hover:bg-emerald-800 disabled:opacity-50 text-white dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-[#04201a] font-medium text-sm transition"
              >
                {isUploading ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    <span>Uploading...</span>
                  </>
                ) : (
                  <>
                    <Upload className="w-4 h-4" />
                    <span>Upload Document</span>
                  </>
                )}
              </button>
            </div>
          )}
        </div>
      </div>

      {uploadError && (
        <div className="p-4 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-rose-800 dark:text-rose-200 text-sm flex items-center justify-between">
          <span>{uploadError}</span>
          <button type="button" onClick={() => setUploadError(null)} className="text-rose-600 hover:text-rose-800">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Duplicate Warning Dialog */}
      {duplicateWarning && (
        <div
          data-testid="duplicate-warning-modal"
          className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center p-4"
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
                className="px-4 py-2 rounded-xl text-sm font-medium bg-emerald-700 hover:bg-emerald-800 text-white dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-[#04201a] transition"
              >
                Save as new version
              </button>
            </div>
          </div>
        </div>
      )}

      {/* TAB CONTENT: SEARCH RECORDS */}
      {activeTab === 'search' && (
        <div data-testid="tab-search-content">
          <RecordSearch profileId={profileId} onSelectNote={handleOpenNote} />
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
              <div className="w-12 h-12 mx-auto rounded-2xl bg-emerald-50 dark:bg-emerald-950/40 flex items-center justify-center text-emerald-700 dark:text-emerald-400 mb-4">
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
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-[#04201a] font-medium text-sm transition"
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
                    {filteredAttachments.map((doc, idx) => {
                      const format = getFileFormat(doc.filename);
                      return (
                        <tr
                          key={doc.id || doc.path || `${doc.filename}-${idx}`}
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
                            <div className="inline-flex items-center gap-2">
                              <Link
                                href={`${baseChatPath}?attach=${encodeURIComponent(doc.filename)}`}
                                data-testid={`use-in-chat-${doc.filename}`}
                                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-50 dark:bg-emerald-950/50 hover:bg-emerald-100 dark:hover:bg-emerald-900/50 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 transition"
                              >
                                <MessageSquare className="w-3.5 h-3.5" />
                                <span>Use in chat</span>
                              </Link>
                              <button
                                type="button"
                                data-testid={`delete-attachment-${doc.filename}`}
                                onClick={() => setAttachmentToDelete(doc)}
                                className="p-1.5 rounded-lg text-slate-400 hover:text-rose-600 dark:hover:text-rose-400 hover:bg-slate-100 dark:hover:bg-zinc-800 transition"
                                title="Delete document"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>
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
                {searchQuery || selectedTypeFilter !== 'all' ? 'No matching notes found' : 'No notes saved yet'}
              </h3>
              <p className="mt-1 text-sm text-slate-600 dark:text-zinc-400 max-w-md mx-auto">
                {searchQuery || selectedTypeFilter !== 'all'
                  ? `No notes match your filter or search query.`
                  : 'When Carefold specialist agents prepare visit dossiers or answer questions, notes appear here.'}
              </p>
              <div className="mt-6 flex items-center justify-center gap-3">
                <button
                  type="button"
                  data-testid="create-first-note-button"
                  onClick={() => setIsCreateModalOpen(true)}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-[#04201a] font-medium text-sm transition"
                >
                  <Plus className="w-4 h-4" />
                  <span>Create note</span>
                </button>
                <Link
                  href={baseChatPath}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-slate-200 dark:border-zinc-800 text-slate-700 dark:text-zinc-300 font-medium text-sm hover:bg-slate-50 dark:hover:bg-zinc-800 transition"
                >
                  <MessageSquare className="w-4 h-4" />
                  <span>Start a chat</span>
                </Link>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5" data-testid="notes-grid">
              {filteredNotes.map((note, idx) => (
                <div
                  key={note.id || `${note.slug}-${note.profile_id || idx}`}
                  data-testid={`note-card-${note.slug}`}
                  onClick={() => handleOpenNote(note.slug)}
                  className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl p-5 shadow-sm hover:border-emerald-500/50 dark:hover:border-emerald-500/50 hover:shadow-md transition cursor-pointer flex flex-col justify-between gap-4 group"
                >
                  <div className="space-y-3">
                    {/* Primary Note Title */}
                    <div className="flex items-start justify-between gap-2">
                      <h2
                        data-testid={`note-title-${note.slug}`}
                        className="text-base sm:text-lg font-semibold text-slate-900 dark:text-zinc-100 group-hover:text-emerald-700 dark:group-hover:text-emerald-400 transition line-clamp-2"
                      >
                        {note.title}
                      </h2>
                    </div>

                    {/* Agent / Type Badges */}
                    <div className="flex flex-wrap items-center gap-1.5">
                      {note.agent && (
                        <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">
                          <Bot className="w-3.5 h-3.5" />
                          <span>@{note.agent}</span>
                        </div>
                      )}
                      {note.type && (
                        <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-slate-100 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300">
                          <Tag className="w-3 h-3" />
                          <span>{note.type}</span>
                        </div>
                      )}
                      {note.tags &&
                        note.tags.slice(0, 3).map((tag, tIdx) => (
                          <span
                            key={tIdx}
                            className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400"
                          >
                            #{tag}
                          </span>
                        ))}
                    </div>
                  </div>

                  {/* Metadata and action */}
                  <div className="pt-3 border-t border-slate-100 dark:border-zinc-800 flex items-center justify-between text-xs text-slate-500 dark:text-zinc-400">
                    <div className="space-y-0.5">
                      <div>{formatDate(note.created_at)}</div>
                      <div className="font-mono text-xs text-slate-500 dark:text-zinc-400">
                        {note.slug}.md • {formatFileSize(note.size_bytes)}
                      </div>
                    </div>
                    <button
                      type="button"
                      data-testid={`read-note-${note.slug}`}
                      className="px-3 py-1.5 rounded-lg bg-slate-100 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300 font-medium group-hover:bg-emerald-700 group-hover:text-white transition"
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
                      <span className="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-400 font-medium">
                        <Bot className="w-3.5 h-3.5" />
                        @{selectedNote.agent}
                      </span>
                    )}
                    <span>{formatDate(selectedNote.created_at)}</span>
                    <span className="font-mono bg-slate-100 dark:bg-zinc-800 px-2 py-0.5 rounded text-xs">
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
                      data-testid="modal-edit-note"
                      onClick={handleStartEditNote}
                      className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-700 dark:text-zinc-200 text-xs font-medium hover:bg-slate-50 dark:hover:bg-zinc-700 transition"
                      title="Edit note"
                    >
                      <Edit2 className="w-3.5 h-3.5" />
                      <span>Edit</span>
                    </button>
                    <button
                      type="button"
                      data-testid="modal-delete-note"
                      onClick={() => setIsDeleteModalOpen(true)}
                      className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-rose-200 dark:border-rose-900 bg-white dark:bg-zinc-800 text-rose-600 dark:text-rose-400 text-xs font-medium hover:bg-rose-50 dark:hover:bg-rose-950/40 transition"
                      title="Delete note"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      <span>Delete</span>
                    </button>
                    <button
                      type="button"
                      data-testid="modal-copy-note"
                      onClick={handleCopyNote}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-700 dark:text-zinc-200 text-xs font-medium hover:bg-slate-50 dark:hover:bg-zinc-700 transition"
                    >
                      {copiedNote ? (
                        <>
                          <Check className="w-3.5 h-3.5 text-emerald-700" />
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
                  <RefreshCw className="w-6 h-6 animate-spin text-emerald-700" />
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

      {/* Direct Notes Create Modal */}
      {isCreateModalOpen && (
        <div
          data-testid="create-note-modal"
          className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center p-4 sm:p-6"
        >
          <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl max-w-2xl w-full p-6 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-zinc-800">
              <h3 className="text-lg font-bold text-slate-900 dark:text-zinc-100">
                Create Consultation Note
              </h3>
              <button
                type="button"
                onClick={() => setIsCreateModalOpen(false)}
                className="text-slate-400 hover:text-slate-600 dark:hover:text-zinc-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {createError && (
              <div className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-rose-800 dark:text-rose-200 text-xs">
                {createError}
              </div>
            )}

            <form onSubmit={handleCreateNoteSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
                  Title *
                </label>
                <input
                  type="text"
                  data-testid="note-title-input"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  placeholder="e.g. Cardiology Pre-Visit Checklist"
                  className="w-full px-3 py-2 text-sm rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-slate-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
                  required
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
                    Category *
                  </label>
                  <select
                    data-testid="note-type-select"
                    value={newType}
                    onChange={(e) => setNewType(e.target.value)}
                    className="w-full px-3 py-2 text-sm rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-slate-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
                  >
                    {NOTE_CATEGORIES.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
                    Tags (comma-separated)
                  </label>
                  <input
                    type="text"
                    data-testid="note-tags-input"
                    value={newTags}
                    onChange={(e) => setNewTags(e.target.value)}
                    placeholder="e.g. cardio, blood-pressure, visit-prep"
                    className="w-full px-3 py-2 text-sm rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-slate-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
                  Linked Appointment ID (optional)
                </label>
                <input
                  type="text"
                  data-testid="note-appointment-select"
                  value={newLinkedAppointment}
                  onChange={(e) => setNewLinkedAppointment(e.target.value)}
                  placeholder="e.g. appt-uuid-or-id"
                  className="w-full px-3 py-2 text-sm rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-slate-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
                  Markdown Content *
                </label>
                <textarea
                  data-testid="note-content-input"
                  rows={8}
                  value={newContent}
                  onChange={(e) => setNewContent(e.target.value)}
                  placeholder="Enter Markdown notes, questions for your doctor, observations..."
                  className="w-full px-3 py-2 text-sm rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-slate-900 dark:text-zinc-100 font-mono focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
                  required
                />
              </div>

              <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100 dark:border-zinc-800">
                <button
                  type="button"
                  data-testid="cancel-note-button"
                  onClick={() => setIsCreateModalOpen(false)}
                  className="px-4 py-2 rounded-xl text-sm font-medium text-slate-700 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-800 transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  data-testid="save-note-button"
                  disabled={isCreatingNote}
                  className="px-4 py-2 rounded-xl text-sm font-medium bg-emerald-700 hover:bg-emerald-800 text-white dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-[#04201a] transition flex items-center gap-2"
                >
                  {isCreatingNote && <RefreshCw className="w-4 h-4 animate-spin" />}
                  <span>Save Note</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Note Edit Modal */}
      {isEditModalOpen && selectedNote && (
        <div
          data-testid="edit-note-modal"
          className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center p-4 sm:p-6"
        >
          <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl max-w-2xl w-full p-6 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-zinc-800">
              <h3 className="text-lg font-bold text-slate-900 dark:text-zinc-100">
                Edit Consultation Note
              </h3>
              <button
                type="button"
                onClick={() => setIsEditModalOpen(false)}
                className="text-slate-400 hover:text-slate-600 dark:hover:text-zinc-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {editError && (
              <div className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-rose-800 dark:text-rose-200 text-xs">
                {editError}
              </div>
            )}

            <form onSubmit={handleSaveEditNote} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
                  Title *
                </label>
                <input
                  type="text"
                  data-testid="edit-note-title-input"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  className="w-full px-3 py-2 text-sm rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-slate-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
                  required
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
                    Category *
                  </label>
                  <select
                    data-testid="edit-note-type-select"
                    value={editType}
                    onChange={(e) => setEditType(e.target.value)}
                    className="w-full px-3 py-2 text-sm rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-slate-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
                  >
                    {NOTE_CATEGORIES.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
                    Tags (comma-separated)
                  </label>
                  <input
                    type="text"
                    data-testid="edit-note-tags-input"
                    value={editTags}
                    onChange={(e) => setEditTags(e.target.value)}
                    className="w-full px-3 py-2 text-sm rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-slate-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
                  Markdown Content *
                </label>
                <textarea
                  data-testid="edit-note-content-input"
                  rows={8}
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  className="w-full px-3 py-2 text-sm rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-slate-900 dark:text-zinc-100 font-mono focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
                  required
                />
              </div>

              <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100 dark:border-zinc-800">
                <button
                  type="button"
                  data-testid="cancel-edit-note-button"
                  onClick={() => setIsEditModalOpen(false)}
                  className="px-4 py-2 rounded-xl text-sm font-medium text-slate-700 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-800 transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  data-testid="save-edit-note-button"
                  disabled={isEditingNote}
                  className="px-4 py-2 rounded-xl text-sm font-medium bg-emerald-700 hover:bg-emerald-800 text-white dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-[#04201a] transition flex items-center gap-2"
                >
                  {isEditingNote && <RefreshCw className="w-4 h-4 animate-spin" />}
                  <span>Save Changes</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Note Delete Confirmation Dialog */}
      {isDeleteModalOpen && (
        <div
          data-testid="delete-note-confirm-modal"
          className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center p-4"
        >
          <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl max-w-md w-full p-6 shadow-xl space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-rose-100 dark:bg-rose-950/50 flex items-center justify-center text-rose-600 dark:text-rose-400">
                <Trash2 className="w-5 h-5" />
              </div>
              <div>
                <h3 className="font-semibold text-slate-900 dark:text-zinc-100">
                  Delete Note
                </h3>
                <p className="text-xs text-slate-500 dark:text-zinc-400">
                  {(noteToDelete || selectedNote)?.title}
                </p>
              </div>
            </div>

            <p className="text-sm text-slate-600 dark:text-zinc-300">
              Are you sure you want to delete this note? This action will remove the note from your workspace permanently.
            </p>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                data-testid="cancel-delete-note-button"
                onClick={() => {
                  setIsDeleteModalOpen(false);
                  setNoteToDelete(null);
                }}
                className="px-4 py-2 rounded-xl text-sm font-medium text-slate-700 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-800 transition"
              >
                Cancel
              </button>
              <button
                type="button"
                data-testid="confirm-delete-note-button"
                onClick={handleConfirmDeleteNote}
                className="px-4 py-2 rounded-xl text-sm font-medium bg-rose-600 hover:bg-rose-700 text-white transition"
              >
                Delete Note
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Attachment Delete Confirmation Dialog */}
      {attachmentToDelete && (
        <div
          data-testid="delete-attachment-confirm-modal"
          className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center p-4"
        >
          <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl max-w-md w-full p-6 shadow-xl space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-rose-100 dark:bg-rose-950/50 flex items-center justify-center text-rose-600 dark:text-rose-400">
                <Trash2 className="w-5 h-5" />
              </div>
              <div>
                <h3 className="font-semibold text-slate-900 dark:text-zinc-100">
                  Delete Document
                </h3>
                <p className="text-xs text-slate-500 dark:text-zinc-400">
                  {attachmentToDelete.filename}
                </p>
              </div>
            </div>

            <p className="text-sm text-slate-600 dark:text-zinc-300">
              Are you sure you want to delete <strong>&quot;{attachmentToDelete.filename}&quot;</strong>? This will remove the file from your workspace attachments.
            </p>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                data-testid="cancel-delete-attachment-button"
                onClick={() => setAttachmentToDelete(null)}
                className="px-4 py-2 rounded-xl text-sm font-medium text-slate-700 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-800 transition"
              >
                Cancel
              </button>
              <button
                type="button"
                data-testid="confirm-delete-attachment-button"
                disabled={isDeletingAttachment}
                onClick={handleConfirmDeleteAttachment}
                className="px-4 py-2 rounded-xl text-sm font-medium bg-rose-600 hover:bg-rose-700 text-white transition flex items-center gap-2"
              >
                {isDeletingAttachment && <RefreshCw className="w-4 h-4 animate-spin" />}
                <span>Delete</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
