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

'use client';

import React, { useState, useRef, DragEvent, ChangeEvent } from 'react';

export interface AttachedFile {
  filename: string;
  path: string;
  size_bytes: number;
  format: 'text' | 'pdf';
}

export interface AttachmentUploaderProps {
  attachedFiles: AttachedFile[];
  onAttach: (file: AttachedFile) => void;
  onRemove: (filename: string) => void;
  disabled?: boolean;
}

const ALLOWED_EXTENSIONS = ['.txt', '.md', '.json', '.csv', '.tsv', '.yaml', '.yml', '.pdf'];
const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB

export function AttachmentUploader({
  attachedFiles,
  onAttach,
  onRemove,
  disabled = false
}: AttachmentUploaderProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const validateFile = (file: File): string | null => {
    const ext = '.' + (file.name.split('.').pop() || '').toLowerCase();
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      return `Unsupported file format "${ext}". Only PDF and plain text documents (.txt, .md, .json, .csv) are permitted.`;
    }
    if (file.size > MAX_FILE_SIZE) {
      return `File size exceeds 10MB limit (${(file.size / (1024 * 1024)).toFixed(1)}MB).`;
    }
    return null;
  };

  const handleUpload = async (file: File) => {
    setErrorMessage(null);
    const validationError = validateFile(file);
    if (validationError) {
      setErrorMessage(validationError);
      return;
    }

    try {
      setIsUploading(true);
      const formData = new FormData();
      formData.append('file', file);

      const res = await fetch('/api/v1/attachments', {
        method: 'POST',
        body: formData
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.error || `Upload failed with status ${res.status}`);
      }

      const result = await res.json();
      const ext = '.' + (file.name.split('.').pop() || '').toLowerCase();
      onAttach({
        filename: result.filename || file.name,
        path: result.path || `attachments/${file.name}`,
        size_bytes: file.size,
        format: ext === '.pdf' ? 'pdf' : 'text'
      });
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to upload attachment.');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (disabled || isUploading) return;
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleUpload(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (disabled || isUploading) return;
    if (e.target.files && e.target.files.length > 0) {
      handleUpload(e.target.files[0]);
    }
  };

  return (
    <div className="w-full space-y-2">
      {/* Attached Files List */}
      {attachedFiles.length > 0 && (
        <div data-testid="attached-files-list" className="flex flex-wrap gap-2">
          {attachedFiles.map((file) => (
            <div
              key={file.filename}
              data-testid="attached-file-chip"
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs bg-zinc-100 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-700 text-zinc-800 dark:text-zinc-200"
            >
              <span className={`px-1 rounded text-xs font-semibold uppercase ${file.format === 'pdf' ? 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300' : 'bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300'}`}>
                {file.format.toUpperCase()}
              </span>
              <span className="font-medium max-w-[150px] truncate" title={file.filename}>
                {file.filename}
              </span>
              <span className="text-zinc-600 dark:text-zinc-400 text-xs">
                ({(file.size_bytes / 1024).toFixed(1)} KB)
              </span>
              <button
                type="button"
                data-testid={`remove-attachment-${file.filename}`}
                onClick={() => onRemove(file.filename)}
                disabled={disabled}
                className="min-w-[44px] min-h-[44px] -my-2.5 -mr-1.5 p-2 inline-flex items-center justify-center text-sm font-semibold text-zinc-600 hover:text-rose-600 dark:hover:text-rose-400 focus:outline-none focus:ring-2 focus:ring-blue-500 rounded cursor-pointer"
                aria-label={`Remove ${file.filename}`}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Upload Drop Zone & Trigger Button */}
      <div
        data-testid="attachment-dropzone"
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        className={`flex items-center gap-2 text-xs transition-colors ${isDragging ? 'border-2 border-dashed border-blue-500 bg-blue-50/30 dark:bg-blue-950/20 p-2 rounded-lg' : ''}`}
      >
        <input
          ref={fileInputRef}
          type="file"
          data-testid="attachment-file-input"
          className="hidden"
          accept=".txt,.md,.json,.csv,.tsv,.yaml,.yml,.pdf"
          onChange={handleFileChange}
          disabled={disabled || isUploading}
        />

        <button
          type="button"
          data-testid="attach-file-button"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled || isUploading}
          className="inline-flex items-center gap-1.5 min-h-[44px] px-3 py-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-750 text-zinc-700 dark:text-zinc-300 font-medium disabled:opacity-50 disabled:cursor-not-allowed shadow-sm transition-all"
        >
          {isUploading ? (
            <>
              <svg className="w-3.5 h-3.5 animate-spin text-blue-500" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              <span>Attaching...</span>
            </>
          ) : (
            <>
              <svg className="w-3.5 h-3.5 text-zinc-600 dark:text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
              </svg>
              <span>Attach file</span>
            </>
          )}
        </button>

        <span className="text-xs text-zinc-600 dark:text-zinc-400">
          PDF or Text (max 10MB, saved locally to attachments/)
        </span>
      </div>

      {/* Error Message Banner */}
      {errorMessage && (
        <div data-testid="attachment-error-banner" className="flex items-center justify-between p-2 rounded-md bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900 text-rose-700 dark:text-rose-300 text-xs">
          <span>{errorMessage}</span>
          <button type="button" onClick={() => setErrorMessage(null)} className="ml-2 font-bold text-rose-600">×</button>
        </div>
      )}
    </div>
  );
}
