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

export type PasswordStrengthScore = 0 | 1 | 2 | 3 | 4;
export type PasswordStrengthLabel = 'Weak' | 'Fair' | 'Good' | 'Strong';

export interface PasswordCriteria {
  minLength: boolean;
  hasUpper: boolean;
  hasLower: boolean;
  hasDigit: boolean;
  hasSpecial: boolean;
}

export interface PasswordStrengthResult {
  score: PasswordStrengthScore;
  label: PasswordStrengthLabel;
  criteria: PasswordCriteria;
  isValid: boolean;
  passedCount: number;
  colorClass: string;
}

export const MIN_PASSWORD_LENGTH = 10;

/**
 * Evaluates live password strength on a 4-tier scale (0-4: Weak, Fair, Good, Strong)
 * and checks individual complexity criteria matching Carefold's backend rules.
 */
export function evaluatePasswordStrength(password: string): PasswordStrengthResult {
  const p = password || '';

  const criteria: PasswordCriteria = {
    minLength: p.length >= MIN_PASSWORD_LENGTH,
    hasUpper: /[A-Z]/.test(p),
    hasLower: /[a-z]/.test(p),
    hasDigit: /[0-9]/.test(p),
    hasSpecial: /[^A-Za-z0-9]/.test(p)
  };

  const passedCount = Object.values(criteria).filter(Boolean).length;

  // Carefold backend requirement: min 10 chars, uppercase, lowercase, and digit or special
  const isValid =
    criteria.minLength &&
    criteria.hasUpper &&
    criteria.hasLower &&
    (criteria.hasDigit || criteria.hasSpecial);

  let score: PasswordStrengthScore = 0;
  let label: PasswordStrengthLabel = 'Weak';
  let colorClass = 'bg-rose-500 text-rose-700 dark:text-rose-400';

  if (p.length === 0) {
    score = 0;
    label = 'Weak';
    colorClass = 'bg-slate-300 dark:bg-zinc-700 text-slate-500 dark:text-zinc-400';
  } else if (!criteria.minLength || passedCount <= 2) {
    score = 1;
    label = 'Weak';
    colorClass = 'bg-rose-500 text-rose-700 dark:text-rose-400';
  } else if (passedCount === 3) {
    score = 2;
    label = 'Fair';
    colorClass = 'bg-amber-500 text-amber-700 dark:text-amber-400';
  } else if (passedCount === 4) {
    score = 3;
    label = 'Good';
    colorClass = 'bg-blue-500 text-blue-700 dark:text-blue-400';
  } else {
    score = 4;
    label = 'Strong';
    colorClass = 'bg-emerald-500 text-emerald-700 dark:text-emerald-400';
  }

  return {
    score,
    label,
    criteria,
    isValid,
    passedCount,
    colorClass
  };
}
