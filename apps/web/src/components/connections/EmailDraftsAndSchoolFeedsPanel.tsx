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

'use client';

import React, { useState } from 'react';
import {
  Mail,
  CheckCircle2,
  Download,
  ExternalLink,
  Calendar,
  RefreshCw,
  ShieldAlert,
  Plus,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/utils';
import type {
  CreateEmailDraftPayload,
  CreateSchoolIcsFeedPayload,
  EmailDraftItem,
  GmailStagedCandidate,
  SchoolIcsFeedItem,
} from '@/types/routinesAndCompanion';

export interface EmailDraftsAndSchoolFeedsPanelProps {
  gmailCandidates: GmailStagedCandidate[];
  emailDrafts: EmailDraftItem[];
  schoolFeeds: SchoolIcsFeedItem[];
  onConfirmGmailCandidate?: (candidateIndex: number) => void | Promise<void>;
  onCreateEmailDraft?: (
    payload: CreateEmailDraftPayload
  ) => void | Promise<void>;
  onDownloadEmailEml?: (draftId: string) => void | Promise<void>;
  onCreateSchoolFeed?: (
    payload: CreateSchoolIcsFeedPayload
  ) => void | Promise<void>;
  onSyncSchoolFeed?: (feedId: string) => void | Promise<void>;
  className?: string;
}

export function EmailDraftsAndSchoolFeedsPanel({
  gmailCandidates,
  emailDrafts,
  schoolFeeds,
  onConfirmGmailCandidate,
  onCreateEmailDraft,
  onDownloadEmailEml,
  onCreateSchoolFeed,
  onSyncSchoolFeed,
  className,
}: EmailDraftsAndSchoolFeedsPanelProps) {
  const [recipient, setRecipient] = useState('records@pediatrics.example.org');
  const [subject, setSubject] = useState('Immunization Form Request');
  const [body, setBody] = useState(
    'Hello, could you please share the signed school immunization certificate?'
  );

  const [feedLabel, setFeedLabel] = useState('Oakridge Elementary Calendar');
  const [feedUrl, setFeedUrl] = useState(
    'https://calendar.oakridge.edu/school-events.ics'
  );

  const handleCreateDraft = async (e: React.FormEvent) => {
    e.preventDefault();
    await onCreateEmailDraft?.({
      recipient: recipient.trim(),
      subject: subject.trim(),
      body: body.trim(),
      category: 'records_request',
    });
  };

  const handleCreateFeed = async (e: React.FormEvent) => {
    e.preventDefault();
    await onCreateSchoolFeed?.({
      label: feedLabel.trim(),
      feed_url: feedUrl.trim(),
    });
  };

  return (
    <div
      data-testid="email-drafts-and-school-feeds-panel"
      className={cn('space-y-8', className)}
    >
      {/* Section 1: Gmail Read-Only Confirm Queue (AU-59) */}
      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-bold text-[var(--cf-fg)]">
              Gmail Read-Only Confirm Queue (Label-Filtered)
            </h3>
            <p className="text-xs text-[var(--cf-fg-muted)]">
              Candidate appointments and Google Classroom guardian digests require explicit user confirmation before saving.
            </p>
          </div>
          <span
            data-testid="gmail-readonly-scope-badge"
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-mono font-semibold bg-blue-50 dark:bg-blue-950/30 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800/60"
          >
            Scope: gmail.readonly (No Send Scope)
          </span>
        </div>

        {gmailCandidates.length === 0 ? (
          <Card
            data-testid="gmail-candidates-empty"
            className="p-4 text-xs text-[var(--cf-fg-muted)] border border-[var(--cf-border)] shadow-sm"
          >
            No unconfirmed Gmail candidate items in the staging queue.
          </Card>
        ) : (
          <div data-testid="gmail-candidates-list" className="space-y-3">
            {gmailCandidates.map((item) => (
              <Card
                key={item.index}
                data-testid={`gmail-candidate-card-${item.index}`}
                className="p-4 flex flex-wrap items-center justify-between gap-4 border border-[var(--cf-border)] shadow-sm"
              >
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="px-2 py-0.5 rounded text-xs font-bold uppercase bg-[var(--cf-surface-2)] border border-[var(--cf-border)] text-[var(--cf-fg)]">
                      {item.record_type}
                    </span>
                    <h4 className="text-sm font-bold text-[var(--cf-fg)]">
                      {item.title}
                    </h4>
                    <span
                      data-testid={`gmail-candidate-taint-${item.index}`}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-amber-50 dark:bg-amber-950/30 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-800/60"
                    >
                      <ShieldAlert className="w-3 h-3 shrink-0" />
                      Untrusted ({item.trust})
                    </span>
                  </div>

                  <p className="text-xs text-[var(--cf-fg-muted)]">
                    {item.summary}
                  </p>

                  <p
                    data-testid={`gmail-candidate-provenance-${item.index}`}
                    className="text-xs font-medium text-emerald-700 dark:text-emerald-300"
                  >
                    {item.source_display}
                  </p>
                </div>

                <div>
                  {item.confirmed ? (
                    <span
                      data-testid={`gmail-confirmed-badge-${item.index}`}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60"
                    >
                      <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                      Confirmed
                    </span>
                  ) : (
                    <Button
                      size="sm"
                      variant="primary"
                      data-testid={`gmail-confirm-btn-${item.index}`}
                      leftIcon={<CheckCircle2 className="w-3.5 h-3.5" />}
                      onClick={() => onConfirmGmailCandidate?.(item.index)}
                    >
                      Confirm &amp; Save
                    </Button>
                  )}
                </div>
              </Card>
            ))}
          </div>
        )}
      </section>

      {/* Section 2: Email Drafts (No Auto-Send, AU-60) */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-bold text-[var(--cf-fg)]">
              Local Email Drafts (Clinic, School &amp; Insurer)
            </h3>
            <p className="text-xs text-[var(--cf-fg-muted)]">
              Carefold prepares structured drafts locally; you review and send from your own mail app.
            </p>
          </div>
          <span
            data-testid="email-no-autosend-badge"
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60"
          >
            <Mail className="w-3.5 h-3.5 shrink-0" />
            No Auto-Send (User Sends from Mail Client)
          </span>
        </div>

        {emailDrafts.length > 0 && (
          <div data-testid="email-drafts-list" className="space-y-3">
            {emailDrafts.map((draft) => (
              <Card
                key={draft.id}
                data-testid={`email-draft-card-${draft.id}`}
                className="p-4 flex flex-wrap items-center justify-between gap-4 border border-[var(--cf-border)] shadow-sm"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <h4 className="text-sm font-bold text-[var(--cf-fg)]">
                      {draft.subject}
                    </h4>
                    <span className="text-xs font-mono text-[var(--cf-fg-muted)]">
                      To: {draft.recipient}
                    </span>
                  </div>
                  <p className="text-xs text-[var(--cf-fg-muted)] line-clamp-2">
                    {draft.body}
                  </p>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <a
                    href={draft.mailto_uri}
                    data-testid={`email-mailto-link-${draft.id}`}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-[var(--cf-surface-2)] border border-[var(--cf-border)] text-[var(--cf-fg)] hover:bg-emerald-50 dark:hover:bg-emerald-950/30 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  >
                    <ExternalLink className="w-3.5 h-3.5" />
                    Open in Mail App (mailto:)
                  </a>
                  <Button
                    size="sm"
                    variant="outline"
                    data-testid={`email-download-eml-btn-${draft.id}`}
                    leftIcon={<Download className="w-3.5 h-3.5" />}
                    onClick={() => onDownloadEmailEml?.(draft.id)}
                  >
                    Download .eml
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        )}

        <Card className="p-4 border border-[var(--cf-border)] shadow-sm">
          <form
            data-testid="create-email-draft-form"
            onSubmit={handleCreateDraft}
            className="space-y-3"
          >
            <h4 className="text-xs font-bold uppercase tracking-wider text-[var(--cf-fg-muted)]">
              Prepare New Email Draft
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label
                  htmlFor="draft-recipient-input"
                  className="block text-xs font-medium text-[var(--cf-fg-muted)] mb-1"
                >
                  Recipient Email
                </label>
                <input
                  id="draft-recipient-input"
                  type="email"
                  data-testid="draft-recipient-input"
                  value={recipient}
                  onChange={(e) => setRecipient(e.target.value)}
                  className="w-full px-3 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>
              <div>
                <label
                  htmlFor="draft-subject-input"
                  className="block text-xs font-medium text-[var(--cf-fg-muted)] mb-1"
                >
                  Subject
                </label>
                <input
                  id="draft-subject-input"
                  type="text"
                  data-testid="draft-subject-input"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  className="w-full px-3 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>
            </div>
            <div>
              <label
                htmlFor="draft-body-input"
                className="block text-xs font-medium text-[var(--cf-fg-muted)] mb-1"
              >
                Draft Body
              </label>
              <textarea
                id="draft-body-input"
                rows={2}
                data-testid="draft-body-input"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                className="w-full px-3 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </div>
            <div className="flex justify-end">
              <Button
                type="submit"
                size="sm"
                variant="primary"
                data-testid="create-email-draft-submit-btn"
                leftIcon={<Plus className="w-3.5 h-3.5" />}
              >
                Save Local Draft
              </Button>
            </div>
          </form>
        </Card>
      </section>

      {/* Section 3: Child School Calendar .ics Feeds (AU-61) */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-bold text-[var(--cf-fg)]">
              Child School Calendar (.ics) Feeds
            </h3>
            <p className="text-xs text-[var(--cf-fg-muted)]">
              Sync school holidays, nurse physical deadlines, and sports physical dates into family care reminders.
            </p>
          </div>
        </div>

        {schoolFeeds.length > 0 && (
          <div data-testid="school-feeds-list" className="space-y-3">
            {schoolFeeds.map((feed) => (
              <Card
                key={feed.id}
                data-testid={`school-feed-card-${feed.id}`}
                className="p-4 flex flex-wrap items-center justify-between gap-4 border border-[var(--cf-border)] shadow-sm"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Calendar className="w-4 h-4 text-emerald-600 shrink-0" />
                    <h4 className="text-sm font-bold text-[var(--cf-fg)]">
                      {feed.label}
                    </h4>
                    <span
                      data-testid={`school-feed-events-${feed.id}`}
                      className="px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60"
                    >
                      {feed.events_synced} events synced
                    </span>
                  </div>
                  <p className="text-xs font-mono text-[var(--cf-fg-muted)]">
                    {feed.feed_url}
                  </p>
                </div>

                <Button
                  size="sm"
                  variant="secondary"
                  data-testid={`school-feed-sync-btn-${feed.id}`}
                  leftIcon={<RefreshCw className="w-3.5 h-3.5" />}
                  onClick={() => onSyncSchoolFeed?.(feed.id)}
                >
                  Sync Feed
                </Button>
              </Card>
            ))}
          </div>
        )}

        <Card className="p-4 border border-[var(--cf-border)] shadow-sm">
          <form
            data-testid="create-school-feed-form"
            onSubmit={handleCreateFeed}
            className="flex flex-wrap items-end gap-3"
          >
            <div className="flex-1 min-w-[200px]">
              <label
                htmlFor="school-feed-label-input"
                className="block text-xs font-medium text-[var(--cf-fg-muted)] mb-1"
              >
                School Calendar Label
              </label>
              <input
                id="school-feed-label-input"
                type="text"
                data-testid="school-feed-label-input"
                value={feedLabel}
                onChange={(e) => setFeedLabel(e.target.value)}
                className="w-full px-3 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </div>
            <div className="flex-1 min-w-[240px]">
              <label
                htmlFor="school-feed-url-input"
                className="block text-xs font-medium text-[var(--cf-fg-muted)] mb-1"
              >
                HTTPS .ics Feed URL
              </label>
              <input
                id="school-feed-url-input"
                type="url"
                data-testid="school-feed-url-input"
                value={feedUrl}
                onChange={(e) => setFeedUrl(e.target.value)}
                className="w-full px-3 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs font-mono text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </div>
            <Button
              type="submit"
              size="sm"
              variant="primary"
              data-testid="create-school-feed-submit-btn"
              leftIcon={<Plus className="w-3.5 h-3.5" />}
            >
              Subscribe .ics Feed
            </Button>
          </form>
        </Card>
      </section>
    </div>
  );
}
