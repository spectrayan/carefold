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

import { SAFE_REFUSAL_TEMPLATE } from './template.js';
import type { SafetyCheckResult } from '../types/safety.js';

interface RefusalPattern {
  category: 'diagnose' | 'dose' | 'replace_emergency_care' | 'instruct_stop_medication';
  regex: RegExp;
  description: string;
}

// Disclaimers and safe disclosure patterns to neutralize
const DISCLAIMER_CLAUSES: RegExp[] = [
  // "I cannot / am unable to diagnose / prescribe / recommend / provide advice"
  /\b(?:i\s+)?(?:cannot|can't|unable\s+to|not\s+(?:permitted|allowed)\s+to|do\s+not|never)\s+(?:diagnose|prescribe|recommend\s+(?:a\s+)?dose|determine\s+if\s+you\s+have|provide\s+(?:medical\s+)?advice)(?:\s+(?:whether|if)\s+you\s+have\s+[a-z\s]+)?/gi,
  // "Only a doctor / clinician can diagnose / prescribe"
  /\bonly\s+(?:an?\s+)?(?:doctor|clinician|physician|licensed\s+(?:professional|clinician)|healthcare\s+provider)(?:\s+(?:or|and)\s+(?:an?\s+)?(?:doctor|clinician|physician|licensed\s+(?:professional|clinician)|healthcare\s+provider))*\s+can\s+(?:diagnose|prescribe|determine|treat)[^.!?]*/gi,
  // "Not a clinician and not emergency care", "not a licensed medical professional or emergency service"
  /\bnot\s+a\s+(?:licensed\s+)?(?:clinician|doctor|physician|medical\s+professional)(?:\s+or\s+emergency\s+service)?(?:\s+and\s+not\s+emergency\s+care)?/gi,
  /\bnot\s+emergency\s+care\b/gi,
  // "Wellness/navigation/admin help — not diagnosis or treatment"
  /\bwellness(?:\/|,\s*)navigation(?:\/|,\s*)admin\s+help\s*[-—]\s*not\s+diagnosis\s+or\s+treatment\b/gi,
  // "If this is an emergency, contact local emergency services immediately"
  /\bif\s+(?:this\s+is|you\s+are\s+experiencing)\s+an?\s+emergency,?\s*(?:contact|call|seek)\s+(?:local\s+)?(?:emergency\s+services?|911|medical\s+help)\b[^.!?]*/gi,
  // "Do not change / stop medication without prescribing clinician / doctor / consulting"
  /\b(?:do\s+not|don['’]t|never)\s+(?:change|stop\s+taking|stop|alter|adjust|discontinue)\s+(?:your\s+)?(?:current\s+|prescribed\s+)?medications?\s+without\s+(?:(?:consulting|speaking\s+with)\s+)?(?:the\s+|your\s+)?(?:prescribing\s+)?(?:clinician|doctor|physician|healthcare\s+provider)\b/gi,
  // "Please consult your doctor / physician / healthcare provider"
  /\bplease\s+consult\s+(?:a\s+qualified\s+)?(?:doctor|physician|clinician|healthcare\s+provider)\b[^.!?]*/gi,
  // "Do not hesitate to contact emergency services / go to the ER"
  /\b(?:do\s+not|don['’]t|never)\s+hesitate\s+to\s+(?:contact|call|go\s+to)\s+(?:emergency|911|the\s+er|the\s+hospital)\b[^.!?]*/gi
];

// High-confidence condition dictionary
const COMMON_CONDITIONS = [
  'adhd', 'add', 'depression', 'major depressive', 'major depressive disorder',
  'bipolar', 'bipolar disorder', 'cancer', 'diabetes', 'type 1 diabetes', 'type 2 diabetes',
  'hypertension', 'high blood pressure', 'asthma', 'autism', 'autism spectrum',
  'schizophrenia', 'ptsd', 'covid(?:-19)?', 'pneumonia', 'bronchitis', 'strep(?: throat)?',
  'shingles', 'arthritis', 'osteoarthritis', 'rheumatoid arthritis', 'anxiety(?: disorder)?',
  'flu', 'influenza', 'infection', 'lupus', 'leukemia', 'lymphoma', 'melanoma',
  'alzheimer[\'’]?s?', 'dementia', 'parkinson[\'’]?s?', 'crohn[\'’]?s?', 'celiac(?: disease)?',
  'fibromyalgia', 'gout', 'migraines?', 'concussions?', 'stroke', 'heart attack',
  '(?:congestive\\s+)?heart failure', 'heart failure',
  'myocardial infarction', 'sepsis', 'mono(?:nucleosis)?', 'sinusitis', 'tonsillitis',
  'gastritis', 'ulcers?', 'gerd', 'acid reflux', 'ibs', 'copd', 'emphysema', 'anemia',
  'neuropathy', 'appendicitis', 'diverticulitis', 'cirrhosis', 'hepatitis', 'meningitis'
].join('|');

const REFUSAL_PATTERNS: RefusalPattern[] = [
  // ==========================================
  // 1. Clinical Diagnosis (diagnose)
  // ==========================================
  {
    category: 'diagnose',
    regex: new RegExp(
      `\\b(?:you\\s+(?:have|suffer\\s+from|are\\s+suffering\\s+from)|you['’]re\\s+suffering\\s+from|indicates?\\s+(?:that\\s+)?you\\s+have|suggests?\\s+(?:that\\s+)?you\\s+have|you\\s+(?:likely|probably|definitely|clearly|seem\\s+to|appear\\s+to)\\s+have|confirm(?:ed)?\\s+that\\s+you\\s+have)\\s+(?:a\\s+|an\\s+)?(?:acute|chronic|severe|mild)?\\s*(?:${COMMON_CONDITIONS}|[a-z]{3,20}(?:itis|osis|emia|aemia|oma|pathy)|(?:[a-z]{3,20}\\s+)?(?:syndrome|disease|disorder|infection|deficiency))\\b`,
      'i'
    ),
    description: 'Direct diagnostic assertion with condition'
  },
  {
    category: 'diagnose',
    regex: new RegExp(
      `\\b(?:(?:it|this|that)\\s+)?(?:looks?\\s+like|sounds?\\s+like|appears?\\s+to\\s+be|seems?\\s+(?:like|to\\s+be)|my\\s+impression\\s+is)\\s+(?:a\\s+|an\\s+)?(?:acute|chronic|severe|mild)?\\s*(?:${COMMON_CONDITIONS}|[a-z]{3,20}(?:itis|osis|emia|aemia|oma|pathy)|(?:[a-z]{3,20}\\s+)?(?:syndrome|disease|disorder|infection|deficiency))\\b`,
      'i'
    ),
    description: 'Impression or appearance of clinical condition'
  },
  {
    category: 'diagnose',
    regex: new RegExp(
      `\\b(?:your\\s+condition\\s+(?:is|looks?\\s+like|appears?\\s+to\\s+be|seems?\\s+(?:like|to\\s+be)|indicates?))\\s+(?:a\\s+|an\\s+)?(?:acute|chronic|severe|mild)?\\s*(?:${COMMON_CONDITIONS}|[a-z]{3,20}(?:itis|osis|emia|aemia|oma|pathy)|(?:[a-z]{3,20}\\s+)?(?:syndrome|disease|disorder|infection|deficiency))\\b`,
      'i'
    ),
    description: 'Condition determination statement'
  },
  {
    category: 'diagnose',
    regex: /\b(?:diagnos(?:ed\s+with|is\s+(?:is|of)|is\s*:\s*|ing\s+(?:you\s+with)?)|i\s+diagnose(?:\s+you)?(?:\s+with)?|my\s+diagnosis\s+is(?:\s+that)?)\s+[a-z\s]{3,30}\b/i,
    description: 'Explicit diagnostic determination phrasing'
  },
  {
    category: 'diagnose',
    regex: /\b(?:(?:please|can\s+you|could\s+you)\s+diagnose(?:\s+(?:my|this|these|the|our|your))?|diagnose\s+(?:my|this|these|the|our|your))\s+[a-z0-9\s-]{2,30}\b/i,
    description: 'Imperative diagnosis request (e.g. diagnose my <symptom>)'
  },
  {
    category: 'diagnose',
    regex: /\b(?:you\s+are|you['’]re)\s+(?:depressed|bipolar|schizophrenic|autistic|anemic|diabetic|hypertensive|septic)\b/i,
    description: 'Affirmative psychological or physiological condition labeling'
  },

  // ==========================================
  // 2. Dosing & Prescription (dose)
  // ==========================================
  {
    category: 'dose',
    regex: /\b(?:take|prescribe|administer|inject|consume|ingest)(?:\s*:)?\s+(?:\d+(?:\.\d+)?|\d+\s*(?:to|-)\s*\d+)\s*(?:mg|milligrams?|g|grams?|mcg|ug|micrograms?|ml|milliliters?|cc|units?|iu|tablets?|capsules?|pills?|caplets?|drops?|puffs?|sprays?)\b/i,
    description: 'Medication administration or prescription with numeric quantity'
  },
  {
    category: 'dose',
    regex: /\b(?:(?:recommended\s+)?(?:dose|dosage)(?:\s+of\s+[a-z\s]{2,25})?(?:\s+(?:is|of)|\s*:)?)\s*\d+(?:\.\d+)?\s*(?:mg|milligrams?|g|grams?|mcg|ug|micrograms?|ml|milliliters?|cc|units?|iu|tablets?|capsules?|pills?|caplets?|drops?|puffs?|sprays?)\b/i,
    description: 'Dosage specification with colon or verb syntax'
  },
  {
    category: 'dose',
    regex: /\b(?:(?:i\s+)?prescribe|prescribing(?:\s+you)?(?!\s+(?:doctor|clinician|physician|provider|practitioner))|prescribed\s*:|prescription(?:\s+(?:is|for)|\s*:))\s+[a-z0-9\s]{2,30}\b/i,
    description: 'Prescription declaration or structured header'
  },
  {
    category: 'dose',
    regex: /\b(?:increase|decrease|adjust|titrate|raise|lower)\s+(?:your\s+)?(?:dose|dosage)\s+to\s+\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|units?|tablets?|pills?)\b/i,
    description: 'Dosage adjustment or titration instruction'
  },
  {
    category: 'dose',
    regex: /\b\d+(?:\.\d+)?\s*(?:mg|mcg|ug|milligrams?|units?)\s+(?:daily|twice\s+(?:daily|(?:a\s+)?day)|once\s+(?:daily|(?:a\s+)?day)|(?:every|\/)\s*\d+\s*(?:hours?|hrs?)|every\s+day|as\s+needed|orally|sublingually|before\s+bed|at\s+bedtime)\b/i,
    description: 'Medication administration schedule'
  },
  {
    category: 'dose',
    regex: /\btake\s+\d+(?:\s*(?:to|-)\s*\d+)?\s+(?:pills?|tablets?|capsules?|caplets?)\b/i,
    description: 'Pill count recommendation'
  },

  // ==========================================
  // 3. Triage & Emergency Diversion (replace_emergency_care)
  // ==========================================
  {
    category: 'replace_emergency_care',
    regex: /\b(?:don['’]t|do\s+not|never|no\s+need\s+to|skip|avoid|delay|refrain\s+from)\s+(?:(?:go(?:ing)?\s+to|visit(?:ing)?|head(?:ing)?\s+to|seek(?:ing)?)\s+)?(?:the\s+)?(?:er|emergency\s+room|emergency\s+department|hospital|urgent\s+care|emergency\s+care|emergency\s+services?)\b/i,
    description: 'Advising user to avoid emergency medical facilities'
  },
  {
    category: 'replace_emergency_care',
    regex: /\b(?:don['’]t|do\s+not|never|no\s+need\s+(?:to|for)|skip|avoid|cancel|abort|hang\s+up\s+(?:on)?|delay|refrain\s+from|stop)\s+(?:(?:call(?:ing)?|dial(?:ing)?|dispatch(?:ing)?|contact(?:ing)?)\s+)?(?:(?:your|the|an?)\s+)?(?:911|999|112|ambulance|paramedics?|emergency\s+services?)(?:\s+call)?\b/i,
    description: 'Advising user to cancel or avoid emergency services dispatch'
  },
  {
    category: 'replace_emergency_care',
    regex: /\b(?:stay\s+home|wait\s+it\s+out|wait\s+until\s+tomorrow|just\s+rest|drink\s+(?:some\s+)?tea)\s+instead\s+of\s+(?:go(?:ing)?\s+to|call(?:ing)?|seek(?:ing)?)\s+(?:the\s+)?(?:er|emergency|hospital|911|ambulance|urgent\s+care)\b/i,
    description: 'Substitution of emergency services with home care or delay'
  },
  {
    category: 'replace_emergency_care',
    regex: /\b(?:you\s+(?:don['’]t|do\s+not)\s+need\s+(?:to\s+go\s+to|to\s+call|to\s+visit)?\s*(?:the\s+)?(?:er|emergency\s+room|emergency\s+department|hospital|911|an?\s+ambulance|urgent\s+care|emergency\s+services?))\b/i,
    description: 'Dismissal of emergency care need'
  },
  {
    category: 'replace_emergency_care',
    regex: /\bavoid\s+(?:the\s+)?(?:er|emergency\s+room|urgent\s+care|hospital|911|ambulance)\b/i,
    description: 'Direct avoidance directive for acute care'
  },

  // ==========================================
  // 4. Medication Cessation & Alteration (instruct_stop_medication)
  // ==========================================
  {
    category: 'instruct_stop_medication',
    regex: /\b(?:stop|discontinue|cease|quit|halt|do\s+not\s+take|don['’]t\s+take)\s+(?:taking|using|ingesting)?\s*(?:your|the|any)?\s*(?:current\s+|prescribed\s+)?[a-z\s]{0,25}?(?:medications?|meds?|treatments?|prescriptions?|pills?|tablets?|capsules?|injections?|therap(?:y|ies))\b/i,
    description: 'Instruction to discontinue medication or clinical treatment'
  },
  {
    category: 'instruct_stop_medication',
    regex: /\b(?:hold|skip|pause|omit)\s+(?:your|the)?\s*(?:[a-z\s]{0,20})?\s*doses?\b/i,
    description: 'Instruction to hold or skip medication dose'
  },
  {
    category: 'instruct_stop_medication',
    regex: /\b(?:stop|discontinue|cease|quit|halt)\s+(?:taking|using)?\s*(?:your|the)?\s*(?:insulin|metformin|lisinopril|atorvastatin|levothyroxine|amlodipine|metoprolol|omeprazole|losartan|gabapentin|hydrochlorothiazide|sertraline|simvastatin|montelukast|escitalopram|prednisone|chemotherapy|chemo|radiation|dialysis|inhalers?|statins?|antidepressants?|blood\s+pressure\s+(?:meds?|medications?|pills?)|heart\s+medications?)\b/i,
    description: 'Instruction to discontinue specific critical prescription medications'
  },
  {
    category: 'instruct_stop_medication',
    regex: /\b(?:taper\s+off|cut\s+down)\s+(?:your\s+)?(?:medication|insulin|prescriptions?|pills?|dose|dosage)\s+(?:without\s+(?:a\s+)?(?:doctor|clinician|physician)|on\s+your\s+own)\b/i,
    description: 'Instruction to alter or taper medication without medical supervision'
  }
];

export function checkSafetyRefusal(text: string): SafetyCheckResult {
  if (!text || typeof text !== 'string') {
    return { refused: false };
  }

  // Quick check: If the text is already the exact safe refusal template, pass
  if (text.includes(SAFE_REFUSAL_TEMPLATE)) {
    return { refused: false };
  }

  // Normalize markdown decorators (*, _, `, #) so bold/italic tags don't disrupt token boundaries
  const normalizedText = text.replace(/[*_`#]/g, '');

  // Neutralize legitimate disclaimer clauses by replacing them with spaces of equal length
  let sanitizedText = normalizedText;
  for (const disclaimerRegex of DISCLAIMER_CLAUSES) {
    sanitizedText = sanitizedText.replace(disclaimerRegex, (match) => ' '.repeat(match.length));
  }

  // Split into sentences across punctuation and line boundaries
  const sentences = sanitizedText.split(/(?<=[.!?\n])\s+/);

  for (const sentence of sentences) {
    const trimmed = sentence.trim();
    if (!trimmed) continue;

    for (const pattern of REFUSAL_PATTERNS) {
      if (pattern.regex.test(trimmed)) {
        return {
          refused: true,
          reason: `forbidden_intent:${pattern.category}`,
          safeResponse: SAFE_REFUSAL_TEMPLATE
        };
      }
    }
  }

  return { refused: false };
}
