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

import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  Send,
  Square,
  Paperclip,
  Cpu,
  Lock,
  Plus,
  Search,
  Activity as ActivityIcon,
  ChevronDown,
  Sparkles,
  Stethoscope,
  PanelLeftClose,
  PanelLeft,
  ArrowDown
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Avatar, type MemberColorSlot } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/Sheet';
import { ChatMarkdown } from '@/components/chat/ChatMarkdown';
import { ThinkingIndicator } from '@/components/chat/ThinkingIndicator';
import { ModelSelector } from '@/components/ModelSelector';
import { DossierExportMenu } from '@/components/chat/DossierExportMenu';
import { ActivityLogDrawer } from '@/components/chat/ActivityLogDrawer';
import {
  type CarefoldUserSettings,
  DEFAULT_USER_SETTINGS,
  loadSettings,
  saveSettings,
  getProviderPrivacyState,
  getEffectiveModel,
  getApiKeyForProvider,
  getEndpointForProvider
} from '@/lib/settings';
import { hasClinicalConsent } from '@/lib/clinicalConsent';
import {
  listSessions,
  upsertSessionFromMessages,
  type ChatSessionMeta
} from '@/lib/sessionHistory';
import { getScopedStorageKey, getStorageUserId } from '@/lib/storageNamespace';
import { stripReferencePreamble, stripSuggestionLeakage } from '@/components/ChatMessageItem';
import { detectProfileAmbiguity } from '@/lib/profileMentions';
import { loadHouseholdProfiles, getHouseholdProfile } from '@/lib/familyProfiles';
import type { AgentSummary, ChatMessage } from '@/lib/types';
import type { CareProfile } from '@/app/p/[profileId]/HomeDashboardClient';

export interface ChatStudioShellProps {
  profileId?: string;
  initialProfile?: CareProfile;
  initialAgents?: AgentSummary[];
  initialThreadId?: string;
  initialPrompt?: string;
}

