#!/usr/bin/env node
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
 * Carefold End-to-End (E2E) Test Suite Runner
 * Executes all 276+ tests across Tiers 1–4 with full test discovery,
 * structured logging, progress indicators, and JSON report generation.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, '..', '..');

// ANSI Color Codes
const RESET = '\x1b[0m';
const BOLD = '\x1b[1m';
const GREEN = '\x1b[32m';
const RED = '\x1b[31m';
const YELLOW = '\x1b[33m';
const CYAN = '\x1b[36m';
const DIM = '\x1b[2m';

async function loadTestFilesFromDir(dirPath) {
  if (!fs.existsSync(dirPath)) return [];
  const entries = fs.readdirSync(dirPath, { withFileTypes: true });
  const files = entries
    .filter(e => e.isFile() && e.name.endsWith('.js') && !e.name.startsWith('_'))
    .map(e => path.join(dirPath, e.name))
    .sort();
  return files;
}

async function main() {
  const startTime = Date.now();
  console.log(`\n${BOLD}${CYAN}========================================================================${RESET}`);
  console.log(`${BOLD}${CYAN}      Carefold Phase 0 Launch Slice: Master E2E Test Suite Runner       ${RESET}`);
  console.log(`${BOLD}${CYAN}========================================================================${RESET}\n`);

  const results = {
    startedAt: new Date().toISOString(),
    total: 0,
    passed: 0,
    failed: 0,
    skipped: 0,
    durationMs: 0,
    tiers: {
      tier1: { name: 'Tier 1: Feature Coverage', total: 0, passed: 0, failed: 0, suites: [] },
      tier2: { name: 'Tier 2: Boundary & Edge Coverage', total: 0, passed: 0, failed: 0, suites: [] },
      tier3: { name: 'Tier 3: Pairwise Combinations', total: 0, passed: 0, failed: 0, suites: [] },
      tier4: { name: 'Tier 4: End-to-End Scenarios', total: 0, passed: 0, failed: 0, suites: [] },
    },
    failures: [],
  };

  const tierPlan = [
    { key: 'tier1', dir: path.join(__dirname, 'tier1_features'), label: 'Tier 1: Feature Coverage (F01–F24)' },
    { key: 'tier2', dir: path.join(__dirname, 'tier2_boundaries'), label: 'Tier 2: Boundary & Edge Cases' },
    { key: 'tier3', dir: path.join(__dirname, 'tier3_combinations'), label: 'Tier 3: Pairwise Combinations' },
    { key: 'tier4', dir: path.join(__dirname, 'tier4_scenarios'), label: 'Tier 4: Real-World Journey Scenarios' },
  ];

  for (const tier of tierPlan) {
    console.log(`${BOLD}${YELLOW}▶ ${tier.label}${RESET}`);
    const files = await loadTestFilesFromDir(tier.dir);

    for (const filePath of files) {
      const relPath = path.relative(REPO_ROOT, filePath);
      const fileUrl = pathToFileURL(filePath).href;

      try {
        const mod = await import(fileUrl);
        const suiteName = mod.name || path.basename(filePath, '.js');
        const tests = typeof mod.run === 'function' ? await mod.run() : [];

        const suiteResult = {
          file: relPath,
          name: suiteName,
          total: tests.length,
          passed: 0,
          failed: 0,
          tests: [],
        };

        process.stdout.write(`  ${DIM}•${RESET} ${suiteName} (${tests.length} tests) `);

        for (const test of tests) {
          const testStart = Date.now();
          results.total += 1;
          results.tiers[tier.key].total += 1;

          try {
            await test.fn();
            const elapsed = Date.now() - testStart;
            results.passed += 1;
            results.tiers[tier.key].passed += 1;
            suiteResult.passed += 1;
            suiteResult.tests.push({ id: test.id, name: test.name, status: 'pass', durationMs: elapsed });
          } catch (err) {
            const elapsed = Date.now() - testStart;
            results.failed += 1;
            results.tiers[tier.key].failed += 1;
            suiteResult.failed += 1;
            const failInfo = {
              id: test.id,
              name: test.name,
              suite: suiteName,
              file: relPath,
              error: err.message || String(err),
              stack: err.stack,
              durationMs: elapsed,
            };
            suiteResult.tests.push({ id: test.id, name: test.name, status: 'fail', error: failInfo.error, durationMs: elapsed });
            results.failures.push(failInfo);
          }
        }

        if (suiteResult.failed === 0) {
          console.log(`${GREEN}✓ [PASS ${suiteResult.passed}/${suiteResult.total}]${RESET}`);
        } else {
          console.log(`${RED}✗ [FAIL ${suiteResult.failed}/${suiteResult.total}]${RESET}`);
        }

        results.tiers[tier.key].suites.push(suiteResult);
      } catch (importErr) {
        console.log(`\n  ${RED}✗ Failed to import ${relPath}: ${importErr.message}${RESET}`);
        results.total += 1;
        results.failed += 1;
        results.failures.push({
          id: 'IMPORT-ERROR',
          name: `Import ${relPath}`,
          suite: path.basename(filePath),
          file: relPath,
          error: importErr.message,
          stack: importErr.stack,
        });
      }
    }
    console.log();
  }

  const totalDuration = Date.now() - startTime;
  results.durationMs = totalDuration;
  results.completedAt = new Date().toISOString();

  // Print Summary Table
  console.log(`${BOLD}${CYAN}========================================================================${RESET}`);
  console.log(`${BOLD}${CYAN}                           E2E TEST SUMMARY                             ${RESET}`);
  console.log(`${BOLD}${CYAN}========================================================================${RESET}`);
  console.log(` ${BOLD}Tier${RESET}                                ${BOLD}Passed${RESET}    ${BOLD}Failed${RESET}    ${BOLD}Total${RESET}    ${BOLD}Status${RESET}`);
  console.log(` ----------------------------------------------------------------------`);

  for (const [key, t] of Object.entries(results.tiers)) {
    const statusStr = t.failed === 0 ? `${GREEN}PASS${RESET}` : `${RED}FAIL${RESET}`;
    const namePad = t.name.padEnd(35);
    const passPad = String(t.passed).padStart(6);
    const failPad = String(t.failed).padStart(6);
    const totPad = String(t.total).padStart(6);
    console.log(` ${namePad} ${passPad}    ${failPad}    ${totPad}    ${statusStr}`);
  }

  console.log(` ----------------------------------------------------------------------`);
  const totalPassPad = String(results.passed).padStart(6);
  const totalFailPad = String(results.failed).padStart(6);
  const totalTotPad = String(results.total).padStart(6);
  const finalStatus = results.failed === 0 ? `${BOLD}${GREEN}100% PASSED${RESET}` : `${BOLD}${RED}FAILED${RESET}`;
  console.log(` ${BOLD}${'TOTAL'.padEnd(35)} ${totalPassPad}    ${totalFailPad}    ${totalTotPad}    ${finalStatus}`);
  console.log(`\n Total Execution Time: ${(totalDuration / 1000).toFixed(2)}s`);

  if (results.failures.length > 0) {
    console.log(`\n${BOLD}${RED}Failures Detail (${results.failures.length}):${RESET}`);
    for (const f of results.failures) {
      console.log(`\n  ${RED}[${f.id}] ${f.name}${RESET}`);
      console.log(`  File: ${f.file}`);
      console.log(`  Error: ${f.error}`);
    }
  }

  // Save report to tests/e2e/results.json
  const reportPath = path.join(__dirname, 'results.json');
  fs.writeFileSync(reportPath, JSON.stringify(results, null, 2), 'utf8');
  console.log(`\n Structured report written to: ${DIM}${path.relative(REPO_ROOT, reportPath)}${RESET}\n`);

  if (results.failed > 0) {
    process.exit(1);
  } else {
    process.exit(0);
  }
}

main().catch(err => {
  console.error('Runner fatal exception:', err);
  process.exit(1);
});
