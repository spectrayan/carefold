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
 * Safe Refusal Template (CF-S13), mirroring backend/src/carefold/resources/disclaimers.yaml.
 * Immutable copy substituted whenever clinical diagnosis, dosing, emergency triage,
 * or medication alteration is triggered.
 */
export const SAFE_REFUSAL_TEMPLATE =
  'I am a wellness and care navigation assistant, not a licensed medical professional or emergency service. ' +
  'I cannot diagnose conditions, prescribe medications, or alter medical treatments. ' +
  'Please consult a qualified healthcare provider or contact emergency services immediately if you are experiencing a medical emergency.';
