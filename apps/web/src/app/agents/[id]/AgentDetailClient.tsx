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

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  ArrowLeft,
  MessageSquare,
  Shield,
  ShieldAlert,
  ShieldCheck,
  CheckCircle,
  Copy,
  Check,
  Cpu,
  Lock,
  Sparkles
} from 'lucide-react';
import type { AgentDetail } from '@/lib/types';
import { toAgentDetail } from '@/lib/agentDetail';
import { grantClinicalConsent } from '@/lib/clinicalConsent';
import { useClinicalConsents } from '@/lib/useClinicalConsents';
import { formatRiskClass } from '@/lib/utils';
import { ClinicalConsentDialog } from '@/components/ClinicalConsentDialog';

export interface AgentDetailClientProps {
  agent: AgentDetail;
  /** True when the server could only load a read-only preview (clinical_assist without consent). */
  consentRequired?: boolean;
}

export function AgentDetailClient({ agent: previewAgent, consentRequired = false }: AgentDetailClientProps) {
  const router = useRouter();
  const [copiedCli, setCopiedCli] = useState(false);

  // Clinical-assist consent gate (#87)
  const { consents, loaded: consentLoaded } = useClinicalConsents();
  const consentRecord = consents[previewAgent.id];
  const isGated = consentRequired && !consentRecord;
  const [fullDetail, setFullDetail] = useState<AgentDetail | null>(null);
  const [isConsentDialogOpen, setIsConsentDialogOpen] = useState(false);
  const [consentDeclined, setConsentDeclined] = useState(false);
  const [pendingNav, setPendingNav] = useState<string | null>(null);

  // With stored consent, upgrade the read-only preview to the full detail view.
  useEffect(() => {
    if (!consentRequired || !consentRecord || fullDetail) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/agents/${encodeURIComponent(previewAgent.id)}?allow_clinical=true`);
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled) setFullDetail(toAgentDetail(data));
      } catch {
        // Keep showing the preview if the backend is unreachable
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [consentRequired, consentRecord, fullDetail, previewAgent.id]);

  const agent = isGated ? previewAgent : fullDetail || previewAgent;

  const requestConsent = (nextHref: string | null) => {
    setPendingNav(nextHref);
    setIsConsentDialogOpen(true);
  };

  const handleAcceptConsent = () => {
    grantClinicalConsent(previewAgent.id);
    setIsConsentDialogOpen(false);
    setConsentDeclined(false);
    if (pendingNav) {
      router.push(pendingNav);
    }
    setPendingNav(null);
  };

  const handleDeclineConsent = () => {
    setIsConsentDialogOpen(false);
    setConsentDeclined(true);
    setPendingNav(null);
  };

  const cliCommand = `carefold run --agent ${agent.id} "Hello"`;

  const handleCopyCli = () => {
    navigator.clipboard.writeText(cliCommand);
    setCopiedCli(true);
    setTimeout(() => setCopiedCli(false), 2000);
  };

  const getRiskDisclaimer = (risk: string) => {
    switch (risk) {
      case 'wellness':
        return 'Wellness Companion: Structured for appointment preparation, habit building, and general well-being. Not a healthcare provider.';
      case 'admin':
        return 'Administrative Navigation: Clarifies health insurance terms, billing statements, and plan benefits. Does not render medical decisions or guarantee insurance reimbursement.';
      case 'education':
        return 'Educational Guide: Explains physiological and scientific concepts in plain language. Never substitutes personalized medical counsel.';
      case 'clinical_assist':
        return 'Clinical Assistant: Elevated risk classification. Subject to strict clinician oversight and local safety refusal controls.';
      default:
        return 'Local health assistant with strict local sandbox controls.';
    }
  };

  const chatHref = `/chat?agent=${agent.id}`;

  return (
    <div className="space-y-8 max-w-5xl mx-auto">
      {/* Back button */}
      <div>
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-100 transition"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>Back to Marketplace</span>
        </Link>
      </div>

      {/* Hero Header */}
      <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl p-6 sm:p-8 shadow-sm transition-colors">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60 capitalize">
                {formatRiskClass(agent.risk_class)}
              </span>
              <span className="text-xs font-mono text-slate-400 dark:text-zinc-500">v{agent.version}</span>
              <span className="text-xs text-slate-400 dark:text-zinc-500">• {agent.license}</span>
              {consentRequired && consentRecord && (
                <span
                  data-testid="clinical-consent-chip"
                  className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60"
                >
                  <ShieldCheck className="w-3 h-3" aria-hidden="true" />
                  <span>Clinical assist: consent given</span>
                </span>
              )}
            </div>
            <h1 className="text-3xl font-extrabold text-slate-900 dark:text-zinc-100 tracking-tight">{agent.title}</h1>
            <p className="mt-2 text-sm text-slate-600 dark:text-zinc-400 max-w-2xl">{getRiskDisclaimer(agent.risk_class)}</p>
          </div>

          {/* Quick CTA Actions */}
          <div className="flex flex-col sm:flex-row md:flex-col gap-3 shrink-0">
            {isGated ? (
              <button
                type="button"
                data-testid="agent-try-chat-gated"
                onClick={() => requestConsent(chatHref)}
                className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-sm shadow-sm transition active:scale-95 text-center cursor-pointer"
              >
                <MessageSquare className="w-4 h-4" />
                <span>Try in chat</span>
              </button>
            ) : (
              <Link
                href={chatHref}
                className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-sm shadow-sm transition active:scale-95 text-center"
              >
                <MessageSquare className="w-4 h-4" />
                <span>Try in chat</span>
              </Link>
            )}

            <button
              type="button"
              onClick={handleCopyCli}
              className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-slate-200 dark:border-zinc-700 hover:bg-slate-50 dark:hover:bg-zinc-800 text-slate-700 dark:text-zinc-300 text-xs font-mono transition"
            >
              {copiedCli ? <Check className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" /> : <Copy className="w-3.5 h-3.5 text-slate-400 dark:text-zinc-500" />}
              <span>{copiedCli ? 'Copied CLI Command!' : `carefold run --agent ${agent.id}`}</span>
            </button>
          </div>
        </div>
      </div>

      {/* Clinical consent required (read-only summary) */}
      {isGated && consentLoaded && (
        <div
          role="status"
          data-testid="agent-consent-required"
          className="bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-900/60 rounded-2xl p-6 text-sm text-amber-900 dark:text-amber-200 flex flex-col sm:flex-row sm:items-center gap-4"
        >
          <div className="flex items-start gap-3 flex-1">
            <ShieldAlert className="w-5 h-5 shrink-0 mt-0.5" aria-hidden="true" />
            <div className="space-y-1">
              <p className="font-semibold">
                {consentDeclined ? 'You chose not to give consent.' : 'Consent is needed before you can chat with this agent.'}
              </p>
              <p className="text-xs leading-relaxed">
                {agent.title} is a clinical assist agent. You are seeing a read-only summary. Chat stays turned off
                until you confirm you understand what it can and cannot do. You can also choose a wellness or insurance
                agent from the marketplace instead.
              </p>
            </div>
          </div>
          <button
            type="button"
            data-testid="agent-consent-review"
            onClick={() => requestConsent(null)}
            className="shrink-0 px-4 py-2 rounded-xl bg-amber-600 hover:bg-amber-700 text-white text-xs font-semibold transition cursor-pointer"
          >
            Review and give consent
          </button>
        </div>
      )}

      {/* Suggested Starters Chips (CF-S50) */}
      {agent.starters.length > 0 && (
        <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl p-6 shadow-sm transition-colors">
          <h2 className="text-sm font-bold text-slate-900 dark:text-zinc-100 uppercase tracking-wider mb-3 flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            <span>Suggested Starter Prompts</span>
          </h2>
          <div className="flex flex-wrap gap-2">
            {agent.starters.map((starter, i) => (
              <button
                key={i}
                type="button"
                onClick={() => {
                  const href = `/chat?agent=${agent.id}&prompt=${encodeURIComponent(starter)}`;
                  if (isGated) {
                    requestConsent(href);
                  } else {
                    router.push(href);
                  }
                }}
                className="text-left text-xs bg-slate-50 dark:bg-zinc-800/80 hover:bg-emerald-50 dark:hover:bg-emerald-950/40 hover:border-emerald-300 dark:hover:border-emerald-800 hover:text-emerald-900 dark:hover:text-emerald-300 border border-slate-200 dark:border-zinc-700 text-slate-700 dark:text-zinc-300 px-3.5 py-2 rounded-xl transition"
              >
                "{starter}"
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Detailed Specifications Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Persona & Intended Behavior */}
        <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl p-6 shadow-sm space-y-4 transition-colors">
          <h2 className="text-sm font-bold text-slate-900 dark:text-zinc-100 uppercase tracking-wider flex items-center gap-2">
            <Cpu className="w-4 h-4 text-slate-500 dark:text-zinc-400" />
            <span>Persona & Operating Instructions</span>
          </h2>
          <div className="text-xs text-slate-600 dark:text-zinc-300 leading-relaxed max-h-60 overflow-y-auto bg-slate-50 dark:bg-zinc-800/60 p-4 rounded-xl border border-slate-200/60 dark:border-zinc-700/60 font-sans whitespace-pre-wrap">
            {isGated ? (
              <span data-testid="agent-persona-withheld" className="italic text-slate-500 dark:text-zinc-400">
                {agent.description ? `${agent.description}\n\n` : ''}
                Full operating instructions are shown after you give consent.
              </span>
            ) : (
              agent.persona
            )}
          </div>

          <div>
            <h3 className="text-xs font-bold text-slate-700 dark:text-zinc-300 mb-2 flex items-center gap-1.5">
              <Lock className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" />
              <span>Forbidden Intent Filters (Refusal Gate)</span>
            </h3>
            <div className="flex flex-wrap gap-1.5">
              {agent.forbidden.map((f) => (
                <span
                  key={f}
                  className="bg-amber-50 dark:bg-amber-950/40 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-800/70 text-[11px] font-mono px-2 py-0.5 rounded"
                >
                  {f}
                </span>
              ))}
            </div>
          </div>
        </div>

        {/* Declared Skills & Effective Tools Allowlist */}
        <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl p-6 shadow-sm space-y-6 transition-colors">
          {/* Declared Skills */}
          <div>
            <h2 className="text-sm font-bold text-slate-900 dark:text-zinc-100 uppercase tracking-wider flex items-center gap-2 mb-3">
              <Shield className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
              <span>Declared Skills ({agent.skills.length})</span>
            </h2>
            <div className="space-y-2.5">
              {agent.skills.map((skill) => (
                <div key={skill.id} className="p-3 bg-slate-50 dark:bg-zinc-800/80 rounded-xl border border-slate-200 dark:border-zinc-700 text-xs">
                  <div className="flex items-center justify-between font-semibold text-slate-800 dark:text-zinc-200">
                    <span>{skill.name}</span>
                    {skill.version && (
                      <span className="font-mono text-[10px] text-slate-500 dark:text-zinc-400">v{skill.version}</span>
                    )}
                  </div>
                  {skill.description && <p className="text-slate-600 dark:text-zinc-400 mt-1">{skill.description}</p>}
                </div>
              ))}
            </div>
          </div>

          {/* Effective Tools Union */}
          <div>
            <h2 className="text-sm font-bold text-slate-900 dark:text-zinc-100 uppercase tracking-wider flex items-center gap-2 mb-2">
              <CheckCircle className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
              <span>Effective Tools Allowlist</span>
            </h2>
            <p className="text-xs text-slate-500 dark:text-zinc-400 mb-3">
              Union of agent and skill declarations restricted to Local Secure Sandbox:
            </p>
            <div className="space-y-2">
              {agent.effectiveTools.map((tool) => (
                <div
                  key={tool}
                  className="flex items-center justify-between p-2.5 bg-emerald-50/50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800/60 rounded-lg text-xs"
                >
                  <span className="font-mono font-bold text-emerald-900 dark:text-emerald-200">{tool}</span>
                  <span className="text-[11px] text-emerald-700 dark:text-emerald-400">Sandbox Permitted</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Clinical-assist consent dialog (#87) */}
      {consentRequired && (
        <ClinicalConsentDialog
          isOpen={isConsentDialogOpen}
          agent={previewAgent}
          onAccept={handleAcceptConsent}
          onDecline={handleDeclineConsent}
        />
      )}
    </div>
  );
}
