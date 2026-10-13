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

import type {
  VitalMeasurements,
  VitalsObservationItem,
  VitalsTrendsResponse,
  LatestVitalsState,
  ClientSafetyEvaluation,
} from '@/types/vitals';

export function classifyBloodPressure(systolic?: number | null, diastolic?: number | null): string {
  if (!systolic || !diastolic) return 'Unknown';
  if (systolic >= 180 || diastolic >= 120) return 'Hypertensive Crisis';
  if (systolic >= 140 || diastolic >= 90) return 'Stage 2';
  if (systolic >= 130 || diastolic >= 80) return 'Stage 1';
  if (systolic >= 120 && diastolic < 80) return 'Elevated';
  if (systolic < 120 && diastolic < 80) return 'Normal';
  return 'Normal';
}

export function classifyHeartRate(hr?: number | null): string {
  if (!hr) return 'Unknown';
  if (hr < 60) return 'Bradycardia (<60)';
  if (hr > 100) return 'Tachycardia (>100)';
  return 'Normal (60–100)';
}

export function classifyGlucose(glucose?: number | null): string {
  if (!glucose) return 'Unknown';
  if (glucose < 54) return 'Severe Low (<54)';
  if (glucose < 70) return 'Low (<70)';
  if (glucose > 140) return 'Elevated (>140)';
  if (glucose >= 100) return 'Pre-diabetic (100–125)';
  return 'Normal (70–99)';
}

export function classifySpo2(spo2?: number | null): string {
  if (!spo2) return 'Unknown';
  if (spo2 < 90) return 'Severe Hypoxemia (<90%)';
  if (spo2 < 95) return 'Borderline (90–94%)';
  return 'Normal (95–100%)';
}

export function classifyBmi(bmi?: number | null): string {
  if (!bmi) return 'Unknown';
  if (bmi < 18.5) return 'Underweight (<18.5)';
  if (bmi < 25) return 'Normal (18.5–24.9)';
  if (bmi < 30) return 'Overweight (25–29.9)';
  return 'Obese (≥30)';
}

export function evaluateClientSafety(
  values: {
    systolic?: number | null;
    diastolic?: number | null;
    spo2?: number | null;
    glucose?: number | null;
  },
  symptoms: string[] = []
): ClientSafetyEvaluation {
  const hasAcuteSymptoms = symptoms.some((s) =>
    [
      'chest_pain',
      'shortness_of_breath',
      'severe_back_pain',
      'stroke_fast',
      'vision_loss',
      'dysarthria',
      'unilateral_weakness',
    ].includes(s)
  );

  const hasHypotensionSymptoms = symptoms.some((s) =>
    ['dizziness', 'lightheadedness', 'fainting', 'syncope'].includes(s)
  );

  const sys = values.systolic ?? 0;
  const dia = values.diastolic ?? 0;
  const isCrisisBp = sys >= 180 || dia >= 120;
  const isHypotension = (sys > 0 && sys < 90) || (dia > 0 && dia < 60);

  // 1. Symptomatic Hypertensive Crisis -> CALL 911 NOW
  if (isCrisisBp && hasAcuteSymptoms) {
    return {
      triggered: true,
      category: 'bp_crisis_symptomatic',
      severity: 'emergency',
      title: 'CRITICAL EMERGENCY: Call 911 Immediately',
      directive:
        'Your blood pressure reading is dangerously elevated (≥180/120 mmHg) accompanied by acute warning symptoms. Do not drive yourself. Call 911 or emergency medical services immediately.',
      call911: true,
      promptRecheck: false,
    };
  }

  // 2. Severe Hypoxemia (<90% SpO2)
  if (values.spo2 !== undefined && values.spo2 !== null && values.spo2 < 90 && values.spo2 > 0) {
    return {
      triggered: true,
      category: 'severe_hypoxemia',
      severity: 'emergency',
      title: 'Critically Low Oxygen Saturation (<90%)',
      directive:
        'Your oxygen saturation is below 90%. Seek immediate emergency medical care. Call 911 if accompanied by shortness of breath or difficulty breathing.',
      call911: true,
      promptRecheck: false,
    };
  }

  // 3. Severe Hypoglycemia (<54 mg/dL) -> Rule of 15
  if (values.glucose !== undefined && values.glucose !== null && values.glucose < 54 && values.glucose > 0) {
    return {
      triggered: true,
      category: 'severe_hypoglycemia',
      severity: 'urgent',
      title: 'Severe Hypoglycemia (<54 mg/dL) — Rule of 15',
      directive:
        'Immediately consume 15 grams of fast-acting carbohydrate (e.g., 4 oz fruit juice or 3–4 glucose tablets). Rest quietly and recheck blood sugar in 15 minutes. Call 911 if symptoms worsen.',
      call911: false,
      promptRecheck: true,
    };
  }

  // 4. Asymptomatic Hypertensive Crisis
  if (isCrisisBp && !hasAcuteSymptoms) {
    return {
      triggered: true,
      category: 'bp_crisis_asymptomatic',
      severity: 'urgent',
      title: 'Very High Blood Pressure Reading (≥180/120 mmHg)',
      directive:
        'Please rest quietly for 5 minutes without talking and recheck your reading. If reading remains ≥180/120 mmHg, or if you develop chest pain or shortness of breath, contact your physician promptly or seek emergency evaluation.',
      call911: false,
      promptRecheck: true,
    };
  }

  // 5. Symptomatic Hypotension
  if (isHypotension && hasHypotensionSymptoms) {
    return {
      triggered: true,
      category: 'symptomatic_hypotension',
      severity: 'urgent',
      title: 'Symptomatic Low Blood Pressure (<90/60 mmHg)',
      directive:
        'Your blood pressure is low and accompanied by dizziness or lightheadedness. Sit or lie down safely to prevent falling. If symptoms persist or you feel faint, contact your doctor immediately.',
      call911: false,
      promptRecheck: true,
    };
  }

  return {
    triggered: false,
    category: null,
    severity: 'normal',
    title: 'Normal Reading',
    directive: '',
    call911: false,
    promptRecheck: false,
  };
}

