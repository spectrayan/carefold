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

/**
 * Emergency Services & Escalation Configuration
 * Centralizes emergency phone numbers and emergency room directory links.
 * Isolated in a single configuration module to facilitate localization (e.g., 999, 112, 000).
 */

export interface EmergencyContact {
  id: string;
  label: string;
  number: string;
  telUri: string;
  actionText: string;
  description: string;
}

export interface EmergencyServicesConfig {
  locale: string;
  country: string;
  primaryEmergency: EmergencyContact;
  crisisLifeline: EmergencyContact;
  erFinderUrl: string;
  erFinderLabel: string;
}

export const DEFAULT_EMERGENCY_SERVICES: EmergencyServicesConfig = {
  locale: 'en-US',
  country: 'US',
  primaryEmergency: {
    id: 'primary-emergency',
    label: 'Emergency Services (911)',
    number: '911',
    telUri: 'tel:911',
    actionText: 'Call 911',
    description: 'Immediate dispatch for acute life-threatening medical emergencies.'
  },
  crisisLifeline: {
    id: 'crisis-lifeline',
    label: 'Suicide & Crisis Lifeline (988)',
    number: '988',
    telUri: 'tel:988',
    actionText: 'Call or Text 988',
    description: 'Free, confidential 24/7 mental health crisis support.'
  },
  erFinderUrl: 'https://www.google.com/maps/search/emergency+room+near+me',
  erFinderLabel: 'Find Nearest Emergency Room'
};
