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

import React, { useState, useMemo } from 'react';
import {
  Calendar,
  Filter,
  Pencil,
  Trash2,
  Loader2,
  AlertTriangle,
  Activity,
  Heart,
  Droplets,
  Wind,
  Scale,
  Thermometer,
} from 'lucide-react';
import { Card } from '../../components/ui/Card';
import { Button } from '../../components/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '../../components/ui/Dialog';
import { updateVitalReading, deleteVitalReading } from '../../lib/vitalsClient';
import type { VitalsObservationItem } from '../../types/vitals';

export interface VitalsHistoryTableProps {
  observations: VitalsObservationItem[];
  profileId: string;
  onRefresh: () => void;
  hideWeight?: boolean;
}

export function VitalsHistoryTable({
  observations,
  profileId,
  onRefresh,
  hideWeight = false,
}: VitalsHistoryTableProps) {
  const [selectedType, setSelectedType] = useState<string>('all');
  const [selectedDateRange, setSelectedDateRange] = useState<string>('all');
  const [editingItem, setEditingItem] = useState<VitalsObservationItem | null>(null);
  const [deletingItem, setDeletingItem] = useState<VitalsObservationItem | null>(null);

  // Edit form states
  const [editValue, setEditValue] = useState<string>('');
  const [editSystolic, setEditSystolic] = useState<string>('');
  const [editDiastolic, setEditDiastolic] = useState<string>('');
  const [editEffectiveAt, setEditEffectiveAt] = useState<string>('');
  const [editStatus, setEditStatus] = useState<string>('active');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  // Deleting state
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Filter observations
  const filteredObservations = useMemo(() => {
    let result = [...observations];

    // Filter by type
    if (selectedType !== 'all') {
      result = result.filter((obs) => {
        const code = obs.data?.code?.coding?.[0]?.code;
        switch (selectedType) {
          case 'blood_pressure':
            return code === '85354-9' || Boolean(obs.data?.component?.length);
          case 'heart_rate':
            return code === '8867-4';
          case 'glucose':
            return code === '2339-0';
          case 'spo2':
            return code === '2708-6';
          case 'weight':
            return code === '29463-7';
          case 'temperature':
            return code === '8310-5';
          case 'respiratory_rate':
            return code === '9279-1';
          default:
            return true;
        }
      });
    }

    // Filter by date range
    if (selectedDateRange !== 'all') {
      const now = new Date();
      const days = parseInt(selectedDateRange, 10);
      if (!isNaN(days)) {
        const cutoff = new Date(now.getTime() - days * 24 * 60 * 60 * 1000);
        result = result.filter((obs) => new Date(obs.effective_at) >= cutoff);
      }
    }

    // Sort descending by effective_at
    result.sort((a, b) => new Date(b.effective_at).getTime() - new Date(a.effective_at).getTime());
    return result;
  }, [observations, selectedType, selectedDateRange]);

  // Open edit modal
  const handleOpenEdit = (item: VitalsObservationItem) => {
    setEditingItem(item);
    setEditError(null);
    setEditStatus(item.status || 'active');
    setEditEffectiveAt(
      item.effective_at ? new Date(item.effective_at).toISOString().slice(0, 16) : ''
    );

    const code = item.data?.code?.coding?.[0]?.code;
    if (code === '85354-9' || item.data?.component?.length) {
      let sys = '';
      let dia = '';
      for (const c of item.data?.component || []) {
        const cCode = c.code?.coding?.[0]?.code;
        if (cCode === '8480-6') sys = String(c.valueQuantity?.value ?? '');
        if (cCode === '8462-4') dia = String(c.valueQuantity?.value ?? '');
      }
      setEditSystolic(sys);
      setEditDiastolic(dia);
      setEditValue('');
    } else {
      setEditValue(String(item.data?.valueQuantity?.value ?? ''));
      setEditSystolic('');
      setEditDiastolic('');
    }
  };

  // Submit edit
  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingItem || isSubmitting) return;

    setIsSubmitting(true);
    setEditError(null);

    try {
      const code = editingItem.data?.code?.coding?.[0]?.code;
      const isBp = code === '85354-9' || editingItem.data?.component?.length;

      let updatedData = { ...editingItem.data };
      if (isBp) {
        const sysNum = parseFloat(editSystolic);
        const diaNum = parseFloat(editDiastolic);
        if (isNaN(sysNum) || isNaN(diaNum) || sysNum <= diaNum) {
          throw new Error('Valid systolic and diastolic numbers required (systolic > diastolic).');
        }
        updatedData.component = (updatedData.component || []).map((c: any) => {
          const cCode = c.code?.coding?.[0]?.code;
          if (cCode === '8480-6') return { ...c, valueQuantity: { ...c.valueQuantity, value: sysNum } };
          if (cCode === '8462-4') return { ...c, valueQuantity: { ...c.valueQuantity, value: diaNum } };
          return c;
        });
      } else {
        const valNum = parseFloat(editValue);
        if (isNaN(valNum) || valNum <= 0) {
          throw new Error('Measurement value must be a positive number.');
        }
        updatedData.valueQuantity = {
          ...updatedData.valueQuantity,
          value: valNum,
        };
      }

      await updateVitalReading(profileId, editingItem.id, {
        data: updatedData,
        status: editStatus,
        effective_at: editEffectiveAt ? new Date(editEffectiveAt).toISOString() : undefined,
      });

      setEditingItem(null);
      onRefresh();
    } catch (err: any) {
      setEditError(err.message || 'Failed to update vital reading.');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Confirm delete
  const handleConfirmDelete = async () => {
    if (!deletingItem || isDeleting) return;

    setIsDeleting(true);
    setDeleteError(null);

    try {
      await deleteVitalReading(profileId, deletingItem.id);
      setDeletingItem(null);
      onRefresh();
    } catch (err: any) {
      setDeleteError(err.message || 'Failed to delete vital observation.');
    } finally {
      setIsDeleting(false);
    }
  };

  // Helper to format metric info
  const formatMetricDisplay = (obs: VitalsObservationItem) => {
    const code = obs.data?.code?.coding?.[0]?.code;
    switch (code) {
      case '85354-9': {
        let sys = 0;
        let dia = 0;
        for (const c of obs.data?.component || []) {
          const cCode = c.code?.coding?.[0]?.code;
          if (cCode === '8480-6') sys = c.valueQuantity?.value;
          if (cCode === '8462-4') dia = c.valueQuantity?.value;
        }
        return {
          name: 'Blood Pressure',
          value: sys && dia ? `${sys}/${dia}` : '—',
          unit: 'mmHg',
          icon: Activity,
          color: 'text-rose-500',
        };
      }
      case '8867-4':
        return {
          name: 'Heart Rate',
          value: String(obs.data?.valueQuantity?.value ?? '—'),
          unit: 'bpm',
          icon: Heart,
          color: 'text-red-500',
        };
      case '2339-0':
        return {
          name: 'Blood Glucose',
          value: String(obs.data?.valueQuantity?.value ?? '—'),
          unit: obs.data?.valueQuantity?.unit || 'mg/dL',
          icon: Droplets,
          color: 'text-purple-500',
        };
      case '2708-6':
        return {
          name: 'Oxygen Saturation',
          value: String(obs.data?.valueQuantity?.value ?? '—'),
          unit: '%',
          icon: Wind,
          color: 'text-cyan-500',
        };
      case '29463-7': {
        const val = obs.data?.valueQuantity?.value;
        const displayVal = hideWeight ? '••••' : (val !== undefined ? String(val) : '—');
        return {
          name: 'Body Weight',
          value: displayVal,
          unit: hideWeight ? '' : (obs.data?.valueQuantity?.unit || 'kg'),
          icon: Scale,
          color: 'text-emerald-500',
        };
      }
      case '8310-5':
        return {
          name: 'Body Temperature',
          value: String(obs.data?.valueQuantity?.value ?? '—'),
          unit: obs.data?.valueQuantity?.unit || '°F',
          icon: Thermometer,
          color: 'text-amber-500',
        };
      case '9279-1':
        return {
          name: 'Respiratory Rate',
          value: String(obs.data?.valueQuantity?.value ?? '—'),
          unit: 'br/min',
          icon: Activity,
          color: 'text-blue-500',
        };
      default:
        return {
          name: obs.data?.code?.text || 'Observation',
          value: String(obs.data?.valueQuantity?.value ?? '—'),
          unit: obs.data?.valueQuantity?.unit || '',
          icon: Activity,
          color: 'text-gray-500',
        };
    }
  };

  return (
    <Card className="p-5 shadow-sm space-y-4">
      {/* Header and Filter Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[var(--cf-border)]">
        <div>
          <h3 className="font-semibold text-base text-[var(--cf-fg)]">
            Readings History
          </h3>
          <p className="text-xs text-[var(--cf-fg-muted)]">
            Governed observations log with audit lineage and management
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          {/* Type Filter */}
          <div className="flex items-center gap-1.5">
            <Filter className="w-3.5 h-3.5 text-[var(--cf-fg-subtle)]" />
            <select
              data-testid="filter-vital-type"
              value={selectedType}
              onChange={(e) => setSelectedType(e.target.value)}
              className="px-2.5 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg)] focus:outline-none focus:ring-1 focus:ring-[var(--cf-focus)] font-medium"
            >
              <option value="all">All Metrics</option>
              <option value="blood_pressure">Blood Pressure</option>
              <option value="heart_rate">Heart Rate</option>
              <option value="glucose">Blood Glucose</option>
              <option value="spo2">Oxygen (SpO2)</option>
              <option value="weight">Body Weight</option>
              <option value="temperature">Temperature</option>
              <option value="respiratory_rate">Respiratory Rate</option>
            </select>
          </div>

          {/* Date Filter */}
          <div className="flex items-center gap-1.5">
            <Calendar className="w-3.5 h-3.5 text-[var(--cf-fg-subtle)]" />
            <select
              data-testid="filter-date-range"
              value={selectedDateRange}
              onChange={(e) => setSelectedDateRange(e.target.value)}
              className="px-2.5 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg)] focus:outline-none focus:ring-1 focus:ring-[var(--cf-focus)] font-medium"
            >
              <option value="all">All Time</option>
              <option value="7">Last 7 Days</option>
              <option value="30">Last 30 Days</option>
              <option value="90">Last 90 Days</option>
            </select>
          </div>
        </div>
      </div>

      {/* Table */}
      {filteredObservations.length === 0 ? (
        <div className="py-12 text-center text-xs text-[var(--cf-fg-subtle)]">
          No vital readings match the current filter selection.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table data-testid="vitals-history-table" className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b border-[var(--cf-border)] text-[var(--cf-fg-muted)]">
                <th className="py-2.5 px-3 font-semibold">Date & Time</th>
                <th className="py-2.5 px-3 font-semibold">Metric</th>
                <th className="py-2.5 px-3 font-semibold">Reading Value</th>
                <th className="py-2.5 px-3 font-semibold">Source</th>
                <th className="py-2.5 px-3 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--cf-border)]">
              {filteredObservations.map((obs) => {
                const info = formatMetricDisplay(obs);
                const IconComponent = info.icon;
                const dateStr = obs.effective_at
                  ? new Date(obs.effective_at).toLocaleString(undefined, {
                      dateStyle: 'medium',
                      timeStyle: 'short',
                    })
                  : '—';

                return (
                  <tr key={obs.id} className="hover:bg-[var(--cf-surface-2)] transition-colors">
                    <td className="py-2.5 px-3 text-[var(--cf-fg-muted)] font-mono whitespace-nowrap">
                      {dateStr}
                    </td>
                    <td className="py-2.5 px-3">
                      <div className="flex items-center gap-1.5">
                        <IconComponent className={`w-3.5 h-3.5 ${info.color}`} />
                        <span className="font-semibold text-[var(--cf-fg)]">{info.name}</span>
                      </div>
                    </td>
                    <td className="py-2.5 px-3 font-mono font-medium text-[var(--cf-fg)] whitespace-nowrap">
                      {info.value} {info.unit}
                    </td>
                    <td className="py-2.5 px-3">
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)] border border-[var(--cf-border)]">
                        {obs.source_type || 'manual'}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-right whitespace-nowrap">
                      <div className="inline-flex items-center gap-1">
                        <button
                          type="button"
                          data-testid={`edit-vital-${obs.id}`}
                          onClick={() => handleOpenEdit(obs)}
                          className="p-1 rounded-md text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface-3)] transition-colors"
                          title="Edit reading"
                        >
                          <Pencil className="w-3.5 h-3.5" />
                        </button>
                        <button
                          type="button"
                          data-testid={`delete-vital-${obs.id}`}
                          onClick={() => setDeletingItem(obs)}
                          className="p-1 rounded-md text-[var(--cf-fg-muted)] hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/30 transition-colors"
                          title="Delete reading"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Edit Vital Observation Modal */}
      {editingItem && (
        <Dialog open={Boolean(editingItem)} onOpenChange={(open) => !open && setEditingItem(null)}>
          <DialogContent data-testid="edit-vital-modal" className="max-w-md">
            <DialogHeader>
              <DialogTitle>Edit Vital Reading</DialogTitle>
              <DialogDescription>
                Update observation value or timestamp. Changes are recorded in audit logs.
              </DialogDescription>
            </DialogHeader>

            {editError && (
              <div className="p-3 rounded-lg bg-rose-50 dark:bg-rose-950/30 border border-rose-300 dark:border-rose-900 text-rose-800 dark:text-rose-200 text-xs">
                {editError}
              </div>
            )}

            <form onSubmit={handleSaveEdit} className="space-y-4 pt-2">
              {editingItem.data?.code?.coding?.[0]?.code === '85354-9' || editingItem.data?.component?.length ? (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-semibold text-[var(--cf-fg)] mb-1">
                      Systolic (mmHg)
                    </label>
                    <input
                      type="number"
                      data-testid="edit-vital-systolic"
                      value={editSystolic}
                      onChange={(e) => setEditSystolic(e.target.value)}
                      className="w-full px-3 py-2 text-sm rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg)] font-mono"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-[var(--cf-fg)] mb-1">
                      Diastolic (mmHg)
                    </label>
                    <input
                      type="number"
                      data-testid="edit-vital-diastolic"
                      value={editDiastolic}
                      onChange={(e) => setEditDiastolic(e.target.value)}
                      className="w-full px-3 py-2 text-sm rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg)] font-mono"
                    />
                  </div>
                </div>
              ) : (
                <div>
                  <label className="block text-xs font-semibold text-[var(--cf-fg)] mb-1">
                    Measurement Value
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    data-testid="edit-vital-value"
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    className="w-full px-3 py-2 text-sm rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg)] font-mono"
                  />
                </div>
              )}

              <div>
                <label className="block text-xs font-semibold text-[var(--cf-fg)] mb-1">
                  Effective Date & Time
                </label>
                <input
                  type="datetime-local"
                  data-testid="edit-vital-date"
                  value={editEffectiveAt}
                  onChange={(e) => setEditEffectiveAt(e.target.value)}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg)]"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[var(--cf-fg)] mb-1">
                  Observation Status
                </label>
                <select
                  data-testid="edit-vital-status"
                  value={editStatus}
                  onChange={(e) => setEditStatus(e.target.value)}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg)]"
                >
                  <option value="active">Active</option>
                  <option value="amended">Amended</option>
                  <option value="corrected">Corrected</option>
                </select>
              </div>

              <DialogFooter className="pt-2">
                <Button
                  type="button"
                  variant="outline"
                  data-testid="cancel-edit-vital-btn"
                  onClick={() => setEditingItem(null)}
                  disabled={isSubmitting}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  data-testid="save-vital-btn"
                  disabled={isSubmitting}
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                      Saving...
                    </>
                  ) : (
                    'Save Changes'
                  )}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      )}

      {/* Delete Confirmation Modal */}
      {deletingItem && (
        <Dialog open={Boolean(deletingItem)} onOpenChange={(open) => !open && setDeletingItem(null)}>
          <DialogContent data-testid="delete-vital-confirm-modal" className="max-w-md">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2 text-rose-600">
                <AlertTriangle className="w-5 h-5 shrink-0" />
                Confirm Observation Deletion
              </DialogTitle>
              <DialogDescription>
                Are you sure you want to delete this vital reading? This action removes it from active trends and moving averages.
              </DialogDescription>
            </DialogHeader>

            {deleteError && (
              <div className="p-3 rounded-lg bg-rose-50 dark:bg-rose-950/30 border border-rose-300 dark:border-rose-900 text-rose-800 dark:text-rose-200 text-xs">
                {deleteError}
              </div>
            )}

            <DialogFooter className="pt-2">
              <Button
                type="button"
                variant="outline"
                data-testid="cancel-delete-vital-btn"
                onClick={() => setDeletingItem(null)}
                disabled={isDeleting}
              >
                Cancel
              </Button>
              <Button
                type="button"
                data-testid="confirm-delete-vital-btn"
                onClick={handleConfirmDelete}
                disabled={isDeleting}
                className="bg-rose-600 hover:bg-rose-700 text-white"
              >
                {isDeleting ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                    Deleting...
                  </>
                ) : (
                  'Delete Reading'
                )}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </Card>
  );
}
