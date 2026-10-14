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

export enum ExitCodes {
  SUCCESS = 0,
  USER_ERROR = 1,
  INTERNAL_ERROR = 2
}

export class CliError extends Error {
  public exitCode: number;
  constructor(message: string, exitCode = ExitCodes.USER_ERROR) {
    super(message);
    this.name = 'CliError';
    this.exitCode = exitCode;
  }
}
