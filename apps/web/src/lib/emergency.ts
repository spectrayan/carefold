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
