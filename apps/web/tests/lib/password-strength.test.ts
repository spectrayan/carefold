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

import { describe, it, expect } from 'vitest';
import { evaluatePasswordStrength, MIN_PASSWORD_LENGTH } from '@/lib/passwordStrength';

describe('evaluatePasswordStrength - Robustness & Stress Suite', () => {
  describe('Constants & Baseline Specifications', () => {
    it('exports MIN_PASSWORD_LENGTH equal to 10', () => {
      expect(MIN_PASSWORD_LENGTH).toBe(10);
    });
  });

  describe('1. Exact 10-Character Boundary Challenges', () => {
    it('rejects 9-character passwords even when containing all 4 character classes', () => {
      // Contains upper, lower, digit, special, but length is 9 (< 10)
      const pw9 = 'Ab1!cdefg';
      expect(pw9.length).toBe(9);

      const result = evaluatePasswordStrength(pw9);
      expect(result.criteria.minLength).toBe(false);
      expect(result.criteria.hasUpper).toBe(true);
      expect(result.criteria.hasLower).toBe(true);
      expect(result.criteria.hasDigit).toBe(true);
      expect(result.criteria.hasSpecial).toBe(true);
      expect(result.passedCount).toBe(4);
      // Boundary invariant: must NOT be valid and score must be < 4
      expect(result.isValid).toBe(false);
      expect(result.score).toBeLessThan(4);
      expect(result.score).toBe(1);
      expect(result.label).toBe('Weak');
      expect(result.colorClass).toContain('bg-rose-500');
    });

    it('accepts 10-character passwords with all 4 character classes as Strong and valid', () => {
      const pw10 = 'Ab1!cdefgh';
      expect(pw10.length).toBe(10);

      const result = evaluatePasswordStrength(pw10);
      expect(result.criteria.minLength).toBe(true);
      expect(result.criteria.hasUpper).toBe(true);
      expect(result.criteria.hasLower).toBe(true);
      expect(result.criteria.hasDigit).toBe(true);
      expect(result.criteria.hasSpecial).toBe(true);
      expect(result.passedCount).toBe(5);
      expect(result.isValid).toBe(true);
      expect(result.score).toBe(4);
      expect(result.label).toBe('Strong');
      expect(result.colorClass).toContain('bg-emerald-500');
    });

    it('verifies the step-function transition strictly between length 9 and length 10', () => {
      const base = 'Ab1!cdef'; // length 8
      const pw8 = base; // 8
      const pw9 = base + 'g'; // 9
      const pw10 = base + 'gh'; // 10
      const pw11 = base + 'ghi'; // 11

      const res8 = evaluatePasswordStrength(pw8);
      const res9 = evaluatePasswordStrength(pw9);
      const res10 = evaluatePasswordStrength(pw10);
      const res11 = evaluatePasswordStrength(pw11);

      expect(res8.isValid).toBe(false);
      expect(res8.score).toBe(1);

      expect(res9.isValid).toBe(false);
      expect(res9.score).toBe(1);

      expect(res10.isValid).toBe(true);
      expect(res10.score).toBe(4);

      expect(res11.isValid).toBe(true);
      expect(res11.score).toBe(4);
    });
  });

  describe('2. Missing Character Classes in 12+ Character Passwords', () => {
    it('fails isValid for 12-char password missing uppercase letter', () => {
      const pw = 'abcdefgh123!';
      expect(pw.length).toBe(12);

      const result = evaluatePasswordStrength(pw);
      expect(result.criteria.minLength).toBe(true);
      expect(result.criteria.hasUpper).toBe(false);
      expect(result.criteria.hasLower).toBe(true);
      expect(result.criteria.hasDigit).toBe(true);
      expect(result.criteria.hasSpecial).toBe(true);
      expect(result.passedCount).toBe(4);
      // Even with 4 passed criteria and Good score, missing upper MUST invalidate
      expect(result.score).toBe(3);
      expect(result.label).toBe('Good');
      expect(result.isValid).toBe(false);
    });

    it('fails isValid for 12-char password missing lowercase letter', () => {
      const pw = 'ABCDEFGH123!';
      expect(pw.length).toBe(12);

      const result = evaluatePasswordStrength(pw);
      expect(result.criteria.minLength).toBe(true);
      expect(result.criteria.hasUpper).toBe(true);
      expect(result.criteria.hasLower).toBe(false);
      expect(result.criteria.hasDigit).toBe(true);
      expect(result.criteria.hasSpecial).toBe(true);
      expect(result.passedCount).toBe(4);
      expect(result.score).toBe(3);
      expect(result.label).toBe('Good');
      expect(result.isValid).toBe(false);
    });

    it('fails isValid for 12-char password missing BOTH digits and special symbols', () => {
      const pw = 'Abcdefghijkl';
      expect(pw.length).toBe(12);

      const result = evaluatePasswordStrength(pw);
      expect(result.criteria.minLength).toBe(true);
      expect(result.criteria.hasUpper).toBe(true);
      expect(result.criteria.hasLower).toBe(true);
      expect(result.criteria.hasDigit).toBe(false);
      expect(result.criteria.hasSpecial).toBe(false);
      expect(result.passedCount).toBe(3);
      expect(result.score).toBe(2);
      expect(result.label).toBe('Fair');
      expect(result.isValid).toBe(false);
    });

    it('passes isValid for 12-char password with digits but no symbols (digit satisfies digit || special)', () => {
      const pw = 'Abcdefgh1234';
      expect(pw.length).toBe(12);

      const result = evaluatePasswordStrength(pw);
      expect(result.criteria.minLength).toBe(true);
      expect(result.criteria.hasUpper).toBe(true);
      expect(result.criteria.hasLower).toBe(true);
      expect(result.criteria.hasDigit).toBe(true);
      expect(result.criteria.hasSpecial).toBe(false);
      expect(result.passedCount).toBe(4);
      expect(result.score).toBe(3);
      expect(result.label).toBe('Good');
      expect(result.isValid).toBe(true);
    });

    it('passes isValid for 12-char password with symbols but no digits (symbol satisfies digit || special)', () => {
      const pw = 'Abcdefgh!@#$';
      expect(pw.length).toBe(12);

      const result = evaluatePasswordStrength(pw);
      expect(result.criteria.minLength).toBe(true);
      expect(result.criteria.hasUpper).toBe(true);
      expect(result.criteria.hasLower).toBe(true);
      expect(result.criteria.hasDigit).toBe(false);
      expect(result.criteria.hasSpecial).toBe(true);
      expect(result.passedCount).toBe(4);
      expect(result.score).toBe(3);
      expect(result.label).toBe('Good');
      expect(result.isValid).toBe(true);
    });

    it('fails isValid for 12-char password with only numbers and symbols (missing all letters)', () => {
      const pw = '12345678!@#$';
      expect(pw.length).toBe(12);

      const result = evaluatePasswordStrength(pw);
      expect(result.criteria.minLength).toBe(true);
      expect(result.criteria.hasUpper).toBe(false);
      expect(result.criteria.hasLower).toBe(false);
      expect(result.criteria.hasDigit).toBe(true);
      expect(result.criteria.hasSpecial).toBe(true);
      expect(result.passedCount).toBe(3);
      expect(result.score).toBe(2);
      expect(result.label).toBe('Fair');
      expect(result.isValid).toBe(false);
    });
  });

  describe('3. Extreme & Malformed Inputs', () => {
    it('handles empty string with score 0 and initial neutral styling', () => {
      const result = evaluatePasswordStrength('');
      expect(result.score).toBe(0);
      expect(result.label).toBe('Weak');
      expect(result.isValid).toBe(false);
      expect(result.passedCount).toBe(0);
      expect(result.criteria.minLength).toBe(false);
      expect(result.criteria.hasUpper).toBe(false);
      expect(result.criteria.hasLower).toBe(false);
      expect(result.criteria.hasDigit).toBe(false);
      expect(result.criteria.hasSpecial).toBe(false);
      expect(result.colorClass).toContain('bg-slate-300');
    });

    it('handles null/undefined gracefully without runtime exceptions', () => {
      const resultNull = evaluatePasswordStrength(null as unknown as string);
      expect(resultNull.score).toBe(0);
      expect(resultNull.isValid).toBe(false);

      const resultUndef = evaluatePasswordStrength(undefined as unknown as string);
      expect(resultUndef.score).toBe(0);
      expect(resultUndef.isValid).toBe(false);
    });

    it('rejects whitespace-only passwords across various lengths', () => {
      // 1 space
      const res1 = evaluatePasswordStrength(' ');
      expect(res1.score).toBe(1);
      expect(res1.isValid).toBe(false);

      // 9 spaces (< minLength)
      const res9 = evaluatePasswordStrength('         ');
      expect(res9.criteria.minLength).toBe(false);
      expect(res9.isValid).toBe(false);
      expect(res9.score).toBe(1);

      // 10 spaces (>= minLength, whitespace triggers hasSpecial because [^A-Za-z0-9])
      const res10 = evaluatePasswordStrength('          ');
      expect(res10.criteria.minLength).toBe(true);
      expect(res10.criteria.hasSpecial).toBe(true);
      expect(res10.criteria.hasUpper).toBe(false);
      expect(res10.criteria.hasLower).toBe(false);
      expect(res10.criteria.hasDigit).toBe(false);
      expect(res10.passedCount).toBe(2); // minLength + hasSpecial
      expect(res10.isValid).toBe(false);
      expect(res10.score).toBe(1);
      expect(res10.label).toBe('Weak');

      // 50 spaces
      const res50 = evaluatePasswordStrength(' '.repeat(50));
      expect(res50.isValid).toBe(false);
      expect(res50.score).toBe(1);
    });

    it('evaluates extreme 1,000-character passwords accurately and quickly without reDoS', () => {
      const longStrongPw = 'A' + 'b' + '1' + '!' + 'x'.repeat(996);
      expect(longStrongPw.length).toBe(1000);

      const startTime = performance.now();
      const result = evaluatePasswordStrength(longStrongPw);
      const elapsed = performance.now() - startTime;

      expect(elapsed).toBeLessThan(50); // Must be near-instant
      expect(result.criteria.minLength).toBe(true);
      expect(result.criteria.hasUpper).toBe(true);
      expect(result.criteria.hasLower).toBe(true);
      expect(result.criteria.hasDigit).toBe(true);
      expect(result.criteria.hasSpecial).toBe(true);
      expect(result.passedCount).toBe(5);
      expect(result.isValid).toBe(true);
      expect(result.score).toBe(4);
      expect(result.label).toBe('Strong');

      // 1,000 chars of identical lowercase
      const longWeakPw = 'a'.repeat(1000);
      const weakResult = evaluatePasswordStrength(longWeakPw);
      expect(weakResult.passedCount).toBe(2); // length, lower
      expect(weakResult.isValid).toBe(false);
      expect(weakResult.score).toBe(1);
      expect(weakResult.label).toBe('Weak');
    });

    it('evaluates unicode symbols and emojis', () => {
      // Password with emoji
      const emojiPw = 'Password123🔥';
      const emojiRes = evaluatePasswordStrength(emojiPw);
      expect(emojiRes.criteria.hasSpecial).toBe(true);
      expect(emojiRes.criteria.hasUpper).toBe(true);
      expect(emojiRes.criteria.hasLower).toBe(true);
      expect(emojiRes.criteria.hasDigit).toBe(true);
      expect(emojiRes.isValid).toBe(true);
      expect(emojiRes.score).toBe(4);

      // Password with Spanish tilde / accented character
      const accentPw = 'Contraseña1!';
      const accentRes = evaluatePasswordStrength(accentPw);
      expect(accentRes.criteria.hasSpecial).toBe(true); // 'ñ' and '!' match [^A-Za-z0-9]
      expect(accentRes.criteria.hasUpper).toBe(true);
      expect(accentRes.criteria.hasLower).toBe(true);
      expect(accentRes.criteria.hasDigit).toBe(true);
      expect(accentRes.isValid).toBe(true);
      expect(accentRes.score).toBe(4);

      // Non-ASCII alphabet only (Cyrillic) without ASCII letters
      const cyrillicPw = 'Пароль12345!';
      const cyrillicRes = evaluatePasswordStrength(cyrillicPw);
      // In ASCII regex /[A-Z]/ and /[a-z]/, Cyrillic letters are not matched
      expect(cyrillicRes.criteria.hasUpper).toBe(false);
      expect(cyrillicRes.criteria.hasLower).toBe(false);
      expect(cyrillicRes.isValid).toBe(false);
    });

    it('evaluates security injection patterns safely without crashes or code execution', () => {
      // SQL Injection payload
      const sqliPw = "' OR '1'='1; DROP TABLE Users; --Abc";
      const sqliRes = evaluatePasswordStrength(sqliPw);
      expect(sqliRes.criteria.minLength).toBe(true);
      expect(sqliRes.criteria.hasUpper).toBe(true);
      expect(sqliRes.criteria.hasLower).toBe(true);
      expect(sqliRes.criteria.hasDigit).toBe(true);
      expect(sqliRes.criteria.hasSpecial).toBe(true);
      expect(sqliRes.isValid).toBe(true);
      expect(sqliRes.score).toBe(4);

      // XSS payload
      const xssPw = "<script>alert('XSS')</script>9";
      const xssRes = evaluatePasswordStrength(xssPw);
      expect(xssRes.criteria.minLength).toBe(true);
      expect(xssRes.criteria.hasUpper).toBe(true);
      expect(xssRes.criteria.hasLower).toBe(true);
      expect(xssRes.criteria.hasDigit).toBe(true);
      expect(xssRes.criteria.hasSpecial).toBe(true);
      expect(xssRes.isValid).toBe(true);
      expect(xssRes.score).toBe(4);

      // Shell injection & backticks
      const shPw = "$(whoami)`touch /tmp/pwn`Aa1";
      const shRes = evaluatePasswordStrength(shPw);
      expect(shRes.isValid).toBe(true);
      expect(shRes.score).toBe(4);

      // Null bytes and control characters
      const nullBytePw = '\x00\r\n\tSecurePass1!';
      const nullRes = evaluatePasswordStrength(nullBytePw);
      expect(nullRes.isValid).toBe(true);
      expect(nullRes.score).toBe(4);
    });

    it('guarantees linear performance on 50,000-character string', () => {
      const hugeString = 'Aa1!' + 'x'.repeat(49996);
      const start = performance.now();
      const res = evaluatePasswordStrength(hugeString);
      const timeMs = performance.now() - start;

      expect(timeMs).toBeLessThan(100);
      expect(res.isValid).toBe(true);
      expect(res.score).toBe(4);
    });
  });

  describe('4. Score Transitions Across All 5 Tiers (0, 1, 2, 3, 4)', () => {
    it('Score 0 (Weak): transitions only for zero-length inputs', () => {
      const res = evaluatePasswordStrength('');
      expect(res.score).toBe(0);
      expect(res.label).toBe('Weak');
      expect(res.passedCount).toBe(0);
      expect(res.isValid).toBe(false);
      expect(res.colorClass).toContain('bg-slate-300');
    });

    it('Score 1 (Weak): transitions for length < 10 or <= 2 criteria passed', () => {
      // 1 char lower
      expect(evaluatePasswordStrength('a').score).toBe(1);
      expect(evaluatePasswordStrength('a').label).toBe('Weak');

      // 2 chars upper & lower
      expect(evaluatePasswordStrength('Ab').score).toBe(1);

      // 4 chars with 4 criteria (upper, lower, digit, special), but length < 10
      const short4 = evaluatePasswordStrength('Ab1!');
      expect(short4.score).toBe(1);
      expect(short4.label).toBe('Weak');
      expect(short4.passedCount).toBe(4);
      expect(short4.isValid).toBe(false);

      // 10 chars with only 2 criteria passed (length + lowercase)
      const long2 = evaluatePasswordStrength('abcdefghij');
      expect(long2.score).toBe(1);
      expect(long2.label).toBe('Weak');
      expect(long2.passedCount).toBe(2);
      expect(long2.isValid).toBe(false);
    });

    it('Score 2 (Fair): transitions when exactly 3 criteria are passed', () => {
      // 10 chars: length + upper + lower
      const res1 = evaluatePasswordStrength('Abcdefghij');
      expect(res1.score).toBe(2);
      expect(res1.label).toBe('Fair');
      expect(res1.passedCount).toBe(3);
      expect(res1.isValid).toBe(false); // missing digit or special
      expect(res1.colorClass).toContain('bg-amber-500');

      // 10 chars: length + digit + special
      const res2 = evaluatePasswordStrength('123456789!');
      expect(res2.score).toBe(2);
      expect(res2.label).toBe('Fair');
      expect(res2.passedCount).toBe(3);
      expect(res2.isValid).toBe(false); // missing upper & lower

      // 11 chars: length + upper + digit
      const res3 = evaluatePasswordStrength('ABCDEF12345');
      expect(res3.score).toBe(2);
      expect(res3.label).toBe('Fair');
      expect(res3.passedCount).toBe(3);
      expect(res3.isValid).toBe(false);
    });

    it('Score 3 (Good): transitions when exactly 4 criteria are passed', () => {
      // 10 chars: length + upper + lower + digit (Valid)
      const res1 = evaluatePasswordStrength('Abcdefgh12');
      expect(res1.score).toBe(3);
      expect(res1.label).toBe('Good');
      expect(res1.passedCount).toBe(4);
      expect(res1.isValid).toBe(true);
      expect(res1.colorClass).toContain('bg-blue-500');

      // 10 chars: length + upper + lower + special (Valid)
      const res2 = evaluatePasswordStrength('Abcdefgh!@');
      expect(res2.score).toBe(3);
      expect(res2.label).toBe('Good');
      expect(res2.passedCount).toBe(4);
      expect(res2.isValid).toBe(true);
      expect(res2.colorClass).toContain('bg-blue-500');

      // 10 chars: length + upper + digit + special (Invalid: missing lower)
      const res3 = evaluatePasswordStrength('ABCDEF12!@');
      expect(res3.score).toBe(3);
      expect(res3.label).toBe('Good');
      expect(res3.passedCount).toBe(4);
      expect(res3.isValid).toBe(false);

      // 10 chars: length + lower + digit + special (Invalid: missing upper)
      const res4 = evaluatePasswordStrength('abcdef12!@');
      expect(res4.score).toBe(3);
      expect(res4.label).toBe('Good');
      expect(res4.passedCount).toBe(4);
      expect(res4.isValid).toBe(false);
    });

    it('Score 4 (Strong): transitions when all 5 criteria are passed', () => {
      const res = evaluatePasswordStrength('Abcdefgh1!');
      expect(res.score).toBe(4);
      expect(res.label).toBe('Strong');
      expect(res.passedCount).toBe(5);
      expect(res.isValid).toBe(true);
      expect(res.colorClass).toContain('bg-emerald-500');
    });
  });

  describe('5. Form Validation Contracts & Invariants', () => {
    // Contract helper matching RegisterPage, ResetPasswordPage, and SecurityProfilePanel:
    const checkPasswordsMatch = (password: string, confirmPassword: string) => {
      return password.length > 0 && password === confirmPassword;
    };

    it('verifies passwordsMatch contract: exact match returns true', () => {
      expect(checkPasswordsMatch('CorrectHorse99!', 'CorrectHorse99!')).toBe(true);
    });

    it('verifies passwordsMatch contract: case mismatch returns false', () => {
      expect(checkPasswordsMatch('CorrectHorse99!', 'correcthorse99!')).toBe(false);
      expect(checkPasswordsMatch('PASSWORD123!', 'password123!')).toBe(false);
    });

    it('verifies passwordsMatch contract: whitespace differences return false without silent trimming', () => {
      expect(checkPasswordsMatch('CorrectHorse99!', 'CorrectHorse99! ')).toBe(false);
      expect(checkPasswordsMatch('CorrectHorse99!', ' CorrectHorse99!')).toBe(false);
      expect(checkPasswordsMatch('CorrectHorse99!', 'Correct Horse99!')).toBe(false);
    });

    it('verifies passwordsMatch contract: empty strings return false to prevent bypass', () => {
      expect(checkPasswordsMatch('', '')).toBe(false);
      expect(checkPasswordsMatch('SecretPass1!', '')).toBe(false);
      expect(checkPasswordsMatch('', 'SecretPass1!')).toBe(false);
    });

    it('verifies passwordsMatch contract: prefix/suffix substrings return false', () => {
      expect(checkPasswordsMatch('SuperSecret123!', 'SuperSecret123')).toBe(false);
      expect(checkPasswordsMatch('SuperSecret123', 'SuperSecret123!')).toBe(false);
    });

    it('verifies parity with backend validate_password_complexity contract', () => {
      // Backend contract: len >= 10, any(c.isupper()), any(c.islower()), any(c.isdigit() or not c.isalnum())
      const testCases = [
        { pw: 'Abc1!defgh', expectedValid: true },
        { pw: 'Abcdefghij', expectedValid: false },
        { pw: 'Abcdefgh12', expectedValid: true },
        { pw: 'Abcdefgh!@', expectedValid: true },
        { pw: 'ABCDEF12!@', expectedValid: false },
        { pw: 'abcdef12!@', expectedValid: false },
        { pw: '123456789!', expectedValid: false },
        { pw: 'Ab1!cdefg', expectedValid: false },
        { pw: '', expectedValid: false }
      ];

      for (const { pw, expectedValid } of testCases) {
        const result = evaluatePasswordStrength(pw);
        expect(result.isValid).toBe(expectedValid);
      }
    });
  });
});
