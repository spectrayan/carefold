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
import { X, Sparkles, ShieldAlert, Check } from 'lucide-react';
import type { SkillDetailResponse, RiskClass } from '@/types/api';

interface SkillFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (skill: SkillDetailResponse) => void;
  initialSkill?: SkillDetailResponse;
}

const AVAILABLE_TOOLS = [
  { id: 'attach-read', label: 'attach-read', desc: 'Read uploaded documents & lab results' },
  { id: 'workspace-note', label: 'workspace-note', desc: 'Save prep notes & checklists' },
  { id: 'skill-docs', label: 'skill-docs', desc: 'Access clinical reference guidelines' },
];

export function SkillFormModal({
  isOpen,
  onClose,
  onSuccess,
  initialSkill,
}: SkillFormModalProps) {
  const isEditing = Boolean(initialSkill);

  const [id, setId] = useState('');
  const [name, setName] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [domain, setDomain] = useState('clinical');
  const [category, setCategory] = useState('');
  const [riskClass, setRiskClass] = useState<RiskClass>('clinical_assist');
  const [selectedTools, setSelectedTools] = useState<string[]>(['attach-read', 'workspace-note', 'skill-docs']);
  const [instructions, setInstructions] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialSkill) {
      setId(initialSkill.id);
      setName(initialSkill.name);
      setTitle(initialSkill.title || initialSkill.name);
      setDescription(initialSkill.description || '');
      setDomain(String(initialSkill.domain || 'clinical'));
      setCategory(initialSkill.category || '');
      setRiskClass((initialSkill.risk_class as RiskClass) || 'clinical_assist');
      setSelectedTools(initialSkill.tools || []);
      setInstructions(initialSkill.instructions || '');
    } else {
      setId('');
      setName('');
      setTitle('');
      setDescription('');
      setDomain('clinical');
      setCategory('');
      setRiskClass('clinical_assist');
      setSelectedTools(['attach-read', 'workspace-note', 'skill-docs']);
      setInstructions(
        '# Clinical / Navigational Instructions\n\n' +
        'Guide the patient with structured visit preparation.\n\n' +
        '## Safety Boundaries\n' +
        '- Informational and visit preparation only.\n' +
        '- Never provide medical diagnosis or alter medications.\n' +
        '- Refer acute life-threatening symptoms immediately to 911 or emergency services.'
      );
    }
    setError(null);
  }, [initialSkill, isOpen]);

  if (!isOpen) return null;

  const toggleTool = (toolId: string) => {
    setSelectedTools((prev) =>
      prev.includes(toolId) ? prev.filter((t) => t !== toolId) : [...prev, toolId]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    const payload = {
      name: name.trim() || id.trim(),
      title: title.trim(),
      description: description.trim(),
      domain,
      category: category.trim(),
      risk_class: riskClass,
      tools: selectedTools,
      instructions,
    };

    try {
      const endpoint = isEditing ? `/api/skills/${encodeURIComponent(initialSkill!.id)}` : '/api/skills';
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

      const result: SkillDetailResponse = await res.json();
      onSuccess(result);
      onClose();
    } catch (err: any) {
      setError(err.message || 'Failed to save skill');
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
            <Sparkles className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            <h3 className="text-sm font-bold text-slate-900 dark:text-zinc-100">
              {isEditing ? `Edit Skill: ${initialSkill?.name}` : 'Create New Skill'}
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
                  Skill ID / Slug
                </label>
                <input
                  type="text"
                  required
                  value={id}
                  onChange={(e) => {
                    const slug = e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, '-');
                    setId(slug);
                    if (!name) setName(slug);
                  }}
                  placeholder="e.g. oncology-prep"
                  className="w-full px-3 py-2 text-xs rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 font-mono focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 outline-none"
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
                placeholder="e.g. Oncology Consultation Prep"
                className="w-full px-3 py-2 text-xs rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300 mb-1">
                Domain
              </label>
              <select
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                className="w-full px-3 py-2 text-xs rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 outline-none"
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
                className="w-full px-3 py-2 text-xs rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 outline-none"
              >
                <option value="clinical_assist">Clinical Assist (HITL review)</option>
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
                placeholder="e.g. oncology or insurance"
                className="w-full px-3 py-2 text-xs rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 outline-none"
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
              placeholder="e.g. Prepares patient dossier and question checklist for oncology consultation."
              className="w-full px-3 py-2 text-xs rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 outline-none"
            />
          </div>

          {/* Tools Selection */}
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
                    <p className="text-[11px] opacity-80">{t.desc}</p>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Instructions */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300">
                System Instructions (Markdown)
              </label>
              <div className="flex items-center gap-1 text-[11px] text-amber-600 dark:text-amber-400">
                <ShieldAlert className="w-3 h-3" />
                <span>Safety disclosures enforced</span>
              </div>
            </div>
            <textarea
              rows={8}
              required
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              className="w-full p-3 text-xs rounded-xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 font-mono focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 outline-none leading-relaxed"
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
              className="px-5 py-2 rounded-xl text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white shadow-sm transition disabled:opacity-50"
            >
              {submitting ? 'Saving...' : isEditing ? 'Update Skill' : 'Create Skill'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