export function extractLatestVitals(observations: VitalsObservationItem[]): LatestVitalsState {
  const result: LatestVitalsState = {};
  if (!observations || observations.length === 0) return result;

  // Sort descending by effective_at
  const sorted = [...observations].sort(
    (a, b) => new Date(b.effective_at).getTime() - new Date(a.effective_at).getTime()
  );

  // Find BP
  const bpObs = sorted.filter((o) => {
    const code = o.data?.code?.coding?.[0]?.code;
    return code === '85354-9' || o.data?.component?.length >= 2;
  });
  if (bpObs.length > 0) {
    const latest = bpObs[0];
    const components = latest.data?.component || [];
    let sys = 0;
    let dia = 0;
    for (const c of components) {
      const cCode = c.code?.coding?.[0]?.code;
      if (cCode === '8480-6') sys = c.valueQuantity?.value;
      if (cCode === '8462-4') dia = c.valueQuantity?.value;
    }
    const d = new Date(latest.effective_at);
    const hour = d.getHours();
    const isAM = hour >= 5 && hour < 12;

    let deltaSys: number | undefined;
    let deltaDia: number | undefined;
    if (bpObs.length > 1) {
      const prior = bpObs[1];
      let pSys = 0;
      let pDia = 0;
      for (const c of prior.data?.component || []) {
        const cCode = c.code?.coding?.[0]?.code;
        if (cCode === '8480-6') pSys = c.valueQuantity?.value;
        if (cCode === '8462-4') pDia = c.valueQuantity?.value;
      }
      if (pSys && pDia) {
        deltaSys = sys - pSys;
        deltaDia = dia - pDia;
      }
    }

    if (sys && dia) {
      result.bloodPressure = {
        systolic: sys,
        diastolic: dia,
        effectiveAt: latest.effective_at,
        stage: classifyBloodPressure(sys, dia),
        isAM,
        deltaSys,
        deltaDia,
      };
    }
  }

  // Find Heart Rate
  const hrObs = sorted.filter((o) => o.data?.code?.coding?.[0]?.code === '8867-4');
  if (hrObs.length > 0) {
    const latest = hrObs[0];
    const val = latest.data?.valueQuantity?.value;
    let delta: number | undefined;
    if (hrObs.length > 1) {
      const pVal = hrObs[1].data?.valueQuantity?.value;
      if (pVal !== undefined && val !== undefined) delta = val - pVal;
    }
    if (val !== undefined) {
      result.heartRate = {
        value: val,
        effectiveAt: latest.effective_at,
        classification: classifyHeartRate(val),
        delta,
      };
    }
  }

  // Find Glucose
  const glucObs = sorted.filter((o) => o.data?.code?.coding?.[0]?.code === '2339-0');
  if (glucObs.length > 0) {
    const latest = glucObs[0];
    const val = latest.data?.valueQuantity?.value;
    const unit = latest.data?.valueQuantity?.unit || 'mg/dL';
    let delta: number | undefined;
    if (glucObs.length > 1) {
      const pVal = glucObs[1].data?.valueQuantity?.value;
      if (pVal !== undefined && val !== undefined) delta = val - pVal;
    }
    if (val !== undefined) {
      result.bloodGlucose = {
        value: val,
        unit,
        effectiveAt: latest.effective_at,
        classification: classifyGlucose(val),
        delta,
      };
    }
  }

  // Find SpO2
  const spo2Obs = sorted.filter((o) => o.data?.code?.coding?.[0]?.code === '2708-6');
  if (spo2Obs.length > 0) {
    const latest = spo2Obs[0];
    const val = latest.data?.valueQuantity?.value;
    let delta: number | undefined;
    if (spo2Obs.length > 1) {
      const pVal = spo2Obs[1].data?.valueQuantity?.value;
      if (pVal !== undefined && val !== undefined) delta = val - pVal;
    }
    if (val !== undefined) {
      result.spo2 = {
        value: val,
        effectiveAt: latest.effective_at,
        classification: classifySpo2(val),
        delta,
      };
    }
  }

  // Find Weight
  const wtObs = sorted.filter((o) => o.data?.code?.coding?.[0]?.code === '29463-7');
  if (wtObs.length > 0) {
    const latest = wtObs[0];
    const val = latest.data?.valueQuantity?.value;
    const bmiVal = latest.data?.extension?.find((e: any) => e.url?.includes('bmi'))?.valueDecimal;
    const isHidden = Boolean(latest.data?.extension?.find((e: any) => e.url?.includes('hidden'))?.valueBoolean);
    let delta: number | undefined;
    if (wtObs.length > 1) {
      const pVal = wtObs[1].data?.valueQuantity?.value;
      if (pVal !== undefined && val !== undefined) delta = val - pVal;
    }
    if (val !== undefined) {
      result.weight = {
        valueKg: val,
        valueLbs: val ? Number((val * 2.20462).toFixed(1)) : undefined,
        bmi: bmiVal,
        classification: classifyBmi(bmiVal),
        effectiveAt: latest.effective_at,
        weightHidden: isHidden,
        delta,
      };
    }
  }

  return result;
}

