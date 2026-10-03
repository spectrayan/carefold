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

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import path from 'node:path';
import fs from 'node:fs/promises';
import {
  executeAgentRun,
  checkSafetyRefusal,
  SAFE_REFUSAL_TEMPLATE,
  getClosedTool,
  executeTool,
  executeSkillDocs,
  executeWorkspaceNote,
  readAuditEvents,
  MockModelClient,
  type StreamChunk,
  type RunResult,
  type AuditEvent
} from '../src/index.js';
import { createTestWorkspace, cleanupTestWorkspace } from './helpers/test-workspace.js';

/**
 * Helper to collect all stream chunks and the final RunResult from executeAgentRun
 */
async function collectRun(
  gen: AsyncGenerator<StreamChunk, RunResult, void>
): Promise<{ chunks: StreamChunk[]; result: RunResult }> {
  const chunks: StreamChunk[] = [];
  let item = await gen.next();
  while (!item.done) {
    chunks.push(item.value);
    item = await gen.next();
  }
  return { chunks, result: item.value };
}

describe('07: Adversarial Hardening & Regression Suite', () => {
  let ws: string;

  beforeEach(async () => {
    ws = await createTestWorkspace();
  });

  afterEach(async () => {
    await cleanupTestWorkspace(ws);
  });

  // =========================================================================
  // 1. Skill-Docs Path Traversal & Sandboxing Hardening (CF-VULN-01 / Reviewer 2 Finding 1)
  // =========================================================================
  describe('Skill-Docs Path Traversal Hardening', () => {
    it('denies path traversal escaping skills/ directory via relative skill_id', async () => {
      // Create external directory with references/ outside skills/
      const outsideDir = path.join(ws, 'exfiltrated_dir', 'references');
      await fs.mkdir(outsideDir, { recursive: true });
      await fs.writeFile(
        path.join(outsideDir, 'secret_outside_skills.md'),
        '# CONFIDENTIAL DATA OUTSIDE SKILLS'
      );

      // Attempt access with relative skill_id containing ../
      const res = await executeSkillDocs(
        {
          skill_id: '../exfiltrated_dir',
          doc: 'secret_outside_skills.md'
        },
        {
          workspaceRoot: ws,
          agent: { id: 'visit-steward', skills: ['../exfiltrated_dir'] } as any
        }
      );

      expect(res.success).toBe(false);
      expect(res.output).toBeNull();
      expect(res.error).toMatch(/escapes|forbidden|invalid|access denied/i);
    });

    it('denies path traversal escaping skills/ via ../../attachments', async () => {
      const res = await executeSkillDocs(
        {
          skill_id: '../../attachments',
          doc: 'sample.txt'
        },
        {
          workspaceRoot: ws,
          agent: { id: 'visit-steward', skills: ['../../attachments'] } as any
        }
      );

      expect(res.success).toBe(false);
      expect(res.output).toBeNull();
    });

    it('denies path traversal via doc argument escaping skill references directory', async () => {
      const res = await executeSkillDocs(
        {
          skill_id: 'visit-prep',
          doc: '../../../../secret_outside.txt'
        },
        {
          workspaceRoot: ws,
          agent: { id: 'visit-steward', skills: ['visit-prep'] } as any
        }
      );

      expect(res.success).toBe(false);
      expect(res.output).toBeNull();
      expect(res.error).toMatch(/escapes allowed directory|File not found|forbidden/i);
    });

    it('denies null byte injection in doc parameter', async () => {
      const res = await executeSkillDocs(
        {
          skill_id: 'visit-prep',
          doc: 'agenda.md\0.txt'
        },
        {
          workspaceRoot: ws,
          agent: { id: 'visit-steward', skills: ['visit-prep'] } as any
        }
      );

      expect(res.success).toBe(false);
      expect(res.output).toBeNull();
      expect(res.error).toMatch(/Null byte detected/i);
    });

    it('allows legitimate access to declared skill reference document', async () => {
      const res = await executeSkillDocs(
        {
          skill_id: 'visit-prep',
          doc: 'agenda.md'
        },
        {
          workspaceRoot: ws,
          agent: { id: 'visit-steward', skills: ['visit-prep'] } as any
        }
      );

      expect(res.success).toBe(true);
      expect(res.output?.content).toContain('Appointment Questions');
    });
  });

  // =========================================================================
  // 2. Skill-Docs Fail-Closed Authorization (CF-VULN-02)
  // =========================================================================
  describe('Skill-Docs Fail-Closed Authorization', () => {
    it('denies access when context lacks agent entirely (fails closed)', async () => {
      const res = await executeSkillDocs(
        {
          skill_id: 'visit-prep',
          doc: 'agenda.md'
        },
        {
          workspaceRoot: ws
          // agent omitted
        }
      );

      expect(res.success).toBe(false);
      expect(res.output).toBeNull();
      expect(res.error).toMatch(/access denied|agent context/i);
    });

    it('denies access when agent.skills property is omitted / undefined', async () => {
      const res = await executeSkillDocs(
        {
          skill_id: 'visit-prep',
          doc: 'agenda.md'
        },
        {
          workspaceRoot: ws,
          agent: { id: 'sneaky-agent' } as any // skills array omitted
        }
      );

      expect(res.success).toBe(false);
      expect(res.output).toBeNull();
      expect(res.error).toMatch(/access denied|undeclared/i);
    });

    it('denies access when requested skill is not in agent.skills', async () => {
      const res = await executeSkillDocs(
        {
          skill_id: 'visit-prep',
          doc: 'agenda.md'
        },
        {
          workspaceRoot: ws,
          agent: { id: 'benefits-agent', skills: ['benefits-explainer'] } as any
        }
      );

      expect(res.success).toBe(false);
      expect(res.output).toBeNull();
      expect(res.error).toMatch(/access denied|not declared|undeclared/i);
    });
  });

  // =========================================================================
  // 3. Prototype Property Leak & Method Dispatch Traps (CF-VULN-03)
  // =========================================================================
  describe('Tool Registry Prototype Pollution Hardening', () => {
    it('getClosedTool returns undefined for built-in Object prototype properties', () => {
      const prototypeKeys = [
        'toString',
        'valueOf',
        'constructor',
        '__proto__',
        'hasOwnProperty',
        'isPrototypeOf',
        'propertyIsEnumerable'
      ];

      for (const key of prototypeKeys) {
        const tool = getClosedTool(key);
        expect(tool, `getClosedTool("${key}") must return undefined`).toBeUndefined();
      }
    });

    it('executeTool cleanly rejects prototype method names without uncaught TypeError', async () => {
      const prototypeKeys = ['toString', 'valueOf', 'constructor', '__proto__'];

      for (const key of prototypeKeys) {
        const res = await executeTool(key, {}, {
          workspaceRoot: ws,
          agent: { id: 'test', title: 'Test', version: '0.1.0', risk_class: 'wellness', skills: [] },
          effectiveTools: [],
          skills: []
        });

        expect(res.success, `executeTool("${key}") must fail cleanly`).toBe(false);
        expect(res.output).toBeNull();
        expect(res.error).toMatch(/not recognized|not available/i);
      }
    });
  });

  // =========================================================================
  // 4. Symlink Note Overwrite Defense (Reviewer 2 Finding 2)
  // =========================================================================
  describe('Workspace Note Symlink Overwrite Defense', () => {
    it('rejects writing note when target file already exists as a symlink pointing outside', async () => {
      const externalSensitiveFile = path.join(ws, 'critical_external_data.txt');
      await fs.writeFile(externalSensitiveFile, 'CRITICAL_EXTERNAL_DATA_DO_NOT_OVERWRITE', 'utf8');

      // Create malicious symlinks at potential notes resolution locations
      const notePathWorkspace = path.join(ws, 'workspace', 'notes', 'hijack.md');
      const notePathRoot = path.join(ws, 'notes', 'hijack.md');

      try {
        await fs.symlink(externalSensitiveFile, notePathWorkspace);
      } catch {}
      try {
        await fs.symlink(externalSensitiveFile, notePathRoot);
      } catch {}

      const res = await executeWorkspaceNote(
        {
          title: 'hijack',
          content: 'MALICIOUS_OVERWRITE_PAYLOAD'
        },
        {
          workspaceRoot: ws,
          agent: { id: 'visit-steward' } as any
        }
      );

      expect(res.success).toBe(false);

      // Verify the external target file was not overwritten
      const externalContent = await fs.readFile(externalSensitiveFile, 'utf8');
      expect(externalContent).toBe('CRITICAL_EXTERNAL_DATA_DO_NOT_OVERWRITE');
    });

    it('successfully creates note when target does not exist as symlink', async () => {
      const res = await executeWorkspaceNote(
        {
          title: 'appointment-checklist',
          content: '1. Ask about blood pressure tracking.\n2. Review lab tests.'
        },
        {
          workspaceRoot: ws,
          agent: { id: 'visit-steward' } as any
        }
      );

      expect(res.success).toBe(true);
      expect(res.output?.title).toBe('appointment-checklist');
    });
  });

  // =========================================================================
  // 5. Safety Refusal Gate Adversarial Hardening
  // =========================================================================
  describe('Safety Refusal Gate Adversarial Hardening', () => {
    it('refuses all clinical diagnostic assertions (canonical & variants)', () => {
      const diagnosticVectors = [
        // Canonical
        'Based on your symptoms you have pneumonia',
        'Patient is diagnosed with diabetes',
        'It looks like asthma',
        // Variants & Reviewer probe
        'I diagnose you with pneumonia',
        'You likely have pneumonia',
        'You probably have diabetes',
        'This appears to be bronchitis',
        'Based on your symptoms, you have lupus',
        "You have Alzheimer's",
        'You have leukemia',
        'My impression is ADHD',
        'Sounds like depression'
      ];

      for (const text of diagnosticVectors) {
        const res = checkSafetyRefusal(text);
        expect(res.refused, `Expected refusal for diagnostic text: "${text}"`).toBe(true);
        expect(res.reason).toBe('forbidden_intent:diagnose');
        expect(res.safeResponse).toBe(SAFE_REFUSAL_TEMPLATE);
      }
    });

    it('refuses all prescription and dosing formulations (canonical & variants with colons/delimiters)', () => {
      const dosingVectors = [
        // Canonical
        'Take 500 mg amoxicillin twice daily',
        'Recommended dosage: 10ml',
        'I prescribe ibuprofen',
        // Variants with colon, unit variations, and intervening medication names
        'Recommended dosage: 500mg',
        'Dosage: 10ml',
        'Prescribed: amoxicillin 500mg',
        'Increase dose to 50mg',
        'The recommended dosage of ibuprofen is 800mg',
        'The dosage of amoxicillin is 500mg',
        '100mcg twice daily orally'
      ];

      for (const text of dosingVectors) {
        const res = checkSafetyRefusal(text);
        expect(res.refused, `Expected refusal for dosing text: "${text}"`).toBe(true);
        expect(res.reason).toBe('forbidden_intent:dose');
        expect(res.safeResponse).toBe(SAFE_REFUSAL_TEMPLATE);
      }
    });

    it('refuses all emergency care evasion and diversion directives (canonical & variants)', () => {
      const triageVectors = [
        // Canonical
        'Do not go to the emergency room',
        'Avoid the ER, wait until tomorrow',
        'Cancel your 911 call',
        // Variants
        'Hang up on 911',
        'Cancel 911',
        'Do not call an ambulance',
        'No need to call an ambulance',
        'Stay home instead of going to the hospital',
        'Skip the emergency room'
      ];

      for (const text of triageVectors) {
        const res = checkSafetyRefusal(text);
        expect(res.refused, `Expected refusal for triage evasion text: "${text}"`).toBe(true);
        expect(res.reason).toBe('forbidden_intent:replace_emergency_care');
        expect(res.safeResponse).toBe(SAFE_REFUSAL_TEMPLATE);
      }
    });

    it('refuses all medication cessation directives (canonical & variants)', () => {
      const medicationVectors = [
        // Canonical
        'Stop taking your blood pressure medication',
        'Discontinue your insulin',
        // Variants
        'Stop taking your blood pressure pills',
        'Discontinue taking your blood pressure medication',
        'Cease your chemotherapy',
        'Stop taking lisinopril',
        'Do not take your medication',
        'Discontinue the medication',
        'Hold your metformin dose'
      ];

      for (const text of medicationVectors) {
        const res = checkSafetyRefusal(text);
        expect(res.refused, `Expected refusal for medication cessation: "${text}"`).toBe(true);
        expect(res.reason).toBe('forbidden_intent:instruct_stop_medication');
        expect(res.safeResponse).toBe(SAFE_REFUSAL_TEMPLATE);
      }
    });

    it('does NOT trigger false-positive refusals on legitimate wellness guidance and standard disclaimers', () => {
      const wellnessVectors = [
        'I am a wellness assistant, not a licensed clinician.',
        'If this is an emergency, contact local emergency services immediately.',
        'Do not change medication without consulting your prescribing doctor.',
        'Prepare questions for your doctor about your blood pressure.',
        'You can track your water intake and daily steps here.',
        'Here is a checklist of questions to bring to your clinical visit.'
      ];

      for (const text of wellnessVectors) {
        const res = checkSafetyRefusal(text);
        expect(res.refused, `False positive detected on wellness text: "${text}"`).toBe(false);
      }
    });
  });

  // =========================================================================
  // 6. In-Memory Audit Body Redaction on RunResult
  // =========================================================================
  describe('In-Memory Audit Body Redaction on RunResult', () => {
    it('strictly strips prompt and completion from RunResult.auditEvents by default (store_bodies: false)', async () => {
      const mockModel = new MockModelClient();
      mockModel.enqueueResponse({ text: 'CONFIDENTIAL_COMPLETION_NOTE_456' });

      const stream = executeAgentRun({
        agentId: 'visit-steward',
        workspaceDir: ws,
        prompt: 'CONFIDENTIAL_PATIENT_SSN_123_PROMPT',
        modelClient: mockModel
        // config omitted: defaults to audit.store_bodies: false
      });

      const { result } = await collectRun(stream);

      expect(result.text).toBe('CONFIDENTIAL_COMPLETION_NOTE_456');
      expect(result.refused).toBe(false);
      expect(result.auditEvents.length).toBeGreaterThan(0);

      // Verify each in-memory audit event strictly has NO prompt or completion
      for (const evt of result.auditEvents) {
        expect(evt.prompt, 'In-memory audit event must strip prompt').toBeUndefined();
        expect(evt.completion, 'In-memory audit event must strip completion').toBeUndefined();
        expect(Object.prototype.hasOwnProperty.call(evt, 'prompt')).toBe(false);
        expect(Object.prototype.hasOwnProperty.call(evt, 'completion')).toBe(false);
      }

      // Verify serialization of audit events does not leak sensitive strings
      const serialized = JSON.stringify(result.auditEvents);
      expect(serialized).not.toContain('CONFIDENTIAL_PATIENT_SSN_123_PROMPT');
      expect(serialized).not.toContain('CONFIDENTIAL_COMPLETION_NOTE_456');
    });

    it('strictly strips prompt and completion when config.audit.store_bodies is explicitly false', async () => {
      const mockModel = new MockModelClient();
      mockModel.enqueueResponse({ text: 'SENSITIVE_ASSISTANT_REPLY' });

      const stream = executeAgentRun({
        agentId: 'visit-steward',
        workspaceDir: ws,
        prompt: 'SENSITIVE_USER_QUERY',
        modelClient: mockModel,
        config: {
          audit: {
            store_bodies: false
          }
        }
      });

      const { result } = await collectRun(stream);
      const runEvent = result.auditEvents.find((e) => e.event === 'run');
      expect(runEvent).toBeDefined();
      expect(runEvent?.prompt).toBeUndefined();
      expect(runEvent?.completion).toBeUndefined();
      expect(Object.prototype.hasOwnProperty.call(runEvent, 'prompt')).toBe(false);
      expect(Object.prototype.hasOwnProperty.call(runEvent, 'completion')).toBe(false);

      // Verify on-disk audit log matches in-memory behavior
      const auditFile = path.join(ws, 'logs', 'audit.jsonl');
      const diskEvents = await readAuditEvents(auditFile);
      const diskRunEvent = diskEvents.find((e) => e.event === 'run');
      expect(diskRunEvent).toBeDefined();
      expect(diskRunEvent?.prompt).toBeUndefined();
      expect(diskRunEvent?.completion).toBeUndefined();
    });

    it('retains prompt and completion in RunResult.auditEvents only when store_bodies is explicitly true (positive control)', async () => {
      const mockModel = new MockModelClient();
      mockModel.enqueueResponse({ text: 'EXPLICIT_RETAINED_COMPLETION' });

      const stream = executeAgentRun({
        agentId: 'visit-steward',
        workspaceDir: ws,
        prompt: 'EXPLICIT_RETAINED_PROMPT',
        modelClient: mockModel,
        config: {
          audit: {
            store_bodies: true
          }
        }
      });

      const { result } = await collectRun(stream);
      const runEvent = result.auditEvents.find((e) => e.event === 'run');
      expect(runEvent).toBeDefined();
      expect(runEvent?.prompt).toBe('EXPLICIT_RETAINED_PROMPT');
      expect(runEvent?.completion).toBe('EXPLICIT_RETAINED_COMPLETION');

      // Verify on-disk log also retained them
      const auditFile = path.join(ws, 'logs', 'audit.jsonl');
      const diskEvents = await readAuditEvents(auditFile);
      const diskRunEvent = diskEvents.find((e) => e.event === 'run');
      expect(diskRunEvent).toBeDefined();
      expect(diskRunEvent?.prompt).toBe('EXPLICIT_RETAINED_PROMPT');
      expect(diskRunEvent?.completion).toBe('EXPLICIT_RETAINED_COMPLETION');
    });

    it('does not leak prompt in RunResult.auditEvents during safety refusal execution', async () => {
      const mockModel = new MockModelClient();
      mockModel.enqueueResponse({ text: 'Based on your symptoms you have pneumonia' });

      const stream = executeAgentRun({
        agentId: 'visit-steward',
        workspaceDir: ws,
        prompt: 'PATIENT_CONFIDENTIAL_SYMPTOMS_BEFORE_REFUSAL',
        modelClient: mockModel,
        config: {
          audit: {
            store_bodies: false
          }
        }
      });

      const { result } = await collectRun(stream);
      expect(result.refused).toBe(true);
      expect(result.text).toBe(SAFE_REFUSAL_TEMPLATE);
      expect(result.refusalReason).toBe('forbidden_intent:diagnose');

      const refuseEvent = result.auditEvents.find((e) => e.event === 'refuse');
      expect(refuseEvent).toBeDefined();
      expect(refuseEvent?.allowed).toBe(false);
      expect(refuseEvent?.prompt).toBeUndefined();
      expect(refuseEvent?.completion).toBeUndefined();

      const serialized = JSON.stringify(result.auditEvents);
      expect(serialized).not.toContain('PATIENT_CONFIDENTIAL_SYMPTOMS_BEFORE_REFUSAL');
    });
  });
});
