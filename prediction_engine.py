"""
prediction_engine.py
====================
Three-Layer Predictive Maintenance Engine for GenPredict NG

LAYER 1 — RAW LAYER    : Ingested daily log data (handled by models/routes)
LAYER 2 — PROCESSING   : Computes 5 health indicators from raw inputs
LAYER 3 — PREDICTING   : Random Forest ML model → CHS score + risk level
                          Falls back to weighted formula if model not trained yet.
"""

import json
import os
import numpy as np
from datetime import datetime, date

# ── Load pre-trained RF models (Layer 3) ──────────────────
_clf = None   # Risk classifier
_reg = None   # Health score regressor
_ML_ACTIVE = False

try:
    import joblib
    _clf_path = os.path.join(os.path.dirname(__file__), 'model', 'rf_classifier.pkl')
    _reg_path = os.path.join(os.path.dirname(__file__), 'model', 'rf_regressor.pkl')
    if os.path.exists(_clf_path) and os.path.exists(_reg_path):
        _clf = joblib.load(_clf_path)
        _reg = joblib.load(_reg_path)
        _ML_ACTIVE = True
except ImportError:
    pass  # scikit-learn not installed — will use formula fallback


# ═══════════════════════════════════════════════════════════
#  CONSTANTS & THRESHOLDS
# ═══════════════════════════════════════════════════════════

# Specific Fuel Consumption (L/kWh) — diesel standard
SFC_DIESEL = 0.35
SFC_PETROL = 0.45
SFC_GAS    = 0.30

# Indicator weights (must sum to 1.0)
WEIGHTS = {
    'uii':  0.20,   # Usage Intensity Index
    'fer':  0.25,   # Fuel Efficiency Ratio  ← highest = best health signal
    'mos':  0.25,   # Maintenance Overdue Score ← highest = most dangerous
    'aals': 0.15,   # Age-Adjusted Load Stress
    'ffr':  0.15,   # Fault Frequency Rate
}

# Risk classification thresholds (CHS out of 100)
RISK_THRESHOLDS = {
    'HEALTHY':   75,
    'MODERATE':  50,
    'HIGH RISK': 25,
    # CRITICAL: < 25
}


# ═══════════════════════════════════════════════════════════
#  LAYER 2 — PROCESSING: INDICATOR COMPUTATION
# ═══════════════════════════════════════════════════════════

def compute_uii(avg_usage_hours: float) -> float:
    """
    Usage Intensity Index (UII)
    Measures how hard the generator is being pushed on a daily basis.
    Range: 0.0 (never used) → 1.0 (running 24 hours/day)
    """
    return min(avg_usage_hours / 24.0, 1.0)


def compute_fer(avg_fuel_consumed: float, kva_rating: float,
                avg_load_level: float, avg_usage_hours: float,
                fuel_type: str = 'Diesel') -> float:
    """
    Fuel Efficiency Ratio (FER)
    Actual fuel consumed vs theoretical expected consumption.
    FER = 1.0 → perfect efficiency
    FER > 1.2 → 20% over-consumption (warning)
    FER > 1.5 → 50% over-consumption (critical — fuel system failure risk)
    FER < 0.8 → under-reporting / logging error
    """
    sfc = SFC_DIESEL
    if fuel_type == 'Petrol':
        sfc = SFC_PETROL
    elif 'Gas' in fuel_type:
        sfc = SFC_GAS

    # kW output = KVA × power_factor (0.8 for typical diesel gen)
    kw_output = kva_rating * 0.8 * (avg_load_level / 100.0)
    expected_fuel = kw_output * avg_usage_hours * sfc

    if expected_fuel <= 0:
        return 1.0  # no usage — neutral

    return avg_fuel_consumed / expected_fuel


