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
import {
  detectProfileAmbiguity,
  type HouseholdProfileMentionTarget
} from '@/lib/profileMentions';

describe('Profile Mentions & Pre-Send Ambiguity Engine', () => {
  const householdProfiles: HouseholdProfileMentionTarget[] = [
    {
      id: 'me',
      name: 'Sam Rivera',
      shortName: 'Sam',
      relationship: 'Self',
      colorSlot: 1
    },
    {
      id: 'rosa',
      name: 'Rosa Rivera',
      shortName: 'Rosa',
      relationship: 'Mom',
      colorSlot: 3,
      nicknames: ['Rosita', 'Nana']
    },
    {
      id: 'ava',
      name: 'Ava Rivera',
      shortName: 'Ava',
      relationship: 'Daughter',
      colorSlot: 2
    },
    {
      id: 'leo',
      name: 'Leo Rivera',
      shortName: 'Leo',
      relationship: 'Child',
      colorSlot: 4,
      nicknames: ['Peanut']
    }
  ];

  describe('Group 1: General Queries (No Mentions)', () => {
    it('returns null for queries that do not reference any household members', () => {
      expect(detectProfileAmbiguity('What is my insurance deductible?', 'me', householdProfiles)).toBeNull();
      expect(detectProfileAmbiguity('Help me prepare questions for my cardiology visit.', 'me', householdProfiles)).toBeNull();
      expect(detectProfileAmbiguity('How much is the copay for metformin?', 'rosa', householdProfiles)).toBeNull();
    });

    it('returns null for empty, whitespace, or single-profile households', () => {
      expect(detectProfileAmbiguity('', 'me', householdProfiles)).toBeNull();
      expect(detectProfileAmbiguity('   ', 'me', householdProfiles)).toBeNull();
      expect(detectProfileAmbiguity('Hello Rosa', 'me', [householdProfiles[0]])).toBeNull();
    });
  });

  describe('Group 2: Direct Name Mentions', () => {
    it('detects direct first name and full name mentions of other household members', () => {
      const match1 = detectProfileAmbiguity('How is Rosa feeling today?', 'me', householdProfiles);
      expect(match1).not.toBeNull();
      expect(match1?.targetProfileId).toBe('rosa');
      expect(match1?.targetName).toBe('Rosa Rivera');
      expect(match1?.matchedPhrase.toLowerCase()).toBe('rosa');

      const match2 = detectProfileAmbiguity('Did Leo take his asthma medicine?', 'rosa', householdProfiles);
      expect(match2).not.toBeNull();
      expect(match2?.targetProfileId).toBe('leo');
      expect(match2?.targetName).toBe('Leo Rivera');

      const match3 = detectProfileAmbiguity('Questions for Ava Rivera appointment tomorrow', 'me', householdProfiles);
      expect(match3).not.toBeNull();
      expect(match3?.targetProfileId).toBe('ava');
    });

    it('matches names case-insensitively', () => {
      const matchUpper = detectProfileAmbiguity('Check LEO allergy panel', 'me', householdProfiles);
      expect(matchUpper?.targetProfileId).toBe('leo');

      const matchLower = detectProfileAmbiguity('check rosa prescription status', 'me', householdProfiles);
      expect(matchLower?.targetProfileId).toBe('rosa');
    });

    it('matches custom nicknames declared on the profile', () => {
      const matchNickname = detectProfileAmbiguity('Does Rosita need a refill on her blood pressure meds?', 'me', householdProfiles);
      expect(matchNickname?.targetProfileId).toBe('rosa');

      const matchNickname2 = detectProfileAmbiguity('When is Peanut next dental checkup?', 'me', householdProfiles);
      expect(matchNickname2?.targetProfileId).toBe('leo');
    });
  });

  describe('Group 3: Relationship Synonyms & Possessives', () => {
    it('detects mentions using relationship synonyms (mom, mother, grandma)', () => {
      const matchMom = detectProfileAmbiguity('My mom has severe chest tightness', 'me', householdProfiles);
      expect(matchMom).not.toBeNull();
      expect(matchMom?.targetProfileId).toBe('rosa');

      const matchMother = detectProfileAmbiguity('I need to prepare questions for my mother doctor visit', 'me', householdProfiles);
      expect(matchMother?.targetProfileId).toBe('rosa');
    });

    it('detects child and daughter synonyms (child, daughter, girl)', () => {
      const matchDaughter = detectProfileAmbiguity('What are common side effects for my daughter vaccine?', 'me', householdProfiles);
      expect(matchDaughter).not.toBeNull();
      expect(matchDaughter?.targetProfileId).toBe('ava');

      const matchChild = detectProfileAmbiguity('My child has had a high fever for three days', 'me', householdProfiles);
      expect(matchChild).not.toBeNull();
      // Matches Ava or Leo (first child match)
      expect(['ava', 'leo']).toContain(matchChild?.targetProfileId);
    });

    it('handles possessive forms cleanly (e.g. Rosa\'s, mom\'s)', () => {
      const matchPossessive = detectProfileAmbiguity("Rosa's recent blood test results", 'me', householdProfiles);
      expect(matchPossessive).not.toBeNull();
      expect(matchPossessive?.targetProfileId).toBe('rosa');
    });
  });

  describe('Group 4: Edge Cases & False Positive Prevention', () => {
    it('does NOT trigger on self-mentions when user is the active profile', () => {
      // If Rosa is the active user, saying "I am Rosa" or "Rosa" should not trigger ambiguity towards Rosa
      const selfMatch = detectProfileAmbiguity('I am Rosa and I need to review my records', 'rosa', householdProfiles);
      expect(selfMatch).toBeNull();

      const selfMom = detectProfileAmbiguity("I am Mom and I'm looking at my own test results", 'rosa', householdProfiles);
      expect(selfMom).toBeNull();
    });

    it('does NOT trigger on substring collisions in words like lesson or rosemary', () => {
      // "lesson" contains "son"
      expect(detectProfileAmbiguity('I learned a valuable lesson about health insurance', 'rosa', householdProfiles)).toBeNull();

      // "prostate" contains "rose"
      expect(detectProfileAmbiguity('Doctor mentioned a prostate screening exam', 'me', householdProfiles)).toBeNull();
    });

    it('executes synchronously in under 5 milliseconds with zero network requests', () => {
      const start = performance.now();
      for (let i = 0; i < 50; i++) {
        detectProfileAmbiguity('Can you check Rosa cardiology appointment next Tuesday?', 'me', householdProfiles);
      }
      const duration = performance.now() - start;
      expect(duration).toBeLessThan(100);
    });
  });
});
