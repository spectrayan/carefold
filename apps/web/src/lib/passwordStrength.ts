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