def compute_mos(last_maintenance_date, avg_usage_hours: float,
                age_years: int, avg_load_level: float) -> float:
    """
    Maintenance Overdue Score (MOS)
    Measures how overdue the generator is for servicing.
    Base recommended interval: 90–250 days, adjusted for:
      - Age (older gen needs shorter intervals)
      - Usage intensity (heavier use = shorter intervals)
      - Load stress (higher load = shorter intervals)
    MOS < 0.7  → Fresh service recently done
    MOS 0.7–1.0 → Approaching service window
    MOS > 1.0   → Overdue
    MOS > 1.5   → Critically overdue
    """
    if last_maintenance_date is None:
        return 1.8  # Unknown maintenance history = high risk

    if isinstance(last_maintenance_date, datetime):
        last_maint = last_maintenance_date.date()
    else:
        last_maint = last_maintenance_date

    days_since = (date.today() - last_maint).days

    # Base: 250 hours of runtime = 1 service interval
    # At avg_usage_hours/day:  250 / avg_usage_hours = days interval
    if avg_usage_hours > 0:
        usage_based_interval = 250.0 / avg_usage_hours
    else:
        usage_based_interval = 90.0

    # Age penalty: every year over 3 years reduces interval by 10%
    age_factor = max(0.5, 1.0 - (max(0, age_years - 3) * 0.08))
    # Load factor: higher load = shorter interval
    load_factor = max(0.6, 1.0 - ((avg_load_level - 50) / 200.0)) if avg_load_level > 50 else 1.0

    recommended_interval = min(usage_based_interval * age_factor * load_factor, 180)
    recommended_interval = max(recommended_interval, 30)  # at least 30 days

    return days_since / recommended_interval


def compute_aals(avg_load_level: float, age_years: int, uii: float) -> float:
    """
    Age-Adjusted Load Stress (AALS)
    How much stress the generator is under, considering its age.
    Range: 0.0 (no stress) → 1.0+ (extreme stress on old generator)
    0–0.35  → Low stress
    0.35–0.60 → Moderate stress
    0.60–0.85 → High stress
    > 0.85  → Very high stress — risk of accelerated wear
    """
    load_fraction = avg_load_level / 100.0
    # Age penalty: gens older than 5 years have increasing stress multiplier
    if age_years <= 3:
        age_multiplier = 1.0
    elif age_years <= 7:
        age_multiplier = 1.0 + (age_years - 3) * 0.12
    else:
        age_multiplier = 1.48 + (age_years - 7) * 0.08

    age_multiplier = min(age_multiplier, 2.2)
    return load_fraction * age_multiplier * (0.7 + 0.3 * uii)


def compute_ffr(total_faults: int, days_tracked: int) -> float:
    """
    Fault Frequency Rate (FFR)
    Average faults per day over the tracking period.
    FFR = 0         → No faults (ideal)
    FFR 0–0.1       → Rare faults (acceptable)
    FFR 0.1–0.3     → Moderate concern
    FFR 0.3–0.5     → High fault rate
    FFR > 0.5       → Critical — generator failing
    """
    if days_tracked <= 0:
        return 0.0
    return total_faults / days_tracked


# ═══════════════════════════════════════════════════════════
#  LAYER 3 — PREDICTING: ML MODEL + FORMULA FALLBACK
# ═══════════════════════════════════════════════════════════

def _indicator_to_penalty(indicator_name: str, value: float) -> float:
    """Convert a raw indicator value to a 0–100 penalty score (used by formula fallback)."""

    if indicator_name == 'uii':
        # UII: 0 = no penalty, 1.0 (24hrs/day) = 80 penalty
        return value * 80

    elif indicator_name == 'fer':
        # FER: 1.0 = perfect (0 penalty), each 10% over = +15 penalty
        if value <= 1.0:
            return 0
        return min((value - 1.0) * 150, 100)

    elif indicator_name == 'mos':
        # MOS: 0.7 = no penalty, 1.0 = 30 penalty, 1.5+ = 100 penalty
        if value < 0.7:
            return 0
        return min((value - 0.7) * 200, 100)

    elif indicator_name == 'aals':
        # AALS: 0 = no penalty, 0.85+ = high penalty
        return min(value * 90, 100)

    elif indicator_name == 'ffr':
        # FFR: 0 = 0 penalty, 0.5+ = 100 penalty
        return min(value * 200, 100)

    return 0


