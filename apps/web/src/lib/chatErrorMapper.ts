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

export interface ChatErrorNotice {
  code: string;
  userMessage: string;
  technicalDetails?: string;
  canRetry: boolean;
  failedPrompt?: string;
  failedAttachments?: string[];
}

export function mapChatErrorToFriendlyNotice(
  error: unknown,
  prompt?: string,
  attachments?: string[]
): ChatErrorNotice {
  const rawMsg = error instanceof Error ? error.message : String(error || '');
  const lower = rawMsg.toLowerCase();

  // 1. Model unreachable / connection refused
  if (
    lower.includes('econnrefused') ||
    lower.includes('failed to fetch') ||
    lower.includes('unreachable') ||
    lower.includes('backend_unreachable')
  ) {
    return {
      code: 'MODEL_UNREACHABLE',
      userMessage: 'Cannot connect to the model service. Please check that Ollama or your model provider is running.',
      technicalDetails: rawMsg,
      canRetry: true,
      failedPrompt: prompt,
      failedAttachments: attachments,
    };
  }

  // 2. Unauthorized / Missing API Key
  if (
    lower.includes('401') ||
    lower.includes('unauthorized') ||
    lower.includes('missing_api_key') ||
    lower.includes('api key')
  ) {
    return {
      code: 'UNAUTHORIZED',
      userMessage: 'An API key or active sign-in is required to talk to this helper.',
      technicalDetails: rawMsg,
      canRetry: false,
      failedPrompt: prompt,
      failedAttachments: attachments,
    };
  }

  // 3. Timeout
  if (lower.includes('504') || lower.includes('timeout') || lower.includes('timed out')) {
    return {
      code: 'TIMEOUT',
      userMessage: 'The model took too long to generate a response. Your message has been saved.',
      technicalDetails: rawMsg,
      canRetry: true,
      failedPrompt: prompt,
      failedAttachments: attachments,
    };
  }

  // 4. Invalid response / Server parse error (JSONDecodeError)
  if (
    lower.includes('expecting value') ||
    lower.includes('jsondecodeerror') ||
    lower.includes('internal server error') ||
    lower.includes('500') ||
    lower.includes('502')
  ) {
    return {
      code: 'INVALID_RESPONSE',
      userMessage: 'Something went wrong while generating an answer. Your message was saved.',
      technicalDetails: rawMsg,
      canRetry: true,
      failedPrompt: prompt,
      failedAttachments: attachments,
    };
  }

  // 5. Default fallback
  return {
    code: 'EXECUTION_ERROR',
    userMessage: 'An unexpected issue occurred while chatting. Your message was saved.',
    technicalDetails: rawMsg,
    canRetry: true,
    failedPrompt: prompt,
    failedAttachments: attachments,
  };
}
