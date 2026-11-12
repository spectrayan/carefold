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

import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import type { Config } from 'tailwindcss';

const DIST_GLOB_SUFFIX = 'dist/**/*.{js,mjs}';

type TokensModuleCompat = {
  yarvelleUiContentGlob?: (rootDir?: string) => string;
};

type PresetModuleCompat = {
  yarvellePreset?: Config;
  default?: Config;
};

interface YarvelleUiPackageHandles {
  distDir: string;
  req: NodeRequire;
}

function resolveYarvelleUiPackage(): YarvelleUiPackageHandles | null {
  const candidatePkgJsons = [
    path.resolve(process.cwd(), 'package.json'),
    path.resolve(process.cwd(), 'frontend', 'package.json')
  ];

  for (const pkgJsonPath of candidatePkgJsons) {
    if (!fs.existsSync(pkgJsonPath)) {
      continue;
    }
    try {
      const req = createRequire(pathToFileURL(pkgJsonPath).href);
      // `./styles.css` is an unconditional string export in both published
      // @yarvelle/ui 0.1.x and local @yarvelle/ui >= 0.2.4, avoiding jiti CJS
      // export-map failures on ESM-only `./tailwind-preset` / `./tokens` subpaths.
      const stylesEntry = req.resolve('@yarvelle/ui/styles.css');
      return {
        distDir: path.dirname(stylesEntry),
        req
      };
    } catch {
      // Try next workspace anchor
    }
  }

  return null;
}

function loadDistModule<T>(handles: YarvelleUiPackageHandles, relativeFromDist: string): T {
  const targetPath = path.join(handles.distDir, relativeFromDist);
  try {
    return handles.req(targetPath) as T;
  } catch (err: unknown) {
    const code = (err as { code?: string } | null)?.code;
    if (code === 'ERR_REQUIRE_ESM') {
      const twReq = createRequire(handles.req.resolve('tailwindcss'));
      const createJiti = twReq('jiti') as (
        id: string,
        opts?: Record<string, unknown>
      ) => (target: string) => T;
      const jitiLoader = createJiti(targetPath, { interopDefault: false });
      return jitiLoader(targetPath);
    }
    throw err;
  }
}

const uiHandles = resolveYarvelleUiPackage();

const loadedPresetModule: PresetModuleCompat = uiHandles
  ? loadDistModule<PresetModuleCompat>(uiHandles, 'tokens/tailwind-preset.js')
  : {};

const loadedTokensModule: TokensModuleCompat = uiHandles
  ? loadDistModule<TokensModuleCompat>(uiHandles, 'tokens/index.js')
  : {};

const rawYarvellePreset: Config =
  loadedPresetModule.yarvellePreset ??
  loadedPresetModule.default ?? {
    content: []
  };

function normalizePosixPath(input: string): string {
  const forward = input.trim().replace(/\\/g, '/');
  if (forward === '/') {
    return '/';
  }
  return forward.replace(/\/+$/, '');
}

/**
 * Resolves the Tailwind `content` glob for `@yarvelle/ui` compiled ESM bundles
 * across both `@yarvelle/ui` >= 0.2.4 (which exports `yarvelleUiContentGlob`)
 * and published `@yarvelle/ui` 0.1.x (where we resolve `@yarvelle/ui`'s dist
 * directory via Node module resolution).
 */
export function resolveYarvelleUiContentGlob(
  rootDir?: string,
  tokensMod: TokensModuleCompat = loadedTokensModule
): string {
  if (typeof tokensMod.yarvelleUiContentGlob === 'function') {
    return tokensMod.yarvelleUiContentGlob(rootDir);
  }

  if (typeof rootDir === 'string' && rootDir.trim().length > 0) {
    const normalized = normalizePosixPath(rootDir);
    if (
      normalized.endsWith('/@yarvelle/ui/dist') ||
      normalized === 'dist' ||
      normalized === './dist'
    ) {
      return `${normalized}/**/*.{js,mjs}`;
    }
    if (normalized.endsWith('/@yarvelle/ui')) {
      return `${normalized}/${DIST_GLOB_SUFFIX}`;
    }
    const prefix = normalized === '/' ? '' : normalized;
    return `${prefix}/node_modules/@yarvelle/ui/${DIST_GLOB_SUFFIX}`;
  }

  const resolvedHandles = resolveYarvelleUiPackage();
  if (resolvedHandles) {
    const posixDist = resolvedHandles.distDir.replace(/\\/g, '/');
    return `${posixDist}/**/*.{js,mjs}`;
  }

  return `./node_modules/@yarvelle/ui/${DIST_GLOB_SUFFIX}`;
}

/**
 * Returns `yarvellePreset` unchanged when tokens already live under `theme.extend`
 * (`@yarvelle/ui` >= 0.2.4 / `yarvelle-core#59`), or lifts top-level `theme`
 * entries into `theme.extend` on published `@yarvelle/ui` 0.1.x so Tailwind's
 * base color/spacing palette is never wiped out.
 */
export function resolveYarvellePreset(preset: Config = rawYarvellePreset): Config {
  const theme = preset.theme;
  if (!theme) {
    return preset;
  }

  const themeKeys = Object.keys(theme);
  if (theme.extend && themeKeys.every((key) => key === 'extend')) {
    return preset;
  }

  const { extend: existingExtend, ...topLevelTheme } = theme;
  return {
    ...preset,
    theme: {
      extend: {
        ...topLevelTheme,
        ...(existingExtend ?? {})
      }
    }
  };
}

export const compatibleYarvellePreset: Config = resolveYarvellePreset(rawYarvellePreset);
