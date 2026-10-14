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

export interface FriendlyChatError {
  summary: string;
  actionHint: string;
  technicalDetails: string;
}

/**
 * Maps raw backend/LLM error strings (missing API key, Ollama connection refused,
 * rate limit, timeout, network error, JSON parse failure) into calm, patient-friendly copy.
 */
export function formatFriendlyChatError(rawError: string): FriendlyChatError {
  const raw = (rawError || '').trim();
  const lower = raw.toLowerCase();
  const technicalDetails = raw || 'Unknown error occurred during consultation stream.';

  // 1. Missing API key / Unauthorized (401 / 403)
  if (
    lower.includes('401') ||
    lower.includes('403') ||
    lower.includes('unauthorized') ||
    lower.includes('api key') ||
    lower.includes('api_key') ||
    lower.includes('missing_api_key') ||
    lower.includes('invalid_api_key') ||
    lower.includes('authentication')
  ) {
    return {
      summary: 'An API key or active sign-in is required to talk to this helper.',
      actionHint: 'Add your API key in Settings → Model or switch to a local Ollama model.',
      technicalDetails,
    };
  }

  // 2. Rate limit / Quota exceeded (429)
  if (
    lower.includes('429') ||
    lower.includes('rate limit') ||
    lower.includes('rate-limit') ||
    lower.includes('too many requests') ||
    lower.includes('quota')
  ) {
    return {
      summary: 'The AI model service is temporarily busy or has reached its request limit.',
      actionHint: 'Wait a moment and click Try again, or select another model in Settings.',
      technicalDetails,
    };
  }

  // 3. Timeout (504 / ETIMEDOUT / AbortError)
  if (
    lower.includes('504') ||
    lower.includes('timeout') ||
    lower.includes('timed out') ||
    lower.includes('etimedout') ||
    lower.includes('aborterror')
  ) {
    return {
      summary: 'The model took too long to respond. Your message was saved.',
      actionHint: 'Click Try again or ask a shorter question.',
      technicalDetails,
    };
  }

  // 4. Ollama connection refused / Network / Unreachable
  if (
    lower.includes('econnrefused') ||
    lower.includes('failed to fetch') ||
    lower.includes('networkerror') ||
    lower.includes('network error') ||
    lower.includes('fetch failed') ||
    lower.includes('ollama') ||
    lower.includes('unreachable') ||
    lower.includes('11434') ||
    lower.includes('502') ||
    lower.includes('503')
  ) {
    return {
      summary:
        'Cannot connect to the model service. Check that Ollama is running or update your model settings.',
      actionHint:
        'Start your local Ollama server (ollama serve) or verify your model settings.',
      technicalDetails,
    };
  }

  // 5. Invalid response / Server error (500 / JSONDecodeError)
  if (
    lower.includes('jsondecodeerror') ||
    lower.includes('syntaxerror') ||
    lower.includes('unexpected token') ||
    lower.includes('expecting value') ||
    lower.includes('500') ||
    lower.includes('internal server error')
  ) {
    return {
      summary: 'Something went wrong while generating an answer. Your message was saved.',
      actionHint: 'Click Try again to re-send your message.',
      technicalDetails,
    };
  }

  // 6. Default calm fallback
  return {
    summary: 'An unexpected issue occurred while chatting. Your message was saved.',
    actionHint: 'Click Try again to re-send your message, or check Settings if the issue continues.',
    technicalDetails,
  };
}