def _formula_health_score(uii: float, fer: float, mos: float,
                           aals: float, ffr: float) -> float:
    """Rule-based fallback: weighted linear penalty formula."""
    penalties = {
        'uii':  _indicator_to_penalty('uii', uii),
        'fer':  _indicator_to_penalty('fer', fer),
        'mos':  _indicator_to_penalty('mos', mos),
        'aals': _indicator_to_penalty('aals', aals),
        'ffr':  _indicator_to_penalty('ffr', ffr),
    }
    total_penalty = sum(WEIGHTS[k] * v for k, v in penalties.items())
    return round(max(0.0, 100.0 - total_penalty), 1)


def compute_health_score(uii: float, fer: float, mos: float,
                          aals: float, ffr: float) -> tuple:
    """
    Composite Health Score (CHS) — 0 to 100  &  risk level string.
    LAYER 3: Uses Random Forest model when available (captures non-linear
    indicator interactions), falls back to weighted formula otherwise.

    Returns: (health_score: float, risk_level: str, model_used: str)
    """
    features = [[uii, fer, mos, aals, ffr]]

    if _ML_ACTIVE and _clf is not None and _reg is not None:
        # ── ML path (Random Forest) ───────────────────────
        chs   = round(float(np.clip(_reg.predict(features)[0], 0, 100)), 1)
        risk  = _clf.predict(features)[0]
        return chs, risk, 'Random Forest'
    else:
        # ── Formula fallback ──────────────────────────────
        chs  = _formula_health_score(uii, fer, mos, aals, ffr)
        risk = classify_risk_from_score(chs)
        return chs, risk, 'Weighted Formula'


def classify_risk_from_score(health_score: float) -> str:
    """Map CHS score to risk label."""
    if health_score >= 75:  return 'HEALTHY'
    if health_score >= 50:  return 'MODERATE'
    if health_score >= 25:  return 'HIGH RISK'
    return 'CRITICAL'


def estimate_days_to_service(health_score: float, mos: float) -> int:
    """Estimate how many days the generator can safely run before service."""
    if health_score >= 75:
        return max(0, int((health_score - 75) * 2.5))
    elif health_score >= 50:
        return max(0, int((health_score - 50) * 0.8))
    elif health_score >= 25:
        return 2
    else:
        return 0  # Immediate action


