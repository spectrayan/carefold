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
