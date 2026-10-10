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

import React, { useState, useEffect } from 'react';
import { X, Bot, Check } from 'lucide-react';
import type { AgentDetailResponse, SkillSummary, RiskClass } from '@/types/api';

interface AgentFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (agent: AgentDetailResponse) => void;
  availableSkills: SkillSummary[];
  initialAgent?: AgentDetailResponse;
}

const AVAILABLE_TOOLS = [
  { id: 'attach-read', label: 'attach-read', desc: 'Read uploaded documents & lab results' },
  { id: 'workspace-note', label: 'workspace-note', desc: 'Save prep notes & checklists' },
  { id: 'skill-docs', label: 'skill-docs', desc: 'Access clinical reference guidelines' },
];

export function AgentFormModal({
  isOpen,
  onClose,
  onSuccess,
  availableSkills,
  initialAgent,
}: AgentFormModalProps) {
  const isEditing = Boolean(initialAgent);

  const [id, setId] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [domain, setDomain] = useState('clinical');
  const [category, setCategory] = useState('');
  const [riskClass, setRiskClass] = useState<RiskClass>('clinical_assist');
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [selectedTools, setSelectedTools] = useState<string[]>(['attach-read', 'workspace-note', 'skill-docs']);
  const [personaRole, setPersonaRole] = useState('');
  const [personaInstructions, setPersonaInstructions] = useState('');
  const [startersText, setStartersText] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialAgent) {
      setId(initialAgent.id);
      setTitle(initialAgent.title);
      setDescription(initialAgent.description || '');
      setDomain(String(initialAgent.domain || 'clinical'));
      setCategory(initialAgent.category || '');
      setRiskClass((initialAgent.risk_class as RiskClass) || 'clinical_assist');
      setSelectedSkills(initialAgent.skills || []);
      setSelectedTools(initialAgent.tools || ['attach-read', 'workspace-note', 'skill-docs']);
      setPersonaRole(initialAgent.persona?.role || initialAgent.title);
      setPersonaInstructions(initialAgent.persona?.instructions || '');
      setStartersText((initialAgent.starters || []).join('\n'));
    } else {
      setId('');
      setTitle('');
      setDescription('');
      setDomain('clinical');
      setCategory('');
      setRiskClass('clinical_assist');
      setSelectedSkills([]);
      setSelectedTools(['attach-read', 'workspace-note', 'skill-docs']);
      setPersonaRole('Specialist Clinical Steward');
      setPersonaInstructions(
        'You are a specialized healthcare assistant helping the patient organize questions, understand their diagnosis context, and prepare for upcoming consultations.\n\n' +
        'Strictly follow safety boundaries: never prescribe, never alter doses, and advise calling 911 in emergencies.'
      );
      setStartersText('How should I prepare for my upcoming consultation?\nWhat questions should I ask my doctor?\nHelp me organize my medical records and test results.');
    }
    setError(null);
  }, [initialAgent, isOpen]);

  if (!isOpen) return null;

  const toggleSkill = (skillId: string) => {
    setSelectedSkills((prev) =>
      prev.includes(skillId) ? prev.filter((s) => s !== skillId) : [...prev, skillId]
    );
  };

  const toggleTool = (toolId: string) => {
    setSelectedTools((prev) =>
      prev.includes(toolId) ? prev.filter((t) => t !== toolId) : [...prev, toolId]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    const starters = startersText
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);

    const payload = {
      title: title.trim(),
      description: description.trim(),
      domain,
      category: category.trim(),
      risk_class: riskClass,
      skills: selectedSkills,
      tools: selectedTools,
      persona: {
        role: personaRole.trim() || title.trim(),
        instructions: personaInstructions,
      },
      starters,
    };

    try {
      const endpoint = isEditing ? `/api/v1/agents/${encodeURIComponent(initialAgent!.id)}` : '/api/v1/agents';
      const method = isEditing ? 'PUT' : 'POST';
      const body = isEditing ? JSON.stringify(payload) : JSON.stringify({ id: id.trim(), ...payload });

      const res = await fetch(endpoint, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || err.error || `HTTP ${res.status} failed`);
      }

      const result: AgentDetailResponse = await res.json();
      onSuccess(result);
      onClose();
    } catch (err: any) {
      setError(err.message || 'Failed to save agent');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm">
      <div className="w-full max-w-2xl max-h-[90vh] flex flex-col bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-3xl shadow-xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-slate-100 dark:border-zinc-800">
          <div className="flex items-center gap-2.5">
            <Bot className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            <h3 className="text-sm font-bold text-slate-900 dark:text-zinc-100">
              {isEditing ? `Edit Agent: ${initialAgent?.title}` : 'Create Specialist Agent'}
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-zinc-200"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-6 space-y-4">
          {error && (
            <div className="p-3 text-xs rounded-xl bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900">
              {error}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {!isEditing && (
              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
                  Agent ID / Slug
                </label>
                <input
                  type="text"
                  required
                  value={id}
                  onChange={(e) => {
                    const slug = e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, '-');
                    setId(slug);
                  }}
                  placeholder="e.g. endocrinology-guide"
                  className="w-full px-3 py-2 text-xs rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 font-mono focus:border-emerald-700 dark:focus:border-emerald-400"
                />
              </div>
            )}

            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
                Display Title
              </label>
              <input
                type="text"
                required
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Endocrinology Guide"
                className="w-full px-3 py-2 text-xs rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:border-emerald-700 dark:focus:border-emerald-400"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
                Domain
              </label>
              <select
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                className="w-full px-3 py-2 text-xs rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:border-emerald-700 dark:focus:border-emerald-400"
              >
                <option value="clinical">Clinical</option>
                <option value="navigation">Navigation</option>
                <option value="wellness">Wellness</option>
                <option value="education">Education</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
                Risk Class
              </label>
              <select
                value={riskClass}
                onChange={(e) => setRiskClass(e.target.value as RiskClass)}
                className="w-full px-3 py-2 text-xs rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:border-emerald-700 dark:focus:border-emerald-400"
              >
                <option value="clinical_assist">Clinical Assist (requires consent)</option>
                <option value="admin">Admin (Formulary / Insurance)</option>
                <option value="wellness">Wellness</option>
                <option value="education">Education</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
                Category
              </label>
              <input
                type="text"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                placeholder="e.g. endocrinology or insurance"
                className="w-full px-3 py-2 text-xs rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:border-emerald-700 dark:focus:border-emerald-400"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
              Short Description
            </label>
            <input
              type="text"
              required
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g. Assists patients with thyroid, diabetes, and metabolic visit prep."
              className="w-full px-3 py-2 text-xs rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:border-emerald-700 dark:focus:border-emerald-400"
            />
          </div>

          {/* Assigned Skills Multi-Select */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-2">
              Assigned Skills ({selectedSkills.length} selected)
            </label>
            <div className="max-h-36 overflow-y-auto p-2 rounded-xl border border-slate-200 dark:border-zinc-800 bg-slate-50 dark:bg-zinc-950 grid grid-cols-1 sm:grid-cols-2 gap-2">
              {availableSkills.map((s) => {
                const checked = selectedSkills.includes(s.id);
                return (
                  <div
                    key={s.id}
                    onClick={() => toggleSkill(s.id)}
                    className={`cursor-pointer flex items-center justify-between p-2 rounded-lg text-xs transition ${
                      checked
                        ? 'bg-emerald-500/10 text-emerald-900 dark:text-emerald-300 font-semibold'
                        : 'hover:bg-slate-200/50 dark:hover:bg-zinc-800/50 text-slate-700 dark:text-zinc-300'
                    }`}
                  >
                    <span className="truncate">{s.title || s.name}</span>
                    {checked && <Check className="w-3.5 h-3.5 text-emerald-600 shrink-0" />}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Allowed Sandboxed Tools */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-2">
              Allowed Sandboxed Tools
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              {AVAILABLE_TOOLS.map((t) => {
                const checked = selectedTools.includes(t.id);
                return (
                  <div
                    key={t.id}
                    onClick={() => toggleTool(t.id)}
                    className={`cursor-pointer p-3 rounded-xl border text-xs transition ${
                      checked
                        ? 'border-emerald-500 bg-emerald-50/50 dark:bg-emerald-950/20 text-emerald-950 dark:text-emerald-100'
                        : 'border-slate-200 dark:border-zinc-800 hover:bg-slate-50 dark:hover:bg-zinc-800/50 text-slate-600 dark:text-zinc-400'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-mono font-bold">{t.label}</span>
                      {checked && <Check className="w-3.5 h-3.5 text-emerald-600" />}
                    </div>
                    <p className="text-xs text-slate-500 dark:text-zinc-400">{t.desc}</p>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Persona Instructions */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
              Persona Instructions (System Prompt)
            </label>
            <textarea
              rows={6}
              required
              value={personaInstructions}
              onChange={(e) => setPersonaInstructions(e.target.value)}
              className="w-full p-3 text-xs rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 font-mono focus:border-emerald-700 dark:focus:border-emerald-400 leading-relaxed"
            />
          </div>

          {/* Conversation Starters */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
              Conversation Starters (one per line)
            </label>
            <textarea
              rows={3}
              value={startersText}
              onChange={(e) => setStartersText(e.target.value)}
              placeholder="What questions should I ask?&#10;Help me organize my lab records."
              className="w-full p-3 text-xs rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:border-emerald-700 dark:focus:border-emerald-400"
            />
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 pt-4 border-t border-slate-100 dark:border-zinc-800">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-600 dark:text-zinc-400 hover:bg-slate-100 dark:hover:bg-zinc-800 transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-5 py-2 rounded-xl text-xs font-semibold bg-emerald-700 hover:bg-emerald-800 text-white dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-[#04201a] shadow-sm transition disabled:opacity-50"
            >
              {submitting ? 'Saving...' : isEditing ? 'Update Agent' : 'Create Agent'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
