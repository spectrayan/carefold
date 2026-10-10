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

export interface HouseholdProfileMentionTarget {
  id: string;
  name: string;
  shortName?: string;
  relationship?: string;
  colorSlot?: 1 | 2 | 3 | 4 | 5;
  nicknames?: string[];
}

export interface AmbiguityDetectionResult {
  targetProfileId: string;
  targetName: string;
  targetRelationship: string;
  targetColorSlot: 1 | 2 | 3 | 4 | 5;
  matchedPhrase: string;
  startIndex: number;
  endIndex: number;
}

export const RELATIONSHIP_SYNONYMS: Record<string, string[]> = {
  mom: ['mom', 'mother', 'mommy', 'mama', 'grandma', 'grandmother'],
  mother: ['mom', 'mother', 'mommy', 'mama', 'grandma', 'grandmother'],
  dad: ['dad', 'father', 'daddy', 'papa', 'grandpa', 'grandfather'],
  father: ['dad', 'father', 'daddy', 'papa', 'grandpa', 'grandfather'],
  son: ['son', 'boy', 'kid', 'child'],
  daughter: ['daughter', 'girl', 'kid', 'child'],
  child: ['son', 'daughter', 'boy', 'girl', 'child', 'kid'],
  spouse: ['husband', 'wife', 'spouse', 'partner'],
  husband: ['husband', 'spouse', 'partner'],
  wife: ['wife', 'spouse', 'partner'],
  sister: ['sister', 'sis'],
  brother: ['brother', 'bro']
};

function escapeRegExp(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Deterministically checks user text for mentions of other household members.
 * Pure synchronous execution — 0 network requests.
 */
export function detectProfileAmbiguity(
  text: string,
  activeProfileId: string,
  householdProfiles: HouseholdProfileMentionTarget[]
): AmbiguityDetectionResult | null {
  if (!text || !text.trim() || !householdProfiles || householdProfiles.length <= 1) {
    return null;
  }

  const trimmedText = text.trim();

  // Find targets other than the active profile
  const candidates = householdProfiles.filter((p) => p.id !== activeProfileId);

  for (const candidate of candidates) {
    const termsToTest: string[] = [];

    // 1. Full name
    if (candidate.name) {
      termsToTest.push(candidate.name);
    }

    // 2. First name (if distinct from full name and not generic 'me')
    const firstName = candidate.name.split(' ')[0];
    if (firstName && firstName.length >= 2 && firstName.toLowerCase() !== 'me') {
      termsToTest.push(firstName);
    }

    // 3. Short name or explicit nicknames
    if (candidate.shortName && candidate.shortName.length >= 2) {
      termsToTest.push(candidate.shortName);
    }
    if (candidate.nicknames) {
      termsToTest.push(...candidate.nicknames);
    }

    // 4. Relationship synonyms
    if (candidate.relationship) {
      const relKey = candidate.relationship.trim().toLowerCase();
      const synonyms = RELATIONSHIP_SYNONYMS[relKey] || [relKey];
      termsToTest.push(...synonyms);
    }

    // Remove duplicates & sort longest first so multi-word names match before partial words
    const uniqueTerms = Array.from(new Set(termsToTest))
      .filter((t) => t.length >= 2)
      .sort((a, b) => b.length - a.length);

    for (const term of uniqueTerms) {
      // Word boundary regex check (case-insensitive)
      // Handles possessive forms gracefully by matching word boundary before apostrophe if any
      const regex = new RegExp(`\\b${escapeRegExp(term)}(?:'s)?\\b`, 'i');
      const match = regex.exec(trimmedText);

      if (match) {
        // Disambiguation check: avoid false positive if referring to active user's own identity
        // (e.g., active user is Mom saying "I am Mom")
        const activeProfile = householdProfiles.find((p) => p.id === activeProfileId);
        if (
          activeProfile &&
          activeProfile.relationship?.toLowerCase() === term.toLowerCase() &&
          /\b(?:i am|i'm|as a|myself)\b/i.test(trimmedText)
        ) {
          continue;
        }

        return {
          targetProfileId: candidate.id,
          targetName: candidate.name,
          targetRelationship: candidate.relationship || 'Family member',
          targetColorSlot: candidate.colorSlot || 1,
          matchedPhrase: match[0],
          startIndex: match.index,
          endIndex: match.index + match[0].length
        };
      }
    }
  }

  return null;
}
