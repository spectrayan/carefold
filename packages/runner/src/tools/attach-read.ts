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

import fs from 'node:fs/promises';
import path from 'node:path';
import { resolveSandboxedPath, SandboxSecurityError } from '../utils/sandbox.js';
import type { ExecutionContext } from '../types/context.js';
import type { ToolResult } from '../types/tool.js';

const ALLOWED_TEXT_EXTS = new Set(['.txt', '.md', '.json', '.csv', '.tsv', '.yaml', '.yml']);
const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB

/**
 * Pure JavaScript PDF text extractor.
 * Extracts text stream blocks (BT ... ET, Tj, TJ, hex and literal strings).
 */
function extractTextFromPdfBuffer(buffer: Buffer): string {
  const content = buffer.toString('latin1');
  const textChunks: string[] = [];

  // Match text objects BT (Begin Text) ... ET (End Text)
  const textObjectRegex = /BT[\s\S]*?ET/g;
  let match: RegExpExecArray | null;

  while ((match = textObjectRegex.exec(content)) !== null) {
    const block = match[0];

    // Match string literals: (Hello World) Tj
    const tjRegex = /\(([^)]*)\)\s*Tj/g;
    let tjMatch: RegExpExecArray | null;
    while ((tjMatch = tjRegex.exec(block)) !== null) {
      textChunks.push(tjMatch[1]);
    }

    // Match text arrays: [(Hello) 10 (World)] TJ
    const tjArrayRegex = /\[(.*?)\]\s*TJ/g;
    let arrayMatch: RegExpExecArray | null;
    while ((arrayMatch = tjArrayRegex.exec(block)) !== null) {
      const inner = arrayMatch[1];
      const strRegex = /\(([^)]*)\)/g;
      let innerMatch: RegExpExecArray | null;
      while ((innerMatch = strRegex.exec(inner)) !== null) {
        textChunks.push(innerMatch[1]);
      }
    }
  }

  // Clean unescaped sequences
  const result = textChunks
    .join(' ')
    .replace(/\\([()\\])/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();

  return result;
}

export async function executeAttachRead(
  params: { path?: string; file_path?: string },
  context: ExecutionContext | { workspaceDir?: string; workspaceRoot?: string }
): Promise<ToolResult> {
  try {
    const rawPath = params.path || params.file_path;
    if (!rawPath || typeof rawPath !== 'string') {
      return { success: false, output: null, error: 'Parameter "path" must be a non-empty string.' };
    }

    const wsRoot = (context as any).workspaceRoot || (context as any).workspaceDir || process.cwd();
    const attachmentsDir = path.resolve(wsRoot, 'attachments');
    const safeFilePath = await resolveSandboxedPath(attachmentsDir, rawPath, { mustExist: true });

    const ext = path.extname(safeFilePath).toLowerCase();
    const handle = await fs.open(safeFilePath, 'r');
    try {
      const stats = await handle.stat();
      if (!stats.isFile()) {
        return { success: false, output: null, error: `Path "${rawPath}" is a directory, not a file.` };
      }

      if (stats.size > MAX_FILE_SIZE) {
        return { success: false, output: null, error: 'File size exceeds maximum allowed limit (10MB).' };
      }

      // Text File Handling
      if (ALLOWED_TEXT_EXTS.has(ext)) {
        const text = await handle.readFile('utf8');
        return {
          success: true,
          output: {
            path: rawPath,
            format: 'text',
            size_bytes: stats.size,
            content: text
          }
        };
      }

      // PDF File Handling
      if (ext === '.pdf') {
        const buffer = await handle.readFile();
        const text = extractTextFromPdfBuffer(buffer);

        if (!text || text.length === 0) {
          return {
            success: true,
            output: {
              path: rawPath,
              format: 'pdf',
              size_bytes: stats.size,
              content: '[Notice: PDF document contains no extractable text layer or is image-scanned.]'
            }
          };
        }

        return {
          success: true,
          output: {
            path: rawPath,
            format: 'pdf',
            size_bytes: stats.size,
            content: text
          }
        };
      }
    } finally {
      await handle.close();
    }

    return {
      success: false,
      output: null,
      error: `Unsupported file format "${ext}": only PDF and plain text documents are permitted.`
    };
  } catch (err: any) {
    return {
      success: false,
      output: null,
      error: err instanceof SandboxSecurityError ? err.message : `Failed to read attachment: ${err.message}`
    };
  }
}
