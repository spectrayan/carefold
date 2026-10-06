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
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  Send,
  Square,
  ChevronDown,
  ArrowLeft,
  Bot,
  AlertTriangle,
  RotateCcw,
  ShieldCheck,
  ShieldAlert
} from 'lucide-react';
import type { AgentSummary } from '@/lib/types';
import { sanitizeAgentDescription } from '@/lib/utils';
import { ChatMessageItem, stripSuggestionLeakage, stripReferencePreamble, type ChatMessage } from '@/components/ChatMessageItem';
import { type ToolTraceItem } from '@/components/ToolTraceCard';
import { StartersChips } from '@/components/StartersChips';
import { SuggestedQuestionsChips } from '@/components/SuggestedQuestionsChips';
import { AttachmentUploader, type AttachedFile } from '@/components/AttachmentUploader';
import { ModelSelector } from '@/components/ModelSelector';
import { SettingsModal } from '@/components/SettingsModal';
import { ScrollToBottomButton } from '@/components/chat/ScrollToBottomButton';
import { ClinicalConsentDialog } from '@/components/ClinicalConsentDialog';
import {
  grantClinicalConsent,
  hasClinicalConsent,
  requiresClinicalConsent
} from '@/lib/clinicalConsent';
import { useClinicalConsents } from '@/lib/useClinicalConsents';
import {
  type CarefoldUserSettings,
  DEFAULT_USER_SETTINGS,
  loadSettings,
  saveSettings,
  getEffectiveModel,
  getApiKeyForProvider,
  getEndpointForProvider,
  getProviderPrivacyState
} from '@/lib/settings';

