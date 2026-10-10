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
 * Strict route and profile parameter sanitizer to prevent DOM-based XSS (CWE-79)
 * and JavaScript URI execution in dynamic navigation links.
 */
export function sanitizeRouteId(id: string | null | undefined): string {
  if (!id) return '';
  return encodeURIComponent(String(id).replace(/[^a-zA-Z0-9_\-]/g, ''));
}

/**
 * Constructs a safe profile path, ensuring profileId cannot inject script or break DOM attributes.
 */
export function profilePath(profileId: string | null | undefined, subpath = ''): string {
  const safeId = sanitizeRouteId(profileId) || 'me';
  if (!subpath) {
    return `/p/${safeId}`;
  }
  const cleanSubpath = subpath.replace(/^\/+/, '');
  return `/p/${safeId}/${cleanSubpath}`;
}

/**
 * Ensures an href string is a safe relative path, neutralizing javascript: and DOM injection attacks.
 */
export function sanitizeHref(href: string | null | undefined): string {
  if (!href) return '#';
  if (href.startsWith('/') && !href.startsWith('//')) {
    return href.replace(/[<>"'`\\]/g, '');
  }
  return '#';
}
