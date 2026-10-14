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

import fs from 'node:fs/promises';
import path from 'node:path';
import { resolveSandboxedPath, SandboxSecurityError } from '../utils/sandbox.js';
import type { ExecutionContext } from '../types/context.js';
import type { ToolResult } from '../types/tool.js';

const ALLOWED_DOC_EXTS = new Set(['.md', '.txt', '.json', '.yaml', '.yml']);

export async function executeSkillDocs(
  params: { skill_id: string; doc?: string; doc_name?: string },
  context: ExecutionContext | { workspaceDir?: string; workspaceRoot?: string; agent?: any }
): Promise<ToolResult> {
  try {
    const skill_id = params.skill_id;
    const doc = params.doc || params.doc_name;

    if (!skill_id || typeof skill_id !== 'string') {
      return { success: false, output: null, error: 'Parameter "skill_id" is required.' };
    }
    if (!doc || typeof doc !== 'string') {
      return { success: false, output: null, error: 'Parameter "doc" is required.' };
    }

    // 1. Strict slug validation for skill_id (CF-VULN-01)
    if (!/^[a-zA-Z0-9_\-]+$/.test(skill_id)) {
      return {
        success: false,
        output: null,
        error: `Path traversal forbidden: Invalid skill_id "${skill_id}". Skill IDs must contain only alphanumeric characters, dashes, and underscores.`
      };
    }

    // 2. Fail-closed authorization check: agent context and declared skills are mandatory (CF-S46 / CF-VULN-02)
    const agent = (context as any)?.agent;
    if (!agent || typeof agent !== 'object' || !Array.isArray(agent.skills)) {
      return {
        success: false,
        output: null,
        error: 'Access denied: An authenticated agent context with declared skills is required to access skill docs.'
      };
    }

    if (!agent.skills.includes(skill_id)) {
      return {
        success: false,
        output: null,
        error: `Access denied: Skill "${skill_id}" is not declared on agent "${agent.id || 'unknown'}". Undeclared skills cannot be accessed.`
      };
    }

    const wsRoot = (context as any).workspaceRoot || (context as any).workspaceDir || process.cwd();
    const skillsDir = (context as any).skillsDir
      ? path.resolve((context as any).skillsDir)
      : path.resolve(wsRoot, 'skills');

    // 3. Sandboxed resolution of skill folder within skillsDir (CF-VULN-01)
    const skillDir = await resolveSandboxedPath(skillsDir, skill_id, { mustExist: true });
    const refDir = path.resolve(skillDir, 'references');
    const targetPath = await resolveSandboxedPath(refDir, doc, { mustExist: true });

    // 4. Extension check
    const ext = path.extname(targetPath).toLowerCase();
    if (!ALLOWED_DOC_EXTS.has(ext)) {
      return {
        success: false,
        output: null,
        error: `Document "${doc}" has unsupported extension "${ext}". Only text/markdown documents are permitted.`
      };
    }

    const content = await fs.readFile(targetPath, 'utf8');

    return {
      success: true,
      output: {
        skill_id,
        doc,
        content
      }
    };
  } catch (err: any) {
    return {
      success: false,
      output: null,
      error: err instanceof SandboxSecurityError ? err.message : `Failed to load skill doc: ${err.message}`
    };
  }
}
