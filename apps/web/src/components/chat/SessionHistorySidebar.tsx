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
import {
  History,
  Plus,
  Trash2,
  Pencil,
  Check,
  X,
  MessageSquare,
  AlertTriangle
} from 'lucide-react';
import {
  listSessions,
  renameSession,
  deleteSession,
  discoverAndMigrateLegacySessions,
  type ChatSessionMeta
} from '@/lib/sessionHistory';

export interface SessionHistorySidebarProps {
  isOpen: boolean;
  onClose: () => void;
  activeThreadId?: string;
  onSelectSession: (session: ChatSessionMeta) => void;
  onNewSession: () => void;
  onDeleteSession?: (threadId: string) => void;
}

function formatRelativeTime(dateString: string): string {
  try {
    const date = new Date(dateString);
    if (isNaN(date.getTime())) return '';
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  } catch {
    return '';
  }
}

export function SessionHistorySidebar({
  isOpen,
  onClose,
  activeThreadId,
  onSelectSession,
  onNewSession,
  onDeleteSession
}: SessionHistorySidebarProps) {
  const [sessions, setSessions] = useState<ChatSessionMeta[]>([]);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState<string>('');
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);

  const editInputRef = useRef<HTMLInputElement>(null);
  const confirmDeleteBtnRef = useRef<HTMLButtonElement>(null);
  const cancelDeleteBtnRef = useRef<HTMLButtonElement>(null);
  const deleteTriggerRef = useRef<HTMLButtonElement | null>(null);

  const refreshSessions = () => {
    discoverAndMigrateLegacySessions();
    setSessions(listSessions());
  };

  const dismissDeleteDialog = () => {
    setDeletingSessionId(null);
    setTimeout(() => {
      deleteTriggerRef.current?.focus();
    }, 0);
  };

  useEffect(() => {
    refreshSessions();

    const handleSessionsChanged = () => {
      setSessions(listSessions());
    };

    window.addEventListener('carefold:sessions-changed', handleSessionsChanged);
    window.addEventListener('carefold:conversations-cleared', handleSessionsChanged);
    window.addEventListener('carefold:conversation-deleted', handleSessionsChanged);

    return () => {
      window.removeEventListener('carefold:sessions-changed', handleSessionsChanged);
      window.removeEventListener('carefold:conversations-cleared', handleSessionsChanged);
      window.removeEventListener('carefold:conversation-deleted', handleSessionsChanged);
    };
  }, []);

  useEffect(() => {
    if (editingSessionId && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingSessionId]);

  useEffect(() => {
    if (deletingSessionId && confirmDeleteBtnRef.current) {
      confirmDeleteBtnRef.current.focus();
    }
  }, [deletingSessionId]);

  // Handle escape key and accessibility focus trapping for delete alertdialog
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (deletingSessionId) {
        if (e.key === 'Escape') {
          e.preventDefault();
          dismissDeleteDialog();
        } else if (e.key === 'Tab') {
          const cancelBtn = cancelDeleteBtnRef.current;
          const confirmBtn = confirmDeleteBtnRef.current;
          if (!cancelBtn || !confirmBtn) return;

          if (e.shiftKey) {
            if (document.activeElement === cancelBtn) {
              e.preventDefault();
              confirmBtn.focus();
            }
          } else {
            if (document.activeElement === confirmBtn) {
              e.preventDefault();
              cancelBtn.focus();
            }
          }
        }
        return;
      }

      if (e.key === 'Escape') {
        if (editingSessionId) {
          setEditingSessionId(null);
        } else if (isOpen) {
          onClose();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [deletingSessionId, editingSessionId, isOpen, onClose]);

  const handleStartRename = (session: ChatSessionMeta, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingSessionId(session.id);
    setEditingTitle(session.title);
  };

  const handleSaveRename = (sessionId: string, e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (editingTitle.trim()) {
      renameSession(sessionId, editingTitle.trim());
      setEditingSessionId(null);
      refreshSessions();
    } else {
      setEditingSessionId(null);
    }
  };

  const handleCancelRename = (e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingSessionId(null);
  };

  const handleStartDelete = (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    deleteTriggerRef.current = e.currentTarget as HTMLButtonElement;
    setDeletingSessionId(sessionId);
  };

  const handleConfirmDelete = () => {
    if (!deletingSessionId) return;
    const idToDelete = deletingSessionId;
    deleteSession(idToDelete);
    dismissDeleteDialog();
    refreshSessions();
    if (onDeleteSession) {
      onDeleteSession(idToDelete);
    }
  };

  const handleCancelDelete = () => {
    dismissDeleteDialog();
  };

  if (!isOpen) return null;

  return (
    <>
      {/* Mobile Backdrop Overlay */}
      <div
        className="fixed inset-0 bg-slate-900/40 dark:bg-black/60 backdrop-blur-sm z-40 md:hidden transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Sidebar Container */}
      <aside
        data-testid="session-history-sidebar"
        role="region"
        aria-label="Conversation history"
        className="fixed md:static inset-y-0 left-0 z-50 md:z-auto w-72 sm:w-80 h-full flex flex-col bg-white dark:bg-zinc-900 border-r border-slate-200 dark:border-zinc-800 shadow-xl md:shadow-none transition-transform duration-200 ease-in-out shrink-0"
      >
        {/* Header */}
        <div className="p-3.5 border-b border-slate-200 dark:border-zinc-800 flex items-center justify-between gap-2 bg-slate-50/70 dark:bg-zinc-900/70">
          <div className="flex items-center gap-2">
            <History className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-zinc-300">
              History
            </h2>
          </div>

          <div className="flex items-center gap-1.5">
            <button
              type="button"
              data-testid="sidebar-new-session-btn"
              onClick={onNewSession}
              className="flex items-center gap-1 px-2.5 py-1 text-xs font-semibold text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/50 hover:bg-emerald-100 dark:hover:bg-emerald-900/50 border border-emerald-200 dark:border-emerald-800/60 rounded-lg transition cursor-pointer"
              title="Start a new session"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>New</span>
            </button>

            <button
              type="button"
              data-testid="close-history-sidebar-btn"
              onClick={onClose}
              className="p-1 rounded-lg text-slate-400 hover:text-slate-700 dark:text-zinc-500 dark:hover:text-zinc-300 hover:bg-slate-200/60 dark:hover:bg-zinc-800 transition cursor-pointer"
              title="Close history sidebar"
              aria-label="Close history sidebar"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Sessions List */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
          {sessions.length === 0 ? (
            <div className="h-48 flex flex-col items-center justify-center text-center px-4">
              <MessageSquare className="w-8 h-8 text-slate-300 dark:text-zinc-600 mb-2 stroke-[1.5]" />
              <p className="text-xs font-semibold text-slate-600 dark:text-zinc-400">
                No past conversations yet
              </p>
              <p className="text-[11px] text-slate-400 dark:text-zinc-500 mt-1">
                Start a consultation to see your chat history here.
              </p>
            </div>
          ) : (
            sessions.map((session) => {
              const isActive = session.id === activeThreadId;
              const isEditing = editingSessionId === session.id;

              return (
                <div
                  key={session.id}
                  className={`group relative rounded-xl border transition-all text-left flex items-stretch ${
                    isActive
                      ? 'bg-emerald-50/70 dark:bg-emerald-950/30 border-emerald-300 dark:border-emerald-800/80 shadow-sm'
                      : 'bg-white dark:bg-zinc-900 border-slate-200/80 dark:border-zinc-800/80 hover:bg-slate-50 dark:hover:bg-zinc-800/50 hover:border-slate-300 dark:hover:border-zinc-700'
                  }`}
                >
                  {isEditing ? (
                    <form
                      onSubmit={(e) => handleSaveRename(session.id, e)}
                      className="p-2 flex-1 flex items-center gap-1.5"
                    >
                      <input
                        ref={editInputRef}
                        type="text"
                        data-testid={`rename-input-${session.id}`}
                        value={editingTitle}
                        onChange={(e) => setEditingTitle(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Escape') {
                            e.preventDefault();
                            setEditingSessionId(null);
                          } else if (e.key === 'Enter') {
                            e.preventDefault();
                            handleSaveRename(session.id);
                          }
                        }}
                        className="flex-1 text-xs px-2 py-1 bg-white dark:bg-zinc-800 border border-emerald-500 rounded-lg text-slate-900 dark:text-zinc-100 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                        aria-label="Rename session"
                      />
                      <button
                        type="submit"
                        className="p-1 rounded text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 hover:bg-emerald-100 dark:hover:bg-emerald-900/50 cursor-pointer"
                        title="Save rename"
                      >
                        <Check className="w-3.5 h-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={handleCancelRename}
                        className="p-1 rounded text-slate-400 hover:text-slate-600 dark:text-zinc-500 dark:hover:text-zinc-300 hover:bg-slate-200 dark:hover:bg-zinc-800 cursor-pointer"
                        title="Cancel rename"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </form>
                  ) : (
                    <>
                      <button
                        type="button"
                        data-testid={`session-item-${session.id}`}
                        onClick={() => onSelectSession(session)}
                        aria-current={isActive ? 'true' : 'false'}
                        className="flex-1 p-2.5 flex flex-col gap-1 text-left cursor-pointer focus:outline-none focus:ring-2 focus:ring-emerald-500/20 rounded-l-xl min-w-0"
                      >
                        <div className="flex items-start justify-between gap-1.5">
                          <span
                            className={`text-xs font-semibold line-clamp-1 flex-1 ${
                              isActive
                                ? 'text-emerald-950 dark:text-emerald-200 font-bold'
                                : 'text-slate-800 dark:text-zinc-200'
                            }`}
                          >
                            {session.title}
                          </span>
                        </div>

                        {/* Meta footer: Agent + Relative time + Message count */}
                        <div className="flex items-center justify-between text-[11px] text-slate-400 dark:text-zinc-500 mt-0.5">
                          <span className="truncate max-w-[130px] font-medium text-slate-500 dark:text-zinc-400">
                            {session.agentTitle || session.agentId}
                          </span>
                          <div className="flex items-center gap-1.5 shrink-0">
                            {session.messageCount > 0 && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 dark:bg-zinc-800 font-medium">
                                {session.messageCount} msgs
                              </span>
                            )}
                            <span>{formatRelativeTime(session.updatedAt || session.createdAt)}</span>
                          </div>
                        </div>
                      </button>

                      {/* Inline Actions */}
                      <div className="flex items-center gap-0.5 pr-2 opacity-80 group-hover:opacity-100 transition-opacity shrink-0">
                        <button
                          type="button"
                          data-testid={`rename-session-${session.id}`}
                          onClick={(e) => handleStartRename(session, e)}
                          className="p-1 rounded hover:bg-slate-200 dark:hover:bg-zinc-700 text-slate-400 hover:text-slate-700 dark:text-zinc-500 dark:hover:text-zinc-200 transition cursor-pointer"
                          title="Rename session"
                          aria-label={`Rename session ${session.title}`}
                        >
                          <Pencil className="w-3 h-3" />
                        </button>
                        <button
                          type="button"
                          data-testid={`delete-session-${session.id}`}
                          onClick={(e) => handleStartDelete(session.id, e)}
                          className="p-1 rounded hover:bg-rose-100 dark:hover:bg-rose-950/50 text-slate-400 hover:text-rose-600 dark:text-zinc-500 dark:hover:text-rose-400 transition cursor-pointer"
                          title="Delete session"
                          aria-label={`Delete session ${session.title}`}
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    </>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* Delete Confirmation Alert Dialog */}
        {deletingSessionId && (
          <div
            className="fixed inset-0 z-60 bg-slate-900/50 dark:bg-black/70 flex items-center justify-center p-4 backdrop-blur-sm"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="delete-dialog-title"
            aria-describedby="delete-dialog-description"
          >
            <div className="w-full max-w-sm bg-white dark:bg-zinc-900 rounded-2xl border border-slate-200 dark:border-zinc-800 shadow-2xl p-5 animate-in fade-in zoom-in-95">
              <div className="flex items-start gap-3">
                <div className="p-2.5 rounded-xl bg-rose-50 dark:bg-rose-950/50 text-rose-600 dark:text-rose-400 shrink-0">
                  <AlertTriangle className="w-5 h-5" />
                </div>
                <div>
                  <h3
                    id="delete-dialog-title"
                    className="text-sm font-bold text-slate-900 dark:text-zinc-100"
                  >
                    Delete this conversation?
                  </h3>
                  <p
                    id="delete-dialog-description"
                    className="text-xs text-slate-600 dark:text-zinc-400 mt-1 leading-relaxed"
                  >
                    This will permanently remove the conversation and its cached messages from
                    this browser. This action cannot be undone.
                  </p>
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 mt-5">
                <button
                  ref={cancelDeleteBtnRef}
                  type="button"
                  data-testid="cancel-delete-session-btn"
                  onClick={handleCancelDelete}
                  className="px-3 py-1.5 text-xs font-semibold text-slate-700 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-800 rounded-xl transition cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  ref={confirmDeleteBtnRef}
                  type="button"
                  data-testid="confirm-delete-session-btn"
                  onClick={handleConfirmDelete}
                  className="px-3.5 py-1.5 text-xs font-semibold text-white bg-rose-600 hover:bg-rose-700 dark:bg-rose-600 dark:hover:bg-rose-500 rounded-xl transition cursor-pointer shadow-sm"
                >
                  Delete
                </button>
              </div>
            </div>
          </div>
        )}
      </aside>
    </>
  );
}
