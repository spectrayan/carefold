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

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import path from 'node:path';
import fs from 'node:fs/promises';
import {
  executeAttachRead,
  executeWorkspaceNote,
  executeSkillDocs,
  getClosedTool,
  executeTool
} from '../src/tools/index.js';
import { createTestWorkspace, cleanupTestWorkspace } from './helpers/test-workspace.js';

describe('Closed Tools Sandbox & Security', () => {
  let ws: string;

  beforeEach(async () => {
    ws = await createTestWorkspace();
  });

  afterEach(async () => {
    await cleanupTestWorkspace(ws);
  });

  describe('attach-read', () => {
    it('reads plain text file within attachments directory', async () => {
      const res = await executeAttachRead({ path: 'sample.txt' }, { workspaceDir: ws });
      expect(res.success).toBe(true);
      expect(res.output.content).toContain('Insurance Plan Summary');
      expect(res.output.format).toBe('text');
    });

    it('extracts text from PDF attachment', async () => {
      const res = await executeAttachRead({ path: 'sample.pdf' }, { workspaceDir: ws });
      expect(res.success).toBe(true);
      expect(res.output.format).toBe('pdf');
      expect(res.output.content).toContain('Plan Summary Benefits Overview');
    });

    it('rejects path traversal attempting to escape attachments directory', async () => {
      const res = await executeAttachRead({ path: '../../etc/passwd' }, { workspaceDir: ws });
      expect(res.success).toBe(false);
      expect(res.error).toMatch(/Path traversal forbidden/i);
    });

    it('rejects null byte injection in attachment path', async () => {
      const res = await executeAttachRead({ path: 'sample.txt\0.pdf' }, { workspaceDir: ws });
      expect(res.success).toBe(false);
      expect(res.error).toMatch(/Null byte detected/i);
    });

    it('rejects non-text / non-PDF binary files', async () => {
      await fs.writeFile(path.join(ws, 'attachments', 'malware.exe'), Buffer.from([0x4d, 0x5a]));
      const res = await executeAttachRead({ path: 'malware.exe' }, { workspaceDir: ws });
      expect(res.success).toBe(false);
      expect(res.error).toMatch(/Unsupported file format/i);
    });

    it('returns error when attachment does not exist', async () => {
      const res = await executeAttachRead({ path: 'non_existent.txt' }, { workspaceDir: ws });
      expect(res.success).toBe(false);
      expect(res.error).toMatch(/File not found/i);
    });
  });

  describe('workspace-note', () => {
    it('writes markdown note with frontmatter metadata', async () => {
      const res = await executeWorkspaceNote(
        { title: 'doctor-prep', content: 'Ask about dosage adjustments' },
        { workspaceDir: ws, agent: { id: 'visit-steward' } }
      );
      expect(res.success).toBe(true);
      expect(res.output.title).toBe('doctor-prep');
      expect(res.output.bytes_written).toBeGreaterThan(0);

      // Verify file on disk
      const notePath = path.join(ws, res.output.path);
      const content = await fs.readFile(notePath, 'utf8');
      expect(content).toContain('title: "doctor-prep"');
      expect(content).toContain('agent_id: "visit-steward"');
      expect(content).toContain('Ask about dosage adjustments');
    });

    it('sanitizes title to prevent directory traversal', async () => {
      const res = await executeWorkspaceNote(
        { title: '../../evil-note', content: 'malicious payload' },
        { workspaceDir: ws }
      );
      expect(res.success).toBe(true);
      expect(res.output.title).toBe('evil-note');

      // Verify it was NOT written outside notes directory
      const evilPath = path.join(ws, 'evil-note.md');
      const existsOutside = await fs.stat(evilPath).catch(() => null);
      expect(existsOutside).toBeNull();
    });

    it('overwrites note with matching title', async () => {
      await executeWorkspaceNote(
        { title: 'daily-log', content: 'Initial log content' },
        { workspaceDir: ws }
      );
      const res = await executeWorkspaceNote(
        { title: 'daily-log', content: 'Updated log content' },
        { workspaceDir: ws }
      );
      expect(res.success).toBe(true);

      const notePath = path.join(ws, res.output.path);
      const content = await fs.readFile(notePath, 'utf8');
      expect(content).toContain('Updated log content');
      expect(content).not.toContain('Initial log content');
    });
  });

  describe('skill-docs', () => {
    it('reads reference document from skill references directory', async () => {
      const res = await executeSkillDocs(
        { skill_id: 'visit-prep', doc: 'agenda.md' },
        { workspaceDir: ws, agent: { id: 'visit-steward', skills: ['visit-prep'] } }
      );
      expect(res.success).toBe(true);
      expect(res.output.content).toContain('# Appointment Questions');
    });

    it('rejects path traversal attempting to escape skill references directory', async () => {
      const res = await executeSkillDocs(
        { skill_id: 'visit-prep', doc: '../SKILL.md' },
        { workspaceDir: ws, agent: { id: 'visit-steward', skills: ['visit-prep'] } }
      );
      expect(res.success).toBe(false);
      expect(res.error).toMatch(/Path traversal forbidden/i);
    });

    it('rejects access to skill not declared on agent (CF-S46)', async () => {
      const res = await executeSkillDocs(
        { skill_id: 'benefits-explainer', doc: 'copay.md' },
        { workspaceDir: ws, agent: { id: 'visit-steward', skills: ['visit-prep'] } }
      );
      expect(res.success).toBe(false);
      expect(res.error).toMatch(/Access denied: Skill "benefits-explainer" is not declared/i);
    });

    it('returns error when reference document does not exist', async () => {
      const res = await executeSkillDocs(
        { skill_id: 'visit-prep', doc: 'missing.md' },
        { workspaceDir: ws, agent: { id: 'visit-steward', skills: ['visit-prep'] } }
      );
      expect(res.success).toBe(false);
      expect(res.error).toMatch(/File not found/i);
    });
  });

  describe('Security & Sandboxing Hardening', () => {
    it('rejects relative path traversal in skill_id (CF-VULN-01)', async () => {
      const res = await executeSkillDocs(
        { skill_id: '../external_dir', doc: 'guide.md' },
        { workspaceDir: ws, agent: { id: 'visit-steward', skills: ['../external_dir'] } }
      );
      expect(res.success).toBe(false);
      expect(res.error).toMatch(/Path traversal forbidden/i);
    });

    it('rejects access to skill docs when agent is omitted (CF-VULN-02)', async () => {
      const res = await executeSkillDocs(
        { skill_id: 'visit-prep', doc: 'agenda.md' },
        { workspaceDir: ws } // no agent
      );
      expect(res.success).toBe(false);
      expect(res.error).toMatch(/Access denied/i);
    });

    it('rejects access to skill docs when agent.skills is omitted (CF-VULN-02)', async () => {
      const res = await executeSkillDocs(
        { skill_id: 'visit-prep', doc: 'agenda.md' },
        { workspaceDir: ws, agent: { id: 'visit-steward' } } // no skills array
      );
      expect(res.success).toBe(false);
      expect(res.error).toMatch(/Access denied/i);
    });

    it('getClosedTool returns undefined for prototype properties (CF-VULN-03)', () => {
      expect(getClosedTool('toString')).toBeUndefined();
      expect(getClosedTool('constructor')).toBeUndefined();
      expect(getClosedTool('__proto__')).toBeUndefined();
      expect(getClosedTool('valueOf')).toBeUndefined();
    });

    it('executeTool returns safe error without uncaught TypeError on prototype methods (CF-VULN-03)', async () => {
      const res = await executeTool('toString', {}, { workspaceDir: ws } as any);
      expect(res.success).toBe(false);
      expect(res.error).toMatch(/not recognized or not available/i);
    });

    it('prevents symlink overwrite in workspace-note (Finding 2)', async () => {
      const notesDir = path.join(ws, 'notes');
      await fs.mkdir(notesDir, { recursive: true });
      const outsideFile = path.join(ws, 'secret.txt');
      await fs.writeFile(outsideFile, 'ORIGINAL_SECRET');

      const symlinkPathRoot = path.join(notesDir, 'symlink-note.md');
      await fs.symlink(outsideFile, symlinkPathRoot);

      const wsNotesDir = path.join(ws, 'workspace', 'notes');
      await fs.mkdir(wsNotesDir, { recursive: true });
      const symlinkPathWs = path.join(wsNotesDir, 'symlink-note.md');
      await fs.symlink(outsideFile, symlinkPathWs);

      const res = await executeWorkspaceNote(
        { title: 'symlink-note', content: 'ATTACK_OVERWRITE' },
        { workspaceDir: ws, agent: { id: 'visit-steward' } }
      );

      expect(res.success).toBe(false);
      expect(res.error).toMatch(/Path traversal forbidden/i);

      // Verify the target outside file was untouched
      const outsideContent = await fs.readFile(outsideFile, 'utf8');
      expect(outsideContent).toBe('ORIGINAL_SECRET');
    });
  });
});