def generate_recommendations(uii: float, fer: float, mos: float,
                               aals: float, ffr: float,
                               risk_level: str, health_score: float,
                               age_years: int, fuel_type: str) -> list:
    """
    Generate prioritised maintenance recommendations based on indicator levels.
    Returns list of dicts: {priority, category, action, reason}
    """
    recs = []

    # ── Fuel Efficiency Recommendations ───────────────────
    if fer >= 1.5:
        recs.append({
            'priority': 'critical',
            'icon': '⛽',
            'category': 'Fuel System',
            'action': f'Immediate fuel system inspection required',
            'reason': f'Fuel consumption is {int((fer-1)*100)}% above expected for your {fuel_type} generator. '
                      f'Likely causes: clogged injectors, failing fuel pump, or air filter blockage.'
        })
    elif fer >= 1.25:
        recs.append({
            'priority': 'high',
            'icon': '⛽',
            'category': 'Fuel System',
            'action': 'Inspect and service fuel injectors / carburettor',
            'reason': f'Over-consuming fuel by {int((fer-1)*100)}%. Check and clean air filter, fuel filter, and injectors.'
        })
    elif fer >= 1.1:
        recs.append({
            'priority': 'medium',
            'icon': '⛽',
            'category': 'Fuel Efficiency',
            'action': 'Monitor fuel consumption closely over the next 5 days',
            'reason': f'Slight over-consumption detected ({int((fer-1)*100)}% above baseline). Could indicate early injector wear.'
        })

    # ── Maintenance Schedule Recommendations ───────────────
    if mos >= 1.5:
        recs.append({
            'priority': 'critical',
            'icon': '🔧',
            'category': 'Scheduled Maintenance',
            'action': 'OVERDUE: Full service required immediately',
            'reason': f'Generator is critically overdue for maintenance (score: {mos:.1f}x recommended interval). '
                      f'Risk of catastrophic failure increases significantly beyond this point.'
        })
    elif mos >= 1.0:
        recs.append({
            'priority': 'high',
            'icon': '🔧',
            'category': 'Scheduled Maintenance',
            'action': 'Schedule oil change, filter replacement, and full inspection within 48 hours',
            'reason': f'Maintenance interval has been exceeded. Perform oil & filter change, check coolant, belts, and battery.'
        })
    elif mos >= 0.7:
        recs.append({
            'priority': 'medium',
            'icon': '📅',
            'category': 'Upcoming Service',
            'action': 'Plan next service appointment within the next 14 days',
            'reason': 'Approaching recommended service interval. Proactive scheduling prevents breakdowns.'
        })

    # ── Age & load Stress Recommendations ─────────────────
    if aals >= 0.85:
        recs.append({
            'priority': 'high',
            'icon': '🌡️',
            'category': 'Load Management',
            'action': 'Reduce load level or implement load shedding rotation',
            'reason': f'Generator (age: {age_years} years) is under extreme load stress. '
                      f'Operating above 75% capacity on an aging unit significantly accelerates wear and overheating.'
        })
    elif aals >= 0.60:
        recs.append({
            'priority': 'medium',
            'icon': '🌡️',
            'category': 'Load Management',
            'action': 'Consider distributing load across other circuits or adding a capacitor bank',
            'reason': f'Moderate-to-high load stress on a {age_years}-year-old generator. '
                      f'Allow cool-down periods between heavy load cycles.'
        })

    # ── Fault Frequency Recommendations ───────────────────
    if ffr >= 0.5:
        recs.append({
            'priority': 'critical',
            'icon': '🚨',
            'category': 'Fault Diagnosis',
            'action': 'DO NOT OPERATE — Contact a certified generator technician immediately',
            'reason': f'Extremely high fault rate ({ffr:.2f} faults/day). Multiple recurring failures indicate a systemic mechanical issue.'
        })
    elif ffr >= 0.3:
        recs.append({
            'priority': 'high',
            'icon': '⚠️',
            'category': 'Fault Diagnosis',
            'action': 'Perform diagnostic inspection — check AVR, starter, and alternator windings',
            'reason': f'High fault frequency ({ffr:.2f} faults/day). Common Nigerian generator faults at this rate: '
                      f'AVR failure, starter motor wear, or winding issues.'
        })
    elif ffr >= 0.1:
        recs.append({
            'priority': 'medium',
            'icon': '🔍',
            'category': 'Monitoring',
            'action': 'Log all fault types carefully and watch for patterns over the next 7 days',
            'reason': f'Moderate fault occurrence ({ffr:.2f} faults/day). Documenting type of faults helps identify root cause early.'
        })

    # ── Usage Intensity Recommendations ───────────────────
    if uii >= 0.85:
        recs.append({
            'priority': 'medium',
            'icon': '⏱️',
            'category': 'Usage Optimisation',
            'action': 'Implement a rest schedule — aim for max 18–20 hrs/day continuous operation',
            'reason': f'Operating at {int(uii*100)}% of maximum daily capacity. '
                      f'Continuous 24hrs/day operation without cool-down significantly shortens generator lifespan.'
        })

    # ── Age-specific advice ────────────────────────────────
    if age_years >= 8:
        recs.append({
            'priority': 'low',
            'icon': '📋',
            'category': 'Long-Term Planning',
            'action': 'Commission a full mechanical assessment for ageing generator',
            'reason': f'At {age_years} years old, major components (alternator windings, governor, injector pump) '
                      f'are approaching end of typical service life in Nigerian operating conditions.'
        })

    # ── Positive reinforcement if all is good ─────────────
    if not recs:
        recs.append({
            'priority': 'info',
            'icon': '✅',
            'category': 'Health Status',
            'action': 'Generator is in excellent condition — continue current maintenance schedule',
            'reason': f'All health indicators are within optimal range (CHS: {health_score}/100). '
                      f'Keep logging daily data to maintain predictive accuracy.'
        })

    # Sort by priority
    priority_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4}
    recs.sort(key=lambda r: priority_order.get(r['priority'], 9))
    return recs


