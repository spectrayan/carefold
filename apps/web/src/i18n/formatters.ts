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

import { DEFAULT_LOCALE, normalizeLocale } from './config';
import type { SupportedLocale } from './types';

export function formatLocalizedDate(
  date: Date | string | number,
  locale: SupportedLocale = DEFAULT_LOCALE,
  options?: Intl.DateTimeFormatOptions,
  timeZone?: string
): string {
  const parsed = date instanceof Date ? date : new Date(date);
  if (Number.isNaN(parsed.getTime())) {
    return String(date);
  }
  const resolvedLocale = normalizeLocale(locale);
  const formatOptions: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    ...options,
    ...(timeZone ? { timeZone } : {})
  };
  return new Intl.DateTimeFormat(resolvedLocale, formatOptions).format(parsed);
}

export function formatLocalizedNumber(
  value: number,
  locale: SupportedLocale = DEFAULT_LOCALE,
  options?: Intl.NumberFormatOptions
): string {
  if (!Number.isFinite(value)) {
    return String(value);
  }
  const resolvedLocale = normalizeLocale(locale);
  return new Intl.NumberFormat(resolvedLocale, options).format(value);
}

export function formatLocalizedRelativeTime(
  value: number,
  unit: Intl.RelativeTimeFormatUnit,
  locale: SupportedLocale = DEFAULT_LOCALE
): string {
  const resolvedLocale = normalizeLocale(locale);
  const rtf = new Intl.RelativeTimeFormat(resolvedLocale, { numeric: 'auto' });
  return rtf.format(value, unit);
}

function parsePluralForms(body: string): Record<string, string> {
  const forms: Record<string, string> = {};
  let i = 0;
  const len = body.length;

  while (i < len) {
    while (i < len && /\s/.test(body[i])) {
      i++;
    }
    if (i >= len) break;

    const keyStart = i;
    while (i < len && !/\s|\{/.test(body[i])) {
      i++;
    }
    const key = body.slice(keyStart, i).trim();
    while (i < len && /\s/.test(body[i])) {
      i++;
    }
    if (body[i] !== '{') {
      break;
    }
    i++; // skip opening '{'
    let depth = 1;
    const contentStart = i;
    while (i < len && depth > 0) {
      if (body[i] === '{') depth++;
      else if (body[i] === '}') depth--;
      i++;
    }
    const content = body.slice(contentStart, i - 1);
    if (key) {
      forms[key] = content;
    }
  }
  return forms;
}

export function formatIcuMessage(
  template: string,
  values?: Record<string, string | number>,
  locale: SupportedLocale = DEFAULT_LOCALE
): string {
  if (!template) return '';
  if (!values || Object.keys(values).length === 0) {
    return template;
  }

  const resolvedLocale = normalizeLocale(locale);
  const pluralRules = new Intl.PluralRules(resolvedLocale);

  // First resolve top-level {var, plural, ...} blocks using balanced braces
  let result = '';
  let idx = 0;
  while (idx < template.length) {
    const openIdx = template.indexOf('{', idx);
    if (openIdx === -1) {
      result += template.slice(idx);
      break;
    }
    result += template.slice(idx, openIdx);

    let depth = 1;
    let scan = openIdx + 1;
    while (scan < template.length && depth > 0) {
      if (template[scan] === '{') depth++;
      else if (template[scan] === '}') depth--;
      scan++;
    }

    if (depth !== 0) {
      result += template.slice(openIdx);
      break;
    }

    const inner = template.slice(openIdx + 1, scan - 1);
    const pluralMatch = inner.match(/^([a-zA-Z0-9_]+)\s*,\s*plural\s*,([\s\S]*)$/);
    if (pluralMatch) {
      const varName = pluralMatch[1];
      const formsBody = pluralMatch[2];
      const rawVal = values[varName];
      const numVal = typeof rawVal === 'number' ? rawVal : Number(rawVal ?? 0);
      const forms = parsePluralForms(formsBody);
      const ruleCategory = pluralRules.select(Number.isFinite(numVal) ? numVal : 0);

      let chosen =
        forms[`=${numVal}`] ??
        (numVal === 0 && forms.zero !== undefined ? forms.zero : undefined) ??
        forms[ruleCategory] ??
        forms.other ??
        '';

      const formattedCount = Number.isFinite(numVal)
        ? formatLocalizedNumber(numVal, resolvedLocale)
        : String(rawVal ?? '');
      chosen = chosen.replace(/#/g, formattedCount);
      result += formatIcuMessage(chosen, values, resolvedLocale);
    } else {
      const key = inner.trim();
      if (Object.prototype.hasOwnProperty.call(values, key)) {
        result += String(values[key]);
      } else {
        result += `{${inner}}`;
      }
    }

    idx = scan;
  }

  return result;
}
