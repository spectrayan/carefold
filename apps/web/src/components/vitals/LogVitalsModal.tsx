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
  AlertTriangle,
  PhoneCall,
  Loader2,
  CheckCircle2,
  ShieldAlert,
} from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/Dialog';
import { Button } from '@/components/ui/Button';
import { evaluateClientSafety, recordVitals } from '@/lib/vitalsClient';
import type { ClientSafetyEvaluation } from '@/types/vitals';

export interface LogVitalsModalProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  profileId: string;
  onSuccess?: () => void;
  defaultMetric?: string;
}

export function LogVitalsModal({
  isOpen,
  onOpenChange,
  profileId,
  onSuccess,
}: LogVitalsModalProps) {
  const [systolic, setSystolic] = useState<string>('');
  const [diastolic, setDiastolic] = useState<string>('');
  const [heartRate, setHeartRate] = useState<string>('');
  const [glucose, setGlucose] = useState<string>('');
  const [spo2, setSpo2] = useState<string>('');
  const [weight, setWeight] = useState<string>('');
  const [height, setHeight] = useState<string>('');
  const [symptoms, setSymptoms] = useState<string[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState(false);

  const numSys = systolic ? parseInt(systolic, 10) : undefined;
  const numDia = diastolic ? parseInt(diastolic, 10) : undefined;
  const numHr = heartRate ? parseInt(heartRate, 10) : undefined;
  const numGluc = glucose ? parseFloat(glucose) : undefined;
  const numSpo2 = spo2 ? parseFloat(spo2) : undefined;
  const numWt = weight ? parseFloat(weight) : undefined;
  const numHt = height ? parseFloat(height) : undefined;

  // Real-time clinical safety screening
  const safetyEval: ClientSafetyEvaluation = useMemo(() => {
    return evaluateClientSafety(
      {
        systolic: numSys,
        diastolic: numDia,
        spo2: numSpo2,
        glucose: numGluc,
      },
      symptoms
    );
  }, [numSys, numDia, numSpo2, numGluc, symptoms]);

  // Validation rules
  const bpIncomplete = (numSys !== undefined && numDia === undefined) || (numDia !== undefined && numSys === undefined);
  const bpInvalidOrder = numSys !== undefined && numDia !== undefined && numSys <= numDia;
  const weightInvalid = numWt !== undefined && numWt <= 0;
  const heightInvalid = numHt !== undefined && numHt <= 0;
  const hasAtLeastOne =
    (numSys !== undefined && numDia !== undefined) ||
    numHr !== undefined ||
    numGluc !== undefined ||
    numSpo2 !== undefined ||
    numWt !== undefined;

  const isFormValid = hasAtLeastOne && !bpIncomplete && !bpInvalidOrder && !weightInvalid && !heightInvalid;

  const handleToggleSymptom = (sym: string) => {
    setSymptoms((prev) =>
      prev.includes(sym) ? prev.filter((s) => s !== sym) : [...prev, sym]
    );
  };

  const handleReset = () => {
    setSystolic('');
    setDiastolic('');
    setHeartRate('');
    setGlucose('');
    setSpo2('');
    setWeight('');
    setHeight('');
    setSymptoms([]);
    setSubmitError(null);
    setSubmitSuccess(false);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isFormValid || isSubmitting) return;

    setIsSubmitting(true);
    setSubmitError(null);

    try {
      await recordVitals(profileId, {
        vitals: {
          systolic: numSys,
          diastolic: numDia,
          heart_rate: numHr,
          blood_glucose: numGluc,
          spo2: numSpo2,
          weight: numWt,
          height: numHt,
        },
        reported_symptoms: symptoms,
        source_type: 'manual',
      });

      setSubmitSuccess(true);
      setTimeout(() => {
        handleReset();
        onOpenChange(false);
        onSuccess?.();
      }, 800);
    } catch (err: any) {
      setSubmitError(err.message || 'Failed to record vitals observation.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent data-testid="log-vitals-modal" className="max-w-xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Log Vitals Observation</DialogTitle>
          <DialogDescription>
            Enter your recent biometric measurements and any active symptoms.
          </DialogDescription>
        </DialogHeader>

        {/* Real-Time Clinical Red-Flag Safety Alert Banner */}
        {safetyEval.triggered && (
          <div
            data-testid="vitals-safety-banner"
            role="alert"
            aria-live="assertive"
            className={`p-4 rounded-xl border-2 flex flex-col gap-2.5 my-2 transition-all ${
              safetyEval.severity === 'emergency'
                ? 'border-red-600 bg-red-50/95 dark:bg-red-950/40 text-red-950 dark:text-red-100'
                : 'border-amber-500 bg-amber-50/90 dark:bg-amber-950/30 text-amber-950 dark:text-amber-100'
            }`}
          >
            <div className="flex items-center gap-2 font-bold text-sm">
              <AlertTriangle className="w-5 h-5 text-red-600 shrink-0" />
              <span data-testid="safety-alert-title">{safetyEval.title}</span>
            </div>
            <p className="text-xs leading-relaxed" data-testid="safety-alert-directive">
              {safetyEval.directive}
            </p>
            {safetyEval.call911 && (
              <div className="pt-1">
                <a
                  data-testid="safety-call-911-btn"
                  href="tel:911"
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white font-bold text-xs shadow-sm cursor-pointer"
                >
                  <PhoneCall className="w-3.5 h-3.5" />
                  Call 911 Immediately
                </a>
              </div>
            )}
          </div>
        )}

        {submitError && (
          <div className="p-3 rounded-lg bg-rose-50 dark:bg-rose-950/30 border border-rose-300 dark:border-rose-900 text-rose-800 dark:text-rose-200 text-xs">
            {submitError}
          </div>
        )}

        {submitSuccess && (
          <div className="p-3 rounded-lg bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-300 dark:border-emerald-900 text-emerald-800 dark:text-emerald-200 text-xs flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600" />
            Vitals recorded successfully!
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4 pt-2">
          {/* Blood Pressure Row */}
          <div>
            <label className="block text-xs font-semibold text-[var(--cf-fg)] mb-1.5">
              Blood Pressure (mmHg)
            </label>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <input
                  type="number"
                  data-testid="input-systolic"
                  placeholder="Systolic (e.g. 120)"
                  value={systolic}
                  onChange={(e) => setSystolic(e.target.value)}
                  min={40}
                  max={300}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] font-mono"
                />
                <span className="text-xs text-[var(--cf-fg-subtle)] mt-0.5 block">Systolic (Upper)</span>
              </div>
              <div>
                <input
                  type="number"
                  data-testid="input-diastolic"
                  placeholder="Diastolic (e.g. 80)"
                  value={diastolic}
                  onChange={(e) => setDiastolic(e.target.value)}
                  min={30}
                  max={200}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] font-mono"
                />
                <span className="text-xs text-[var(--cf-fg-subtle)] mt-0.5 block">Diastolic (Lower)</span>
              </div>
            </div>
            {bpIncomplete && (
              <span className="text-xs text-amber-600 dark:text-amber-400 mt-1 block">
                Please enter both systolic and diastolic blood pressure values.
              </span>
            )}
            {bpInvalidOrder && (
              <span data-testid="bp-error-order" className="text-xs text-rose-600 dark:text-rose-400 mt-1 block">
                Systolic pressure must be greater than diastolic pressure.
              </span>
            )}
          </div>

          {/* Heart Rate & Glucose */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-[var(--cf-fg)] mb-1">
                Heart Rate (bpm)
              </label>
              <input
                type="number"
                data-testid="input-heart-rate"
                placeholder="Pulse (e.g. 72)"
                value={heartRate}
                onChange={(e) => setHeartRate(e.target.value)}
                min={20}
                max={250}
                className="w-full px-3 py-2 text-sm rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] font-mono"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-[var(--cf-fg)] mb-1">
                Blood Glucose (mg/dL)
              </label>
              <input
                type="number"
                data-testid="input-glucose"
                placeholder="e.g. 95"
                value={glucose}
                onChange={(e) => setGlucose(e.target.value)}
                min={10}
                max={600}
                className="w-full px-3 py-2 text-sm rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] font-mono"
              />
            </div>
          </div>

          {/* Oxygen (SpO2) & Weight */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-[var(--cf-fg)] mb-1">
                Oxygen Saturation (SpO2 %)
              </label>
              <input
                type="number"
                data-testid="input-spo2"
                placeholder="e.g. 98"
                value={spo2}
                onChange={(e) => setSpo2(e.target.value)}
                min={50}
                max={100}
                className="w-full px-3 py-2 text-sm rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] font-mono"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-[var(--cf-fg)] mb-1">
                Body Weight (kg)
              </label>
              <input
                type="number"
                step="0.1"
                data-testid="input-weight"
                placeholder="e.g. 74.5"
                value={weight}
                onChange={(e) => setWeight(e.target.value)}
                min={1}
                className="w-full px-3 py-2 text-sm rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] font-mono"
              />
            </div>
          </div>

          {/* Height (for BMI) */}
          <div>
            <label className="block text-xs font-semibold text-[var(--cf-fg)] mb-1">
              Body Height (cm) <span className="text-[var(--cf-fg-subtle)] font-normal">(optional, for BMI calculation)</span>
            </label>
            <input
              type="number"
              step="0.1"
              data-testid="input-height"
              placeholder="e.g. 175"
              value={height}
              onChange={(e) => setHeight(e.target.value)}
              min={30}
              className="w-full px-3 py-2 text-sm rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] font-mono"
            />
          </div>

          {/* Active Symptoms Checklist */}
          <div className="pt-2 border-t border-[var(--cf-border)]">
            <span className="block text-xs font-semibold text-[var(--cf-fg)] mb-2">
              Any Concurrent Symptoms?
            </span>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
              {[
                { id: 'chest_pain', label: 'Chest pain or chest pressure' },
                { id: 'shortness_of_breath', label: 'Severe shortness of breath' },
                { id: 'severe_back_pain', label: 'Sudden severe back pain' },
                { id: 'stroke_fast', label: 'Face droop, arm weakness, slurred speech' },
                { id: 'vision_loss', label: 'Acute vision loss or severe blur' },
                { id: 'dizziness', label: 'Dizziness or lightheadedness' },
              ].map((sym) => (
                <label
                  key={sym.id}
                  className="flex items-center gap-2 p-2 rounded-lg border border-[var(--cf-border)] hover:bg-[var(--cf-surface-2)] cursor-pointer select-none"
                >
                  <input
                    type="checkbox"
                    data-testid={`checkbox-symptom-${sym.id}`}
                    checked={symptoms.includes(sym.id)}
                    onChange={() => handleToggleSymptom(sym.id)}
                    className="rounded text-[var(--cf-primary)] focus:ring-[var(--cf-focus)]"
                  />
                  <span className="text-[var(--cf-fg-muted)]">{sym.label}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Non-clinical boundary notice */}
          <div className="pt-2 text-xs text-[var(--cf-fg-subtle)] flex items-start gap-1.5 leading-relaxed">
            <ShieldAlert className="w-3.5 h-3.5 shrink-0 mt-0.5 text-[var(--cf-fg-subtle)]" />
            <span>
              Values recorded here are stored locally in your clinical profile for tracking and visit preparation.
            </span>
          </div>

          <DialogFooter className="pt-3">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              data-testid="submit-vitals-btn"
              disabled={!isFormValid || isSubmitting}
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
                  Saving...
                </>
              ) : (
                'Save Observations'
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
