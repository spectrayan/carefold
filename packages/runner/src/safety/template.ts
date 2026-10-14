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
 * Safe Refusal Template (CF-S13), mirroring backend/src/carefold/resources/disclaimers.yaml.
 * Immutable copy substituted whenever clinical diagnosis, dosing, emergency triage,
 * or medication alteration is triggered.
 */
export const SAFE_REFUSAL_TEMPLATE =
  'I am a wellness and care navigation assistant, not a licensed medical professional or emergency service. ' +
  'I cannot diagnose conditions, prescribe medications, or alter medical treatments. ' +
  'Please consult a qualified healthcare provider or contact emergency services immediately if you are experiencing a medical emergency.';