# ═══════════════════════════════════════════════════════════
#  MAIN ENTRY POINT — Run Full Prediction Pipeline
# ═══════════════════════════════════════════════════════════

def run_prediction(generator, logs, maintenance_records):
    """
    Full three-layer prediction pipeline.

    Args:
        generator: Generator model object
        logs: list of DailyLog objects (recent entries, newest first)
        maintenance_records: list of MaintenanceRecord objects

    Returns:
        dict with all indicators, health score, risk level, recommendations
    """
    if not logs:
        return None  # Cannot predict without any log data

    # ─── LAYER 1: RAW DATA ─────────────────────────────────
    # Aggregate recent logs (use last 7 days for daily averages)
    recent_logs = logs[:7]
    all_logs_30d = logs[:30]

    avg_usage_hours = sum(l.usage_hours for l in recent_logs) / len(recent_logs)
    avg_load_level  = sum(l.load_level  for l in recent_logs) / len(recent_logs)
    avg_fuel        = sum(l.fuel_consumed for l in recent_logs) / len(recent_logs)
    total_faults    = sum(l.fault_count for l in all_logs_30d)
    days_tracked    = len(all_logs_30d)

    # Last maintenance date
    last_maint_date = None
    if maintenance_records:
        last_maint_date = maintenance_records[0].maintenance_date

    # ─── LAYER 2: PROCESSING — Compute Indicators ──────────
    uii  = compute_uii(avg_usage_hours)
    fer  = compute_fer(avg_fuel, generator.kva_rating, avg_load_level,
                       avg_usage_hours, generator.fuel_type)
    mos  = compute_mos(last_maint_date, avg_usage_hours,
                       generator.age_years, avg_load_level)
    aals = compute_aals(avg_load_level, generator.age_years, uii)
    ffr  = compute_ffr(total_faults, days_tracked)

    # ─── LAYER 3: PREDICTING — Score + Classify ────────────
    health_score, risk_level, model_used = compute_health_score(uii, fer, mos, aals, ffr)
    days_to_service = estimate_days_to_service(health_score, mos)
    recommendations = generate_recommendations(
        uii, fer, mos, aals, ffr, risk_level, health_score,
        generator.age_years, generator.fuel_type
    )

    return {
        # Layer 2 indicators
        'uii':  round(uii, 3),
        'fer':  round(fer, 3),
        'mos':  round(mos, 3),
        'aals': round(aals, 3),
        'ffr':  round(ffr, 3),
        # Layer 3 outputs
        'health_score':    health_score,
        'risk_level':      risk_level,
        'model_used':      model_used,
        'days_to_service': days_to_service,
        'recommendations': json.dumps(recommendations),
        'logs_used':       days_tracked,
        # Metadata
        'avg_usage_hours': round(avg_usage_hours, 2),
        'avg_load_level':  round(avg_load_level, 1),
        'avg_fuel':        round(avg_fuel, 2),
    }