// ---------------------------------------------------------------------------
// API Client Functions
// ---------------------------------------------------------------------------

export async function fetchVitalsObservations(
  profileId: string,
  params?: { limit?: number; offset?: number; resource_type?: string }
): Promise<{ observations: VitalsObservationItem[]; total: number }> {
  const query = new URLSearchParams();
  if (params?.limit) query.set('limit', String(params.limit));
  if (params?.offset) query.set('offset', String(params.offset));
  if (params?.resource_type) query.set('resource_type', params.resource_type);

  const res = await fetch(`/api/profiles/${encodeURIComponent(profileId)}/vitals?${query.toString()}`, {
    credentials: 'include',
  });
  if (!res.ok) throw new Error(`Failed to fetch vitals (${res.status})`);
  return res.json();
}

export async function fetchVitalsTrends(
  profileId: string,
  timezone?: string,
  days = 90
): Promise<VitalsTrendsResponse> {
  const query = new URLSearchParams();
  const tz = timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  query.set('timezone', tz);
  query.set('days', String(days));

  const res = await fetch(`/api/profiles/${encodeURIComponent(profileId)}/vitals/trends?${query.toString()}`, {
    credentials: 'include',
  });
  if (!res.ok) throw new Error(`Failed to fetch vitals trends (${res.status})`);
  return res.json();
}

export async function recordVitals(
  profileId: string,
  payload: {
    vitals: VitalMeasurements;
    reported_symptoms?: string[];
    effective_at?: string;
    source_type?: string;
  }
): Promise<{
  status: string;
  created_ids: string[];
  safety_alert?: any;
  bmi?: any;
}> {
  const res = await fetch(`/api/profiles/${encodeURIComponent(profileId)}/vitals`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to record vitals (${res.status})`);
  }
  return res.json();
}
