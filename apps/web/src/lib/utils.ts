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

import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Sanitizes an agent description by removing stray markdown section headers
 * (e.g. "ROLE & EMPATHY:", "ROLE:") if present as a fallback artifact.
 */
export function sanitizeAgentDescription(desc?: string | null): string {
  if (!desc) return '';
  return desc
    .replace(
      /^(?:#+\s*|\*+\s*)?(?:ROLE(?:\s*&|\s+AND)?\s*EMPATHY|ROLE|CLINICAL SCOPE(?:\s*&|\s+FOCUS)?|MISSION|OVERVIEW):?\s*/i,
      ''
    )
    .trim();
}

/**
 * Formats a hierarchical category string (e.g. "clinical.ophthalmology" or "navigation.prior_auth")
 * into a clean, human-readable specialty label (e.g. "Ophthalmology", "Prior Auth").
 * Strips any redundant domain prefix matching the agent domain.
 */
export function formatCategoryLabel(category?: string | null, domain?: string | null): string {
  if (!category) return '';
  let sub = category.trim();

  // Strip leading domain prefix if present (e.g. "clinical.ophthalmology" -> "ophthalmology")
  if (domain && sub.toLowerCase().startsWith(`${domain.toLowerCase()}.`)) {
    sub = sub.slice(domain.length + 1);
  } else if (sub.includes('.')) {
    // Or take the leaf segment after the last dot
    const parts = sub.split('.');
    sub = parts[parts.length - 1];
  }

  // If subcategory is empty or identical to domain, omit redundant badge
  if (!sub || (domain && sub.toLowerCase() === domain.toLowerCase())) {
    return '';
  }

  // Replace underscores/hyphens with spaces and capitalize each word
  return sub
    .replace(/[_-]+/g, ' ')
    .trim()
    .split(' ')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');
}

/**
 * Maps risk classes to human-readable plain language labels.
 * (e.g. "wellness" -> "Wellness", "clinical_assist" -> "Clinical assist", "admin" -> "Admin", "education" -> "Education")
 */
export function formatRiskClass(riskClass?: string | null): string {
  if (!riskClass) return '';
  const trimmed = riskClass.trim();
  if (!trimmed) return '';
  const normalized = trimmed.toLowerCase();
  switch (normalized) {
    case 'wellness':
      return 'Wellness';
    case 'admin':
      return 'Admin';
    case 'education':
      return 'Education';
    case 'clinical_assist':
    case 'clinical-assist':
      return 'Clinical assist';
    default:
      return trimmed
        .replace(/[_-]+/g, ' ')
        .trim()
        .split(/\s+/)
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
        .join(' ');
  }
}

export const formatRiskLabel = formatRiskClass;
export const formatRiskClassLabel = formatRiskClass;

/**
 * Maps care stage identifiers to human-readable plain language labels.
 * (e.g. "pre_visit" -> "Before visit", "during_visit" -> "During visit",
 * "post_visit" -> "After visit", "follow_up" -> "Follow-up", "daily_living" -> "Daily living")
 */
export function formatCareStage(stage?: string | null): string {
  if (!stage) return '';
  const trimmed = stage.trim();
  if (!trimmed) return '';
  switch (trimmed.toLowerCase()) {
    case 'pre_visit':
    case 'pre-visit':
      return 'Before visit';
    case 'during_visit':
    case 'during-visit':
      return 'During visit';
    case 'post_visit':
    case 'post-visit':
      return 'After visit';
    case 'follow_up':
    case 'follow-up':
      return 'Follow-up';
    case 'daily_living':
    case 'daily-living':
      return 'Daily living';
    default:
      return trimmed
        .replace(/[_-]+/g, ' ')
        .trim()
        .split(/\s+/)
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
        .join(' ');
  }
}