export function ChatClient({ initialAgents }: { initialAgents: AgentSummary[] }) {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Selected agent resolution (filter out hidden helper agents)
  const visibleAgents = initialAgents.filter((a) => !a.hidden);
  const agentParam = searchParams.get('agent');
  const defaultAgentId = visibleAgents.some((a) => a.id === agentParam)
    ? (agentParam as string)
    : visibleAgents[0]?.id || 'visit-steward';

  const [selectedAgentId, setSelectedAgentId] = useState<string>(defaultAgentId);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputText, setInputText] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [attachedFiles, setAttachedFiles] = useState<AttachedFile[]>([]);
  const [starters, setStarters] = useState<string[]>([]);
  const [suggestedQuestions, setSuggestedQuestions] = useState<string[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // User Settings & Model Selection State (deterministic initial state to prevent SSR hydration mismatch)
  const [settings, setSettings] = useState<CarefoldUserSettings>(DEFAULT_USER_SETTINGS);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  // Session continuity thread ID (deterministic initial state for SSR)
  const [threadId, setThreadId] = useState<string>(`thread-${defaultAgentId}`);

  // Load client-persisted user settings on mount & subscribe to settings changes
  useEffect(() => {
    setSettings(loadSettings());

    const handleSettingsChange = (e: Event) => {
      const customEvent = e as CustomEvent<CarefoldUserSettings>;
      if (customEvent.detail) {
        setSettings(customEvent.detail);
      } else {
        setSettings(loadSettings());
      }
    };

    window.addEventListener('carefold:settings-changed', handleSettingsChange);
    return () => {
      window.removeEventListener('carefold:settings-changed', handleSettingsChange);
    };
  }, []);

  const privacyState = getProviderPrivacyState(settings);

  const abortControllerRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const isAtBottomRef = useRef(true);
  const [unreadCount, setUnreadCount] = useState(0);

  const selectedAgent = initialAgents.find((a) => a.id === selectedAgentId);

  // Clinical-assist consent gate (#87). Fail-closed: clinical agents stay gated
  // until stored consent has been loaded and found for this specific agent.
  const { consents: clinicalConsents, loaded: consentLoaded } = useClinicalConsents();
  const [declinedConsentAgentId, setDeclinedConsentAgentId] = useState<string | null>(null);
  const needsClinicalConsent = requiresClinicalConsent(selectedAgent?.risk_class);
  const consentRecord = clinicalConsents[selectedAgentId];
  const isConsentGated = needsClinicalConsent && !consentRecord;
  const showConsentDialog = consentLoaded && isConsentGated && declinedConsentAgentId !== selectedAgentId;

  const handleGrantConsent = () => {
    grantClinicalConsent(selectedAgentId);
    setDeclinedConsentAgentId(null);
  };

  const handleDeclineConsent = () => {
    setDeclinedConsentAgentId(selectedAgentId);
  };

  // Sync url param
  useEffect(() => {
    if (agentParam && agentParam !== selectedAgentId && initialAgents.some((a) => a.id === agentParam)) {
      setSelectedAgentId(agentParam);
    }
  }, [agentParam, initialAgents, selectedAgentId]);

  // Thread continuity & message restoration across agent switch
  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      const savedThreadId = localStorage.getItem(`carefold_thread_${selectedAgentId}`);
      if (savedThreadId) {
        setThreadId(savedThreadId);
        const cached = localStorage.getItem(`carefold_msgs_${savedThreadId}`);
        if (cached) {
          const parsed = JSON.parse(cached);
          if (Array.isArray(parsed)) {
            setMessages(
              parsed.map((m: any) =>
                m.role === 'assistant'
                  ? { ...m, content: stripReferencePreamble(stripSuggestionLeakage(m.content || '')) }
                  : m
              )
            );
          }
        } else {
          setMessages([]);
        }
      } else {
        const newThread = `thread-${selectedAgentId}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        setThreadId(newThread);
        localStorage.setItem(`carefold_thread_${selectedAgentId}`, newThread);
        setMessages([]);
      }
    } catch {
      // Graceful localStorage error handling
    }
    setSuggestedQuestions([]);
  }, [selectedAgentId]);

  // Persist messages to localStorage on completion
  useEffect(() => {
    if (typeof window === 'undefined' || !threadId) return;
    if (!isStreaming && messages.length > 0) {
      try {
        localStorage.setItem(`carefold_msgs_${threadId}`, JSON.stringify(messages));
      } catch {
        // Storage quota protection
      }
    }
  }, [messages, isStreaming, threadId]);

  // Load starters for selected agent
  useEffect(() => {
    if (selectedAgent && selectedAgent.starters && selectedAgent.starters.length > 0) {
      setStarters(selectedAgent.starters);
    } else if (isConsentGated) {
      // Detail endpoint is consent-gated for clinical_assist agents; do not probe it.
      setStarters([]);
    } else {
      async function loadAgentStarters() {
        try {
          const allowClinical = hasClinicalConsent(selectedAgentId);
          const res = await fetch(
            `/api/agents?id=${encodeURIComponent(selectedAgentId)}&allow_clinical=${allowClinical}`
          );
          if (res.ok) {
            const data = await res.json();
            setStarters(data.starters || []);
          } else {
            setStarters([]);
          }
        } catch {
          setStarters([]);
        }
      }
      loadAgentStarters();
    }
  }, [selectedAgentId, selectedAgent, isConsentGated]);

  // Handle incoming ?prompt= param (deferred until clinical consent is resolved)
  const promptHandledRef = useRef(false);
  useEffect(() => {
    const promptParam = searchParams.get('prompt');
    if (!promptParam || promptHandledRef.current || messages.length !== 0) return;
    if (!consentLoaded || isConsentGated) return;
    promptHandledRef.current = true;
    sendMessage(promptParam);
  }, [searchParams, messages.length, consentLoaded, isConsentGated]);

  // Dynamic textarea height calculation helper (min 42px, max 160px)
  const adjustTextareaHeight = (el: HTMLTextAreaElement | null) => {
    if (!el) return;
    if (!el.value) {
      el.style.height = '42px';
      el.style.overflowY = 'hidden';
      return;
    }
    el.style.height = 'auto';
    const scrollHeight = el.scrollHeight;
    const nextHeight = Math.min(Math.max(scrollHeight, 42), 160);
    el.style.height = `${nextHeight}px`;
    el.style.overflowY = scrollHeight > 160 ? 'auto' : 'hidden';
  };

  useEffect(() => {
    if (textareaRef.current) {
      adjustTextareaHeight(textareaRef.current);
    }
  }, [inputText]);

  // Scroll position detection
  const handleScroll = () => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    const atBottom = distanceFromBottom < 60;
    isAtBottomRef.current = atBottom;
    setIsAtBottom(atBottom);
    if (atBottom) {
      setUnreadCount(0);
    }
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    setIsAtBottom(true);
    isAtBottomRef.current = true;
    setUnreadCount(0);
  };

  // Auto scroll to bottom only when user is already at the bottom
  useEffect(() => {
    if (isAtBottomRef.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isStreaming, suggestedQuestions]);

  const handleAgentChange = (newAgentId: string) => {
    setSelectedAgentId(newAgentId);
    router.replace(`/chat?agent=${encodeURIComponent(newAgentId)}`);
  };

  const handleSettingsChange = (newSettings: CarefoldUserSettings) => {
    setSettings(newSettings);
    saveSettings(newSettings);
  };

  const handleNewSession = () => {
    stopGeneration();
    const newThread = `thread-${selectedAgentId}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setThreadId(newThread);
    if (typeof window !== 'undefined') {
      try {
        localStorage.setItem(`carefold_thread_${selectedAgentId}`, newThread);
      } catch {}
    }
    setMessages([]);
    setSuggestedQuestions([]);
    setErrorMessage(null);
    setInputText('');
    setIsAtBottom(true);
    isAtBottomRef.current = true;
    setUnreadCount(0);
    if (textareaRef.current) {
      textareaRef.current.style.height = '42px';
      textareaRef.current.style.overflowY = 'hidden';
    }
  };

  const stopGeneration = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setIsStreaming(false);
      setMessages((prev) =>
        prev.map((msg, idx) =>
          idx === prev.length - 1 && msg.role === 'assistant'
            ? { ...msg, isStreaming: false }
            : msg
        )
      );
    }
  };

  /**
   * Core SSE chat streaming pipeline reused by sendMessage and handleRegenerate.
   */
  const executeChatStream = async (
    promptText: string,
    attachments: string[],
    historyMessages: ChatMessage[],
    assistantMessageId: string
  ) => {
    setErrorMessage(null);
    setSuggestedQuestions([]);
    setIsStreaming(true);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    const effectiveModel = getEffectiveModel(settings);
    const apiKey = getApiKeyForProvider(settings, settings.provider);
    const customEndpoint =
      settings.provider === 'ollama' &&
      (!settings.endpoints?.ollamaUrl ||
        settings.endpoints.ollamaUrl.trim() === 'http://127.0.0.1:11434' ||
        settings.endpoints.ollamaUrl.trim() === 'http://localhost:11434')
        ? undefined
        : getEndpointForProvider(settings, settings.provider);

    // Read consent from storage at send time (never hard-coded; see #87)
    const allowClinical = hasClinicalConsent(selectedAgentId);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(apiKey ? { 'x-api-key': apiKey } : {}),
          ...(settings.provider ? { 'x-provider': settings.provider } : {}),
          ...(effectiveModel ? { 'x-model': effectiveModel } : {})
        },
        body: JSON.stringify({
          agentId: selectedAgentId,
          agent_id: selectedAgentId,
          prompt: promptText,
          attachments,
          allow_clinical: allowClinical,
          allowClinical,
          messages: historyMessages.map((m) => ({ role: m.role, content: m.content })),
          provider: settings.provider,
          model: effectiveModel,
          apiKey,
          api_key: apiKey,
          customEndpoint,
          custom_endpoint: customEndpoint,
          threadId,
          thread_id: threadId
        }),
        signal: controller.signal
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.error || `HTTP error ${res.status}`);
      }

      if (!res.body) throw new Error('Response body is null');

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
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMessageId
                      ? { ...msg, content: msg.content + delta }
                      : msg
                  )
                );
                if (!isAtBottomRef.current) {
                  setUnreadCount((prev) => prev + 1);
                }
              } else if (eventType === 'tool_start') {
                const newTrace: ToolTraceItem = {
                  id: `trace-${Date.now()}-${data.tool}`,
                  tool: data.tool,
                  status: 'running',
                  input: data.params || data.input || {},
                  params: data.params || data.input || {},
                  startTime: Date.now()
                };
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMessageId
                      ? {
                          ...msg,
                          toolTraces: [...(msg.toolTraces || []), newTrace]
                        }
                      : msg
                  )
                );
              } else if (eventType === 'tool_end') {
                setMessages((prev) =>
                  prev.map((msg) => {
                    if (msg.id !== assistantMessageId) return msg;
                    const traces = (msg.toolTraces || []).map((t) => {
                      if (t.tool === data.tool && t.status === 'running') {
                        return {
                          ...t,
                          status: (data.allowed === false ? 'denied' : data.status || 'completed') as any,
                          duration_ms: data.duration_ms,
                          result: data.result || data.output,
                          output: data.result || data.output,
                          allowed: data.allowed,
                          reason: data.reason
                        };
                      }
                      return t;
                    });
                    return { ...msg, toolTraces: traces };
                  })
                );
              } else if (eventType === 'refusal') {
                const isHard = !data.reason || !data.reason.includes('diagnose');
                const isEmergency = Boolean(data.reason && data.reason.startsWith('emergency_red_flag'));
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantMessageId
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
              } else if (eventType === 'suggestions') {
                const list = data.suggestions || data.followUpSuggestions;
                if (Array.isArray(list) && list.length > 0) {
                  setSuggestedQuestions(list);
                }
              } else if (eventType === 'done') {
                const list = data.suggestions || data.followUpSuggestions;
                if (Array.isArray(list) && list.length > 0) {
                  setSuggestedQuestions(list);
                }
                const isRefusal = Boolean(data.refused);
                const hasBoundaryWarning = Boolean(data.boundaryWarning);
                const isEmergency = Boolean(
                  (data.refusalReason && data.refusalReason.startsWith('emergency_red_flag'))
                );
                setMessages((prev) =>
                  prev.map((msg) => {
                    if (msg.id !== assistantMessageId) return msg;
                    const messageIsEmergency = isEmergency || Boolean(msg.isEmergency);
                    return {
                      ...msg,
                      content: messageIsEmergency
                        ? (msg.content || stripReferencePreamble(stripSuggestionLeakage(data.fullText || '')))
                        : stripReferencePreamble(stripSuggestionLeakage(data.fullText || msg.content)),
                      isRefusal: isRefusal,
                      isEmergency: messageIsEmergency,
                      emergencyCategory: msg.emergencyCategory,
                      refusalReason: data.refusalReason || msg.refusalReason,
                      boundaryWarning: hasBoundaryWarning || (!isRefusal && Boolean(msg.boundaryWarning)),
                      boundaryReason: data.boundaryReason || (hasBoundaryWarning ? data.refusalReason : msg.boundaryReason),
                      isStreaming: false
                    };
                  })
                );
              } else if (eventType === 'error') {
                setErrorMessage(data.message || 'An error occurred during agent execution.');
              }
            } catch {
              // Ignore partial JSON chunks
            }
          }
        }
      }
    } catch (err: any) {
      if (err.name === 'AbortError') {
        // Stream aborted by user
      } else {
        setErrorMessage(
          err.message && (err.message.includes('fetch') || err.message.includes('ECONNREFUSED'))
            ? 'Ollama is unreachable. Please verify Ollama is running on http://127.0.0.1:11434.'
            : err.message || 'Execution error.'
        );
      }
    } finally {
      setIsStreaming(false);
      abortControllerRef.current = null;
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMessageId
            ? { ...msg, isStreaming: false }
            : msg
        )
      );
    }
  };

  const sendMessage = async (promptToSend?: string) => {
    const text = (promptToSend !== undefined ? promptToSend : inputText).trim();
    if (!text && attachedFiles.length === 0) return;
    if (isStreaming) return;
    if (isConsentGated) {
      // Re-open the consent dialog rather than sending without consent
      setDeclinedConsentAgentId(null);
      return;
    }

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
      attachments: attachedFiles.map((a) => a.path),
      timestamp: new Date().toISOString()
    };

    const currentFiles = [...attachedFiles];
    setAttachedFiles([]);
    setInputText('');

    if (textareaRef.current) {
      textareaRef.current.style.height = '42px';
      textareaRef.current.style.overflowY = 'hidden';
    }

    setIsAtBottom(true);
    isAtBottomRef.current = true;
    setUnreadCount(0);
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });

    const assistantMessageId = `assistant-${Date.now() + 1}`;
    const initialAssistantMessage: ChatMessage = {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
      isStreaming: true,
      toolTraces: []
    };

    const nextMessages = [...messages, userMessage, initialAssistantMessage];
    setMessages(nextMessages);

    await executeChatStream(
      text,
      currentFiles.map((a) => a.path),
      messages,
      assistantMessageId
    );
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      if (
        e.nativeEvent?.isComposing ||
        (e.nativeEvent as any)?.nativeEvent?.isComposing ||
        (e as any).isComposing ||
        e.keyCode === 229
      ) {
        return;
      }
      e.preventDefault();
      if (!isStreaming && (inputText.trim() || attachedFiles.length > 0)) {
        sendMessage();
      }
    }
  };

  const handleRerun = (prompt: string) => {
    if (isStreaming) return;
    sendMessage(prompt);
  };

  const handleRegenerate = async (assistantMessageId: string) => {
    if (isStreaming) return;
    if (isConsentGated) {
      setDeclinedConsentAgentId(null);
      return;
    }

    const idx = messages.findIndex((m) => m.id === assistantMessageId);
    if (idx === -1) return;

    // Locate preceding user turn
    let userIdx = -1;
    let userPrompt = '';
    let userAttachments: string[] = [];
    for (let i = idx - 1; i >= 0; i--) {
      if (messages[i].role === 'user') {
        userIdx = i;
        userPrompt = messages[i].content;
        userAttachments = messages[i].attachments || [];
        break;
      }
    }

    if (userIdx === -1 || !userPrompt) return;

    const historyBeforeUser = messages.slice(0, userIdx);
    const userMsg = messages[userIdx];

    const newAssistantId = `assistant-${Date.now()}`;
    const newAssistantMsg: ChatMessage = {
      id: newAssistantId,
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
      isStreaming: true,
      toolTraces: []
    };

    // Rollback message history to the targeted user prompt + new blank assistant response
    setMessages([...historyBeforeUser, userMsg, newAssistantMsg]);

    await executeChatStream(
      userPrompt,
      userAttachments,
      historyBeforeUser,
      newAssistantId
    );
  };

  const handleSelectSuggestion = (question: string) => {
    setSuggestedQuestions([]);
    sendMessage(question);
  };

  return (
    <div className="flex flex-col h-[calc(100dvh-120px)] sm:h-[calc(100dvh-140px)] bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl shadow-sm overflow-hidden transition-colors">
      {/* Chat Header Bar */}
      <div className="px-4 py-3 border-b border-slate-200 dark:border-zinc-800 bg-slate-50 dark:bg-zinc-900/90 flex items-center justify-between gap-4 transition-colors">
        {/* Left Section: Back Link & Agent Selector */}
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="p-1.5 rounded-lg hover:bg-slate-200 dark:hover:bg-zinc-800 text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-100 transition cursor-pointer"
            title="Back to Marketplace"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>

          {/* Agent Selector Dropdown */}
          <div className="relative">
            <select
              aria-label="Select Agent"
              value={selectedAgentId}
              onChange={(e) => handleAgentChange(e.target.value)}
              className="appearance-none bg-white dark:bg-zinc-800 border border-slate-300 dark:border-zinc-700 rounded-xl pl-3 pr-8 py-1.5 text-xs font-bold text-slate-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 cursor-pointer shadow-sm"
            >
              {visibleAgents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.title} ({a.risk_class})
                </option>
              ))}
            </select>
            <ChevronDown className="w-3.5 h-3.5 text-slate-400 dark:text-zinc-500 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
          </div>

          {needsClinicalConsent && consentRecord && (
            <span
              data-testid="clinical-consent-chip"
              title={`Clinical assist consent given ${new Date(consentRecord.grantedAt).toLocaleString()}. Withdraw it in Settings.`}
              className="inline-flex items-center gap-1 shrink-0 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60"
            >
              <ShieldCheck className="w-3 h-3" aria-hidden="true" />
              <span className="sr-only sm:not-sr-only">Clinical assist: consent given</span>
            </span>
          )}

          <span className="hidden sm:inline text-xs text-slate-400 dark:text-zinc-500">•</span>
          <span className="hidden sm:inline text-xs font-medium text-slate-600 dark:text-zinc-400 truncate max-w-sm">
            {sanitizeAgentDescription(selectedAgent?.description) || 'Task-scoped health assistant'}
          </span>
        </div>

        {/* Right Section: ModelSelector & New Session */}
        <div className="flex items-center gap-2">
          {/* Dynamic Model & Provider Selector */}
          <ModelSelector
            settings={settings}
            onSettingsChange={handleSettingsChange}
            onOpenSettings={() => setIsSettingsOpen(true)}
            disabled={isStreaming}
          />

          {/* Clear thread / New session */}
          <button
            type="button"
            data-testid="new-session-btn"
            onClick={handleNewSession}
            className="flex items-center gap-1.5 text-xs font-medium text-slate-500 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-100 px-2.5 py-1.5 rounded-xl hover:bg-slate-200 dark:hover:bg-zinc-800 transition cursor-pointer"
            title="Start a new chat session"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span className="hidden md:inline">New Session</span>
          </button>
        </div>
      </div>

      {/* Message History Area */}
      <div className="relative flex-1 min-h-0">
        <div
          ref={scrollContainerRef}
          onScroll={handleScroll}
          className="h-full overflow-y-auto overflow-x-hidden p-4 sm:p-6 space-y-4"
        >
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center max-w-lg mx-auto py-12">
              <div className="w-14 h-14 rounded-2xl bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60 flex items-center justify-center mb-4">
                <Bot className="w-7 h-7" />
              </div>
              <h2 className="text-lg font-bold text-slate-900 dark:text-white">
                Chat with {selectedAgent?.title || 'Carefold Assistant'}
              </h2>
              <p data-testid="chat-empty-state-privacy" className="text-xs sm:text-sm text-slate-500 dark:text-zinc-400 mt-1 max-w-md">
                Ask questions or drop relevant documents into the chat. {privacyState.emptyStateText}
              </p>

              {/* Quick Starter Chips */}
              {starters.length > 0 && (
                <div className="mt-6 w-full text-left">
                  <StartersChips
                    starters={starters}
                    onSelectStarter={(prompt) => sendMessage(prompt)}
                  />
                </div>
              )}
            </div>
          ) : (
            <>
              {messages.map((msg) => (
                <ChatMessageItem
                  key={msg.id}
                  message={msg}
                  onRerun={handleRerun}
                  onRegenerate={handleRegenerate}
                  disabled={isStreaming}
                />
              ))}

              {/* Interactive Contextual Follow-up Suggestions */}
              {!isStreaming && suggestedQuestions.length > 0 && (
                <div className="flex justify-start my-2 max-w-[95%] md:max-w-[85%]">
                  <SuggestedQuestionsChips
                    suggestions={suggestedQuestions}
                    onSelectSuggestion={handleSelectSuggestion}
                    disabled={isStreaming}
                  />
                </div>
              )}
            </>
          )}

          {/* Error Notification */}
          {errorMessage && (
            <div className="p-4 bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/60 rounded-xl text-xs text-rose-800 dark:text-rose-200 flex items-center gap-2 max-w-xl mx-auto my-2">
              <AlertTriangle className="w-4 h-4 text-rose-600 dark:text-rose-400 shrink-0" />
              <span>{errorMessage}</span>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Floating Auto-Scroll Button */}
        <ScrollToBottomButton
          visible={!isAtBottom}
          unreadCount={unreadCount}
          onClick={scrollToBottom}
        />
      </div>

      {/* Composer Input Area */}
      <div className="p-4 border-t border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 space-y-3 transition-colors">
        {/* Clinical consent gate notice (shown after the dialog is declined or closed) */}
        {consentLoaded && isConsentGated && !showConsentDialog && (
          <div
            role="status"
            data-testid="clinical-consent-gate"
            className="p-3 rounded-xl bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-900/60 text-xs text-amber-900 dark:text-amber-200 flex flex-col sm:flex-row sm:items-center gap-3"
          >
            <div className="flex items-start gap-2 flex-1">
              <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
              <span>
                Chat with {selectedAgent?.title || 'this agent'} is turned off until you give consent. It is a clinical
                assist agent, so Carefold first asks you to confirm what it can and cannot do. You can still choose a
                wellness or insurance agent from the menu above.
              </span>
            </div>
            <button
              type="button"
              data-testid="clinical-consent-review"
              onClick={() => setDeclinedConsentAgentId(null)}
              className="shrink-0 px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold transition cursor-pointer"
            >
              Review and give consent
            </button>
          </div>
        )}

        {/* Attachment uploader component */}
        <AttachmentUploader
          attachedFiles={attachedFiles}
          onAttach={(file) => setAttachedFiles((prev) => [...prev, file])}
          onRemove={(filename) =>
            setAttachedFiles((prev) => prev.filter((f) => f.filename !== filename))
          }
          disabled={isStreaming || isConsentGated}
        />

        {/* Message input form */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            sendMessage();
          }}
          className="flex items-end gap-2"
        >
          <textarea
            ref={textareaRef}
            rows={1}
            value={inputText}
            onChange={(e) => {
              setInputText(e.target.value);
              adjustTextareaHeight(e.target);
            }}
            onKeyDown={handleKeyDown}
            placeholder={
              isConsentGated
                ? `Give consent to chat with ${selectedAgent?.title || 'this agent'}`
                : `Message ${selectedAgent?.title || 'agent'}...`
            }
            disabled={isStreaming || isConsentGated}
            data-testid="chat-composer-textarea"
            className="flex-1 px-4 py-2.5 rounded-xl border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800 focus:bg-white dark:focus:bg-zinc-700 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 text-base sm:text-sm text-slate-900 dark:text-zinc-100 placeholder:text-slate-400 dark:placeholder:text-zinc-500 transition-colors disabled:opacity-50 resize-none min-h-[42px] max-h-[160px] leading-normal"
          />

          {isStreaming ? (
            <button
              type="button"
              data-testid="chat-stop-btn"
              onClick={stopGeneration}
              className="min-w-[42px] min-h-[42px] p-2.5 rounded-xl bg-slate-900 dark:bg-zinc-700 text-white hover:bg-slate-800 dark:hover:bg-zinc-600 transition shadow-sm cursor-pointer flex items-center justify-center shrink-0"
              title="Stop Generation"
            >
              <Square className="w-4 h-4 fill-current" />
            </button>
          ) : (
            <button
              type="submit"
              data-testid="chat-submit-btn"
              disabled={(!inputText.trim() && attachedFiles.length === 0) || isStreaming || isConsentGated}
              className="min-w-[42px] min-h-[42px] p-2.5 rounded-xl bg-emerald-600 text-white hover:bg-emerald-700 transition disabled:opacity-40 disabled:cursor-not-allowed shadow-sm cursor-pointer flex items-center justify-center shrink-0"
              title="Send Prompt"
            >
              <Send className="w-4 h-4" />
            </button>
          )}
        </form>
      </div>

      {/* API Key & Provider Settings Modal */}
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        initialSettings={settings}
        onSave={handleSettingsChange}
        agents={visibleAgents}
      />

      {/* Clinical-assist consent dialog (#87) */}
      {selectedAgent && (
        <ClinicalConsentDialog
          isOpen={showConsentDialog}
          agent={selectedAgent}
          onAccept={handleGrantConsent}
          onDecline={handleDeclineConsent}
        />
      )}
    </div>
  );
}
