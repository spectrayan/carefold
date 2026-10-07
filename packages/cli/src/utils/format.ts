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
 * Strips ANSI escape sequences from a string
 */
export function stripAnsi(str: string): string {
  return str.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, '');
}

/**
 * Returns the visible character length of a string, ignoring ANSI escape sequences
 */
export function visibleLength(str: string): number {
  return stripAnsi(str).length;
}

/**
 * Pads a string to a visible target width, correctly handling ANSI codes
 */
export function padAnsiEnd(str: string, targetWidth: number): string {
  const vLen = visibleLength(str);
  if (vLen >= targetWidth) {
    return str;
  }
  return str + ' '.repeat(targetWidth - vLen);
}

export function formatTable(headers: string[], rows: string[][]): string {
  if (rows.length === 0) {
    return '';
  }

  // Calculate maximum visible width for each column
  const colWidths = headers.map((header, colIndex) => {
    let maxWidth = visibleLength(header);
    for (const row of rows) {
      const cell = row[colIndex] || '';
      const cellWidth = visibleLength(cell);
      if (cellWidth > maxWidth) {
        maxWidth = cellWidth;
      }
    }
    return maxWidth;
  });

  // Render header line
  const headerLine = headers.map((h, i) => padAnsiEnd(h, colWidths[i])).join('   ');
  const dividerLine = colWidths.map((w) => '─'.repeat(w)).join('   ');

  // Render rows
  const rowLines = rows.map((row) => {
    return headers.map((_, i) => padAnsiEnd(row[i] || '', colWidths[i])).join('   ');
  });

  return [headerLine, dividerLine, ...rowLines].join('\n');
}

export function formatRiskBadge(riskClass: string): string {
  switch (riskClass) {
    case 'wellness':
      return 'wellness';
    case 'admin':
      return 'admin';
    case 'education':
      return 'education';
    case 'clinical_assist':
      return 'clinical_assist [RESTRICTED]';
    default:
      return riskClass;
  }
}