function formatSessionTimeAndGroup(updatedAtStr: string): { timeStr: string; group: 'this_week' | 'earlier' } {
  const date = new Date(updatedAtStr || 0);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffHours = diffMs / (1000 * 60 * 60);
  const diffDays = diffMs / (1000 * 60 * 60 * 24);

  let timeStr = 'now';
  if (isNaN(date.getTime()) || diffHours < 1) {
    timeStr = 'now';
  } else if (diffHours < 24) {
    timeStr = `${Math.floor(diffHours)}h ago`;
  } else if (diffDays < 2) {
    timeStr = 'yesterday';
  } else if (diffDays < 7) {
    timeStr = `${Math.floor(diffDays)}d ago`;
  } else {
    timeStr = date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  const group: 'this_week' | 'earlier' = (isNaN(date.getTime()) || diffDays < 7) ? 'this_week' : 'earlier';
  return { timeStr, group };
}

export function ChatStudioShell({
  profileId: profileIdProp = 'me',
  initialProfile,
  initialAgents = [],
  initialThreadId,
  initialPrompt
}: ChatStudioShellProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Active Profile Resolution
  const profile: CareProfile = useMemo(() => {
    if (initialProfile) return initialProfile;
    const household = getHouseholdProfile(profileIdProp);
    if (household) {
      return {
        id: household.id,
        name: household.name,
        relationship: household.relationship || 'Self',
        colorSlot: household.colorSlot || 1,
        role: household.role || 'Personal care'
      };
    }
    return {
      id: profileIdProp,
      name: profileIdProp === 'me' ? 'Me' : profileIdProp,
      relationship: 'Self',
      colorSlot: 1,
      role: 'Personal care'
    };
  }, [initialProfile, profileIdProp]);

  // Collapsible Left Thread Sidebar
  const [isThreadSidebarCollapsed, setIsThreadSidebarCollapsed] = useState<boolean>(false);
  const [isMobileThreadDrawerOpen, setIsMobileThreadDrawerOpen] = useState<boolean>(false);

  useEffect(() => {
    try {
      if (localStorage.getItem('carefold_chat_sidebar_collapsed') === 'true') {
        setIsThreadSidebarCollapsed(true);
      }
    } catch {}
  }, []);

  const handleToggleSidebar = () => {
    setIsThreadSidebarCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem('carefold_chat_sidebar_collapsed', String(next));
      } catch {}
      return next;
    });
  };

  // Resolved Agents
  const agents = useMemo(() => {
    if (initialAgents && initialAgents.length > 0) {
      return initialAgents.filter((a) => !a.hidden);
    }
    return [
      {
        id: 'visit-steward',
        title: 'Visit Steward',
        version: '0.4.0',
        risk_class: 'clinical_assist',
        skills: ['visit-prep'],
        effectiveTools: ['attach-read', 'workspace-note'],
        starters: ['Help me prepare for my visit'],
        description: 'Prepares questions and checklists for upcoming clinical visits.'
      },
      {
        id: 'benefits-guide',
        title: 'Benefits Guide',
        version: '0.4.0',
        risk_class: 'admin',
        skills: ['benefits-explainer'],
        effectiveTools: ['attach-read'],
        starters: ['Explain my benefits'],
        description: 'Explains health insurance coverage, copays, and deductibles.'
      },
      {
        id: 'habit-companion',
        title: 'Habit Companion',
        version: '0.4.0',
        risk_class: 'wellness',
        skills: ['habit-checkin'],
        effectiveTools: ['workspace-note'],
        starters: ['Log my daily habit'],
        description: 'Gentle check-ins for health routines and daily living.'
      }
    ] as AgentSummary[];
  }, [initialAgents]);

  const agentParam = searchParams.get('agent');
  const [selectedAgentId, setSelectedAgentId] = useState<string>(
    agentParam || agents[0]?.id || 'visit-steward'
  );
  const selectedAgent = agents.find((a) => a.id === selectedAgentId) || agents[0];

  // Settings & Residency
  const [settings, setSettings] = useState<CarefoldUserSettings>(DEFAULT_USER_SETTINGS);
  useEffect(() => {
    setSettings(loadSettings());
  }, []);
  const privacyState = getProviderPrivacyState(settings);

  // Threads State
  const [threadSearch, setThreadSearch] = useState('');
  const [activeThreadId, setActiveThreadId] = useState<string>(
    initialThreadId || `thread-${profile.id}-1`
  );
  const [sessions, setSessions] = useState<ChatSessionMeta[]>([]);

  const refreshSessions = useCallback(() => {
    setSessions(listSessions());
  }, []);

  useEffect(() => {
    refreshSessions();
    const handleChanged = () => refreshSessions();
    window.addEventListener('carefold:sessions-changed', handleChanged);
    window.addEventListener('carefold:conversations-cleared', handleChanged);
    window.addEventListener('carefold:conversation-deleted', handleChanged);
    return () => {
      window.removeEventListener('carefold:sessions-changed', handleChanged);
      window.removeEventListener('carefold:conversations-cleared', handleChanged);
      window.removeEventListener('carefold:conversation-deleted', handleChanged);
    };
  }, [refreshSessions]);

  const profileThreads = useMemo(() => {
    return sessions
      .filter((s) => {
        if ((s as any).profileId) return (s as any).profileId === profile.id;
        if (s.id.includes(profile.id)) return true;
        if (profile.id === 'me' && !s.id.includes('rosa') && !s.id.includes('leo')) return true;
        return false;
      })
      .map((s) => {
        const { timeStr, group } = formatSessionTimeAndGroup(s.updatedAt || s.createdAt);
        return {
          id: s.id,
          title: s.title,
          agentTitle: s.agentTitle || 'Visit Steward',
          timeStr,
          group
        };
      });
  }, [sessions, profile.id]);

  const filteredThreads = useMemo(() => {
    if (!threadSearch.trim()) return profileThreads;
    const q = threadSearch.toLowerCase();
    return profileThreads.filter(
      (t) => t.title.toLowerCase().includes(q) || t.agentTitle.toLowerCase().includes(q)
    );
  }, [profileThreads, threadSearch]);

  // Messages State
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    if (typeof window === 'undefined') return [];
    try {
      const initialId = initialThreadId || `thread-${profile.id}-1`;
      const msgsKey = getScopedStorageKey(`msgs_${initialId}`);
      const raw =
        window.localStorage.getItem(msgsKey) ||
        (!getStorageUserId() ? window.localStorage.getItem(`carefold_msgs_${initialId}`) : null);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) return parsed;
      }
    } catch {
      // ignore
    }
    return [];
  });

  // Reload messages when activeThreadId changes
  useEffect(() => {
    try {
      const msgsKey = getScopedStorageKey(`msgs_${activeThreadId}`);
      const raw =
        window.localStorage.getItem(msgsKey) ||
        (!getStorageUserId() ? window.localStorage.getItem(`carefold_msgs_${activeThreadId}`) : null);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          setMessages(parsed);
          return;
        }
      }
      setMessages([]);
    } catch {
      setMessages([]);
    }
  }, [activeThreadId]);

  const persistMessages = useCallback(
    (newMessages: ChatMessage[], threadIdToSave = activeThreadId) => {
      try {
        const msgsKey = getScopedStorageKey(`msgs_${threadIdToSave}`);
        localStorage.setItem(msgsKey, JSON.stringify(newMessages));
        if (!getStorageUserId()) {
          localStorage.setItem(`carefold_msgs_${threadIdToSave}`, JSON.stringify(newMessages));
        }
        upsertSessionFromMessages(
          threadIdToSave,
          selectedAgent.id,
          newMessages,
          selectedAgent.title
        );
      } catch {
        // storage quota
      }
    },
    [activeThreadId, selectedAgent]
  );

  // Composer Input & Ambiguity State
  const promptParam = searchParams.get('prompt') || initialPrompt || '';
  const [inputText, setInputText] = useState(promptParam);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isActivityOpen, setIsActivityOpen] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Client-side ambiguity hold state
  const [heldAmbiguity, setHeldAmbiguity] = useState<{
    text: string;
    targetName: string;
    targetProfileId: string;
    targetColorSlot: MemberColorSlot;
  } | null>(null);

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef<boolean>(true);
  const [isAtBottom, setIsAtBottom] = useState<boolean>(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const handleScroll = () => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    const atBottom = distanceFromBottom < 80;
    isAtBottomRef.current = atBottom;
    setIsAtBottom(atBottom);
  };

  const scrollToBottom = (force = false) => {
    const container = scrollContainerRef.current;
    if (!container) return;
    if (force || isAtBottomRef.current) {
      container.scrollTop = container.scrollHeight;
      setIsAtBottom(true);
      isAtBottomRef.current = true;
    }
  };

  useEffect(() => {
    if (isAtBottomRef.current) {
      scrollToBottom();
    }
  }, [messages, heldAmbiguity]);

  // Ambiguity check regex matching family members other than current profile
  const checkAmbiguity = (text: string) => {
    const household = loadHouseholdProfiles();
    return detectProfileAmbiguity(text, profile.id, household);
  };

  const executeChatStream = async (text: string) => {
    if (!text.trim() || isStreaming) return;

    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: text
    };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    persistMessages(updatedMessages);
    setInputText('');
    isAtBottomRef.current = true;
    scrollToBottom(true);

    const assistantMsgId = `a-${Date.now()}`;
    const assistantMsg: ChatMessage = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      isStreaming: true
    };
    setMessages([...updatedMessages, assistantMsg]);
    setIsStreaming(true);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    const effectiveModel = getEffectiveModel(settings);
    const apiKey = getApiKeyForProvider(settings, settings.provider);
    const customEndpoint = getEndpointForProvider(settings, settings.provider);
    const allowClinical = hasClinicalConsent(selectedAgent.id);

    let accumulatedAssistantText = '';
    let refusalMessage = '';

    try {
      const res = await fetch('/api/v1/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(apiKey ? { 'x-api-key': apiKey } : {}),
          ...(settings.provider ? { 'x-provider': settings.provider } : {}),
          ...(effectiveModel ? { 'x-model': effectiveModel } : {})
        },
        body: JSON.stringify({
          agentId: selectedAgent.id,
          agent_id: selectedAgent.id,
          prompt: text,
          allow_clinical: allowClinical,
          allowClinical,
          messages: updatedMessages.map((m) => ({ role: m.role, content: m.content })),
          provider: settings.provider,
          model: effectiveModel,
          apiKey,
          api_key: apiKey,
          customEndpoint,
          custom_endpoint: customEndpoint,
          threadId: activeThreadId,
          thread_id: activeThreadId
        }),
        signal: controller.signal
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.error || `HTTP error ${res.status}`);
      }

      if (!res.body) {
        setIsStreaming(false);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let currentEvent = 'token';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;

          if (trimmed.startsWith('event:')) {
            currentEvent = trimmed.slice(6).trim();
            continue;
          }

          if (trimmed.startsWith('data:')) {
            const dataStr = trimmed.slice(5).trim();
            try {
              const data = JSON.parse(dataStr);
              const eventType = data.type || currentEvent;

              if (eventType === 'token') {
                const delta = data.delta || data.token || '';
                accumulatedAssistantText += delta;
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMsgId
                      ? { ...msg, content: msg.content + delta }
                      : msg
                  )
                );
              } else if (eventType === 'refusal') {
                refusalMessage = data.message || refusalMessage;
                const isHard = Boolean(data.refused);
                const isEmergency = Boolean(
                  data.category === 'emergency_red_flag' ||
                  (data.reason && data.reason.startsWith('emergency_red_flag'))
                );
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMsgId
                      ? {
                          ...msg,
                          isRefusal: isHard,
                          isEmergency,
                          emergencyCategory: data.category || msg.emergencyCategory,
                          refusalReason: data.reason,
                          boundaryWarning: !isHard,
                          boundaryReason: data.reason,
                          content: (isHard || isEmergency) ? (data.message || msg.content) : msg.content
                        }
                      : msg
                  )
                );
              } else if (eventType === 'done') {
                const isRefusal = Boolean(data.refused);
                const hasBoundaryWarning = Boolean(data.boundaryWarning);
                const isEmergency = Boolean(
                  (data.refusalReason && data.refusalReason.startsWith('emergency_red_flag'))
                );
                setMessages((prev) =>
                  prev.map((msg) => {
                    if (msg.id !== assistantMsgId) return msg;
                    const finalEmergency = isEmergency || Boolean(msg.isEmergency);
                    return {
                      ...msg,
                      content: finalEmergency
                        ? (msg.content || stripReferencePreamble(stripSuggestionLeakage(data.fullText || '')))
                        : stripReferencePreamble(stripSuggestionLeakage(data.fullText || msg.content)),
                      isRefusal,
                      isEmergency: finalEmergency,
                      refusalReason: data.refusalReason || msg.refusalReason,
                      boundaryWarning: hasBoundaryWarning || (!isRefusal && Boolean(msg.boundaryWarning)),
                      boundaryReason: data.boundaryReason || (hasBoundaryWarning ? data.refusalReason : msg.boundaryReason),
                      isStreaming: false
                    };
                  })
                );
              }
            } catch {
              // ignore partial chunk
            }
          }
        }
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMsgId
              ? {
                  ...msg,
                  content: msg.content || 'Unable to connect to service. Please check your connection or model settings.',
                  isStreaming: false
                }
              : msg
          )
        );
      }
    } finally {
      setIsStreaming(false);
      abortControllerRef.current = null;
      setMessages((prev) => {
        const finalMsgs = prev.map((msg) =>
          msg.id === assistantMsgId ? { ...msg, isStreaming: false } : msg
        );
        persistMessages(finalMsgs, activeThreadId);
        return finalMsgs;
      });
    }
  };

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setIsStreaming(false);
  };

  const handleSendMessage = () => {
    const text = inputText.trim();
    if (!text || isStreaming) return;

    // Run client-side ambiguity check
    const ambiguity = checkAmbiguity(text);
    if (ambiguity) {
      setHeldAmbiguity({
        text,
        ...ambiguity
      });
      setInputText('');
      isAtBottomRef.current = true;
      scrollToBottom(true);
      return;
    }

    executeChatStream(text);
  };

  const handleResolveAmbiguity = (routeToTarget: boolean) => {
    if (!heldAmbiguity) return;
    const text = heldAmbiguity.text;
    const targetId = heldAmbiguity.targetProfileId;

    if (routeToTarget) {
      setHeldAmbiguity(null);
      router.push(`/p/${targetId}/chat?prompt=${encodeURIComponent(text)}`);
    } else {
      // Keep in current profile's chat
      setHeldAmbiguity(null);
      isAtBottomRef.current = true;
      executeChatStream(text);
    }
  };

  const handleNewSession = () => {
    const newId = `thread-${profile.id}-${Date.now()}`;
    setActiveThreadId(newId);
    setMessages([]);
    setHeldAmbiguity(null);
  };

  return (
    <div
      data-chat-page="true"
      className="flex flex-col flex-1 h-full min-h-0 bg-[var(--cf-surface)] overflow-hidden"
    >
      {/* Three-Zone Layout: Left Thread Column + Main Conversation Studio */}
      <div className="flex-1 flex flex-row min-h-0 h-full overflow-hidden">
        {/* Zone 1: Left Thread Column (300px desktop, hidden on mobile or when collapsed) */}
        {!isThreadSidebarCollapsed && (
          <aside
            aria-label={`${profile.name}'s consultation sessions`}
            className="hidden md:flex flex-col w-[300px] shrink-0 min-h-0 h-full border-r border-[var(--cf-border)] bg-[var(--cf-canvas)] animate-in fade-in duration-150"
          >
            {/* Thread Header */}
            <div className="flex items-center justify-between p-4 pb-3">
              <h2 className="text-sm font-bold text-[var(--cf-fg)] tracking-tight truncate">
                {profile.name}&apos;s chats
              </h2>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={`New chat about ${profile.name}`}
                  onClick={handleNewSession}
                  className="p-1 min-h-[36px] min-w-[36px]"
                >
                  <Plus className="w-4 h-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label="Collapse chats sidebar"
                  title="Collapse chats sidebar"
                  onClick={handleToggleSidebar}
                  className="p-1 min-h-[36px] min-w-[36px] text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)]"
                >
                  <PanelLeftClose className="w-4 h-4" />
                </Button>
              </div>
            </div>

          {/* Thread Search Box */}
          <div className="px-4 mb-3">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-[var(--cf-fg-subtle)] absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={threadSearch}
                onChange={(e) => setThreadSearch(e.target.value)}
                placeholder="Search sessions..."
                className="w-full h-8 pl-8 pr-3 text-xs rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg)] placeholder:text-[var(--cf-fg-subtle)] focus:outline-none focus:ring-1 focus:ring-[var(--cf-focus)] transition-all"
              />
            </div>
          </div>

          {/* Grouped Thread List */}
          <div className="flex-1 overflow-y-auto px-2 space-y-4">
            {/* This Week Group */}
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--cf-fg-subtle)] px-2.5 mb-1.5">
                This week
              </div>
              <div className="space-y-1">
                {filteredThreads
                  .filter((t) => t.group === 'this_week')
                  .map((t) => {
                    const isActive = t.id === activeThreadId;
                    return (
                      <button
                        key={t.id}
                        type="button"
                        onClick={() => setActiveThreadId(t.id)}
                        className={cn(
                          'w-full text-left p-2.5 rounded-xl transition-all min-h-[44px]',
                          isActive
                            ? 'bg-[var(--cf-surface)] border border-[var(--cf-border)] shadow-sm'
                            : 'hover:bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)]'
                        )}
                      >
                        <div className="text-xs font-semibold text-[var(--cf-fg)] truncate">
                          {t.title}
                        </div>
                        <div className="text-[11px] text-[var(--cf-fg-subtle)] flex items-center justify-between mt-0.5">
                          <span>{t.agentTitle}</span>
                          <span>{t.timeStr}</span>
                        </div>
                      </button>
                    );
                  })}
              </div>
            </div>

            {/* Earlier Group */}
            {filteredThreads.some((t) => t.group === 'earlier') && (
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--cf-fg-subtle)] px-2.5 mb-1.5">
                  Earlier
                </div>
                <div className="space-y-1">
                  {filteredThreads
                    .filter((t) => t.group === 'earlier')
                    .map((t) => {
                      const isActive = t.id === activeThreadId;
                      return (
                        <button
                          key={t.id}
                          type="button"
                          onClick={() => setActiveThreadId(t.id)}
                          className={cn(
                            'w-full text-left p-2.5 rounded-xl transition-all min-h-[44px]',
                            isActive
                              ? 'bg-[var(--cf-surface)] border border-[var(--cf-border)] shadow-sm'
                              : 'hover:bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)]'
                          )}
                        >
                          <div className="text-xs font-semibold text-[var(--cf-fg)] truncate">
                            {t.title}
                          </div>
                          <div className="text-[11px] text-[var(--cf-fg-subtle)] flex items-center justify-between mt-0.5">
                            <span>{t.agentTitle}</span>
                            <span>{t.timeStr}</span>
                          </div>
                        </button>
                      );
                    })}
                </div>
              </div>
            )}
          </div>

          {/* Privacy Footer */}
          <div className="p-3 border-t border-[var(--cf-border)] text-[11px] text-[var(--cf-fg-subtle)] flex items-center gap-2">
            <Lock className="w-3.5 h-3.5 shrink-0" />
            <span>Only {profile.name}&apos;s chats are listed. They&apos;re stored on this computer.</span>
          </div>
        </aside>
        )}

        {/* Zone 2 & 3 & 4: Main Conversation Studio */}
        <div className="flex flex-col flex-1 min-w-0 min-h-0 h-full bg-[var(--cf-surface)] overflow-hidden">
          {/* Zone 2: Slim Conversation Header (64px) */}
          <header className="h-16 shrink-0 flex items-center justify-between px-3 sm:px-6 border-b border-[var(--cf-border)] bg-[var(--cf-surface)] z-10">
            {/* Left: Specialist Guide Picker & Subtitle */}
            <div className="flex items-center gap-2 sm:gap-3 min-w-0">
              {/* Mobile: open threads drawer */}
              <Button
                variant="ghost"
                size="sm"
                aria-label="Open consultation sessions"
                title="Chat sessions"
                onClick={() => setIsMobileThreadDrawerOpen(true)}
                className="md:hidden p-1.5 min-h-[36px] min-w-[36px] text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] shrink-0"
              >
                <PanelLeft className="w-4 h-4" />
              </Button>

              {isThreadSidebarCollapsed && (
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label="Expand chats sidebar"
                  title="Expand chats sidebar"
                  onClick={handleToggleSidebar}
                  className="hidden md:flex p-1.5 min-h-[36px] min-w-[36px] mr-1 text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] shrink-0"
                >
                  <PanelLeft className="w-4 h-4" />
                </Button>
              )}
              <div className="w-9 h-9 rounded-xl bg-emerald-50 dark:bg-emerald-950/60 border border-emerald-200 dark:border-emerald-800/60 flex items-center justify-center text-emerald-700 dark:text-emerald-300 shrink-0">
                <Stethoscope className="w-4 h-4" />
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => {
                      const nextIdx = (agents.findIndex((a) => a.id === selectedAgentId) + 1) % agents.length;
                      setSelectedAgentId(agents[nextIdx].id);
                    }}
                    className="text-sm font-bold text-[var(--cf-fg)] truncate flex items-center gap-1 hover:opacity-80 transition"
                  >
                    <span>{selectedAgent.title}</span>
                    <ChevronDown className="w-3.5 h-3.5 text-[var(--cf-fg-subtle)]" />
                  </button>
                </div>
                <span className="text-[11px] text-[var(--cf-fg-subtle)] block truncate">
                  {selectedAgent.risk_class === 'clinical_assist'
                    ? 'Clinical prep · consent given'
                    : 'Everyday wellness'}
                </span>
              </div>
            </div>

            {/* Center/Right: Context Chip & Actions */}
            <div className="flex items-center gap-1.5 sm:gap-2.5 shrink-0">
              {/* Profile Context Chip - compact on mobile */}
              <div
                className={cn(
                  'hidden sm:inline-flex items-center gap-1.5 h-8 px-2.5 rounded-full text-xs font-semibold shadow-sm',
                  profile.colorSlot === 3 && 'bg-[var(--cf-member-3-bg)] text-[var(--cf-member-3-fg)]',
                  profile.colorSlot === 4 && 'bg-[var(--cf-member-4-bg)] text-[var(--cf-member-4-fg)]',
                  (!profile.colorSlot || profile.colorSlot === 1) &&
                    'bg-[var(--cf-member-1-bg)] text-[var(--cf-member-1-fg)]'
                )}
                title={`Everything in this chat is about ${profile.name}`}
              >
                <Avatar name={profile.name} size="xs" colorSlot={profile.colorSlot} />
                <span>About {profile.name.split(' ')[0]}</span>
              </div>

              {/* Model Selector */}
              <ModelSelector
                settings={settings}
                onSettingsChange={(newSettings) => {
                  setSettings(newSettings);
                  saveSettings(newSettings);
                }}
                onOpenSettings={() => router.push('/settings/model')}
                disabled={isStreaming}
              />

              {/* Export Menu */}
              <DossierExportMenu
                messages={messages}
                agent={selectedAgent as any}
                agentId={selectedAgent.id}
                threadId={activeThreadId}
                isStreaming={isStreaming}
              />

              {/* Activity Log Trigger */}
              <button
                type="button"
                aria-label="Inspect activity"
                onClick={() => setIsActivityOpen(true)}
                className="p-2 rounded-xl text-[var(--cf-fg-subtle)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface-2)] transition min-h-[44px] min-w-[44px] flex items-center justify-center"
              >
                <ActivityIcon className="w-4 h-4" />
              </button>
            </div>
          </header>

          {/* Zone 3: Central Message Stream */}
          <div className="relative flex-1 min-h-0 overflow-hidden">
            <div
              ref={scrollContainerRef}
              onScroll={handleScroll}
              role="log"
              aria-label={`Conversation with ${selectedAgent.title}`}
              aria-live="polite"
              tabIndex={0}
              className="absolute inset-0 overflow-y-auto p-4 sm:p-6 space-y-4 focus:outline-none overscroll-contain"
            >
              <div className="max-w-[760px] mx-auto space-y-4">
                {messages.length === 0 && (
                  <div className="text-center py-12 text-xs text-[var(--cf-fg-subtle)]">
                    Start a conversation about {profile.name}&apos;s care with {selectedAgent.title}.
                  </div>
                )}

                {messages.map((m) => {
                  const isUser = m.role === 'user';
                  return (
                    <div
                      key={m.id}
                      className={cn('flex flex-col', isUser ? 'items-end' : 'items-start')}
                    >
                      <div
                        className={cn(
                          'max-w-[85%] sm:max-w-[78%] rounded-2xl p-3.5 text-sm leading-relaxed',
                          isUser
                            ? 'bg-[var(--cf-surface-2)] border border-[var(--cf-border)] text-[var(--cf-fg)] rounded-tr-sm'
                            : 'bg-[var(--cf-surface)] border border-[var(--cf-border)] text-[var(--cf-fg)] rounded-tl-sm shadow-sm'
                        )}
                      >
                        {isUser ? (
                          <span>{m.content}</span>
                        ) : m.isStreaming && !m.content.trim() ? (
                          <ThinkingIndicator text={`Consulting with ${selectedAgent.title}...`} />
                        ) : (
                          <>
                            <ChatMarkdown content={m.content} />
                            {m.isStreaming && (
                              <span
                                data-testid="streaming-indicator"
                                aria-hidden="true"
                                className="inline-block w-1.5 h-3.5 ml-1 bg-emerald-600 dark:bg-emerald-400 animate-pulse align-middle rounded-sm"
                              />
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}

                {/* Ambiguity Interception Card Flow */}
                {heldAmbiguity && (
                  <div className="space-y-3">
                    {/* Held Message Bubble */}
                    <div className="flex flex-col items-end opacity-70" aria-label="Held message, not sent">
                      <div className="max-w-[85%] sm:max-w-[78%] rounded-2xl p-3.5 text-sm bg-[var(--cf-surface-2)] border border-[var(--cf-border)] text-[var(--cf-fg)] rounded-tr-sm">
                        {heldAmbiguity.text}
                      </div>
                    </div>

                    {/* Resolution Card */}
                    <div className="p-4 rounded-2xl border border-[var(--cf-info-border)] bg-[var(--cf-info-bg)] shadow-sm space-y-3">
                      <div className="flex items-start gap-3">
                        <div className="w-8 h-8 rounded-xl bg-[var(--cf-surface)] text-[var(--cf-info-fg)] flex items-center justify-center shrink-0 shadow-sm">
                          <Sparkles className="w-4 h-4" />
                        </div>
                        <div>
                          <h3 className="text-sm font-bold text-[var(--cf-fg)]">
                            This sounds like it&apos;s about {heldAmbiguity.targetName.split(' ')[0]}
                          </h3>
                          <p className="text-xs text-[var(--cf-fg-muted)] mt-1 leading-relaxed">
                            This chat is about {profile.name}, so I&apos;ve held that message — it hasn&apos;t been sent or saved. Where should it go?
                          </p>
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center gap-2.5 pt-1">
                        <Button
                          variant="primary"
                          size="sm"
                          onClick={() => handleResolveAmbiguity(true)}
                          leftIcon={
                            <Avatar
                              name={heldAmbiguity.targetName}
                              size="xs"
                              colorSlot={heldAmbiguity.targetColorSlot}
                            />
                          }
                        >
                          Start a chat for {heldAmbiguity.targetName.split(' ')[0]}
                        </Button>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => handleResolveAmbiguity(false)}
                        >
                          Keep it in {profile.name.split(' ')[0]}&apos;s chat
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setHeldAmbiguity(null)}
                        >
                          Discard
                        </Button>
                      </div>
                    </div>
                  </div>
                )}

                <div ref={messagesEndRef} />
              </div>
            </div>

            {/* Floating scroll-to-bottom indicator */}
            {!isAtBottom && (
              <button
                type="button"
                onClick={() => scrollToBottom(true)}
                aria-label="Scroll to bottom"
                className="absolute bottom-4 right-6 z-20 flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-[var(--cf-surface)] border border-[var(--cf-border-strong)] text-xs font-semibold text-[var(--cf-fg)] shadow-md hover:bg-[var(--cf-surface-2)] transition-all animate-in fade-in cursor-pointer"
              >
                <ArrowDown className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                <span>Latest messages</span>
              </button>
            )}
          </div>

          {/* Zone 4: Unified Rounded Composer (16px border-radius) */}
          <div className="p-3 sm:p-4 border-t border-[var(--cf-border)] bg-[var(--cf-surface)] shrink-0">
            <div className="max-w-[760px] mx-auto">
              <div className="rounded-2xl border border-[var(--cf-border-strong)] bg-[var(--cf-surface)] p-3 shadow-sm focus-within:ring-2 focus-within:ring-[var(--cf-focus)] transition-all">
                <textarea
                  aria-label={`Message ${selectedAgent.title}`}
                  placeholder={`Ask ${selectedAgent.title} about ${profile.name}…`}
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      handleSendMessage();
                    }
                  }}
                  className="w-full h-14 resize-none text-sm text-[var(--cf-fg)] placeholder:text-[var(--cf-fg-subtle)] bg-transparent focus:outline-none"
                />

                <div className="flex items-center justify-between pt-2 border-t border-[var(--cf-border)]">
                  <div className="flex items-center gap-2">
                    {/* Profile Context Chip */}
                    <button
                      type="button"
                      className={cn(
                        'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold min-h-[32px] transition',
                        profile.colorSlot === 3 && 'bg-[var(--cf-member-3-bg)] text-[var(--cf-member-3-fg)]',
                        profile.colorSlot === 4 && 'bg-[var(--cf-member-4-bg)] text-[var(--cf-member-4-fg)]',
                        (!profile.colorSlot || profile.colorSlot === 1) &&
                          'bg-[var(--cf-member-1-bg)] text-[var(--cf-member-1-fg)]'
                      )}
                    >
                      <Avatar name={profile.name} size="xs" colorSlot={profile.colorSlot} />
                      <span>{profile.name.split(' ')[0]}</span>
                      <ChevronDown className="w-3 h-3 ml-0.5" />
                    </button>

                    {/* Paperclip Attachment Trigger */}
                    <button
                      type="button"
                      aria-label="Attach document"
                      className="p-1.5 rounded-lg text-[var(--cf-fg-subtle)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface-2)] transition min-h-[36px] min-w-[36px] flex items-center justify-center"
                    >
                      <Paperclip className="w-4 h-4" />
                    </button>

                    {/* Data Residency Indicator */}
                    <div className="hidden sm:flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px] text-emerald-700 dark:text-emerald-400 font-medium">
                      <Cpu className="w-3.5 h-3.5" />
                      <span>{privacyState.badgeText} · llama3.2</span>
                    </div>
                  </div>

                  {/* Send / Stop Button */}
                  <Button
                    variant="primary"
                    size="sm"
                    aria-label={isStreaming ? 'Stop response' : 'Send message'}
                    onClick={isStreaming ? handleStop : handleSendMessage}
                    disabled={!inputText.trim() && !isStreaming}
                    className="w-9 h-9 p-0 rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white shrink-0"
                  >
                    {isStreaming ? (
                      <Square className="w-3.5 h-3.5 fill-current" />
                    ) : (
                      <Send className="w-3.5 h-3.5" />
                    )}
                  </Button>
                </div>
              </div>

              {/* Persistent 1-Line Quiet Safety Footer Disclaimer */}
              <p className="text-[11px] text-[var(--cf-fg-subtle)] text-center mt-2">
                Carefold helps you prepare. It doesn&apos;t diagnose. In an emergency, call 911.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Mobile Thread Drawer Sheet */}
      <Sheet open={isMobileThreadDrawerOpen} onOpenChange={setIsMobileThreadDrawerOpen} side="left">
        <SheetContent className="p-0 flex flex-col w-[300px] max-w-[85vw] bg-[var(--cf-canvas)]">
          <SheetHeader className="p-4 pb-3 border-b border-[var(--cf-border)]">
            <div className="flex items-center justify-between">
              <SheetTitle className="text-sm font-bold text-[var(--cf-fg)] tracking-tight">
                {profile.name}&apos;s chats
              </SheetTitle>
              <Button
                variant="ghost"
                size="sm"
                aria-label={`New chat about ${profile.name}`}
                onClick={() => {
                  handleNewSession();
                  setIsMobileThreadDrawerOpen(false);
                }}
                className="p-1 min-h-[36px] min-w-[36px]"
              >
                <Plus className="w-4 h-4" />
              </Button>
            </div>
          </SheetHeader>

          {/* Thread Search Box */}
          <div className="p-3">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-[var(--cf-fg-subtle)] absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={threadSearch}
                onChange={(e) => setThreadSearch(e.target.value)}
                placeholder="Search sessions..."
                className="w-full h-8 pl-8 pr-3 text-xs rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg)] placeholder:text-[var(--cf-fg-subtle)] focus:outline-none focus:ring-1 focus:ring-[var(--cf-focus)] transition-all"
              />
            </div>
          </div>

          {/* Grouped Thread List */}
          <div className="flex-1 overflow-y-auto px-2 space-y-4">
            {/* This Week Group */}
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--cf-fg-subtle)] px-2.5 mb-1.5">
                This week
              </div>
              <div className="space-y-1">
                {filteredThreads
                  .filter((t) => t.group === 'this_week')
                  .map((t) => {
                    const isActive = t.id === activeThreadId;
                    return (
                      <button
                        key={t.id}
                        type="button"
                        onClick={() => {
                          setActiveThreadId(t.id);
                          setIsMobileThreadDrawerOpen(false);
                        }}
                        className={cn(
                          'w-full text-left p-2.5 rounded-xl transition-all min-h-[44px]',
                          isActive
                            ? 'bg-[var(--cf-surface)] border border-[var(--cf-border)] shadow-sm'
                            : 'hover:bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)]'
                        )}
                      >
                        <div className="text-xs font-semibold text-[var(--cf-fg)] truncate">
                          {t.title}
                        </div>
                        <div className="text-[11px] text-[var(--cf-fg-subtle)] flex items-center justify-between mt-0.5">
                          <span>{t.agentTitle}</span>
                          <span>{t.timeStr}</span>
                        </div>
                      </button>
                    );
                  })}
              </div>
            </div>

            {/* Earlier Group */}
            {filteredThreads.some((t) => t.group === 'earlier') && (
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--cf-fg-subtle)] px-2.5 mb-1.5">
                  Earlier
                </div>
                <div className="space-y-1">
                  {filteredThreads
                    .filter((t) => t.group === 'earlier')
                    .map((t) => {
                      const isActive = t.id === activeThreadId;
                      return (
                        <button
                          key={t.id}
                          type="button"
                          onClick={() => {
                            setActiveThreadId(t.id);
                            setIsMobileThreadDrawerOpen(false);
                          }}
                          className={cn(
                            'w-full text-left p-2.5 rounded-xl transition-all min-h-[44px]',
                            isActive
                              ? 'bg-[var(--cf-surface)] border border-[var(--cf-border)] shadow-sm'
                              : 'hover:bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)]'
                          )}
                        >
                          <div className="text-xs font-semibold text-[var(--cf-fg)] truncate">
                            {t.title}
                          </div>
                          <div className="text-[11px] text-[var(--cf-fg-subtle)] flex items-center justify-between mt-0.5">
                            <span>{t.agentTitle}</span>
                            <span>{t.timeStr}</span>
                          </div>
                        </button>
                      );
                    })}
                </div>
              </div>
            )}
          </div>

          {/* Privacy Footer */}
          <div className="p-3 border-t border-[var(--cf-border)] text-[11px] text-[var(--cf-fg-subtle)] flex items-center gap-2">
            <Lock className="w-3.5 h-3.5 shrink-0" />
            <span>Only {profile.name}&apos;s chats are listed.</span>
          </div>
        </SheetContent>
      </Sheet>

      {/* Slide-over Activity Log Drawer */}
      <ActivityLogDrawer
        isOpen={isActivityOpen}
        onClose={() => setIsActivityOpen(false)}
        activeAgentId={selectedAgent.id}
      />
    </div>
  );
}
