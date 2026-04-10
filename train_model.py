"""
train_model.py
==============
Generates synthetic training data from domain formulas and trains
a Random Forest model for the GenPredict NG Layer 3 Prediction.

Run once before starting the app:
    python train_model.py

The trained model is saved to model/rf_health_model.pkl
"""

import os
import json
import numpy as np
import joblib
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, mean_absolute_error
from sklearn.preprocessing import LabelEncoder

# ── Reproducibility ─────────────────────────────────────────
np.random.seed(42)
N_SAMPLES = 15000

os.makedirs('model', exist_ok=True)

print("=" * 55)
print("GenPredict NG — Model Training")
print("Generating synthetic training data...")
print("=" * 55)


# ═══════════════════════════════════════════════════════════
#  SYNTHETIC DATA GENERATION
#  Based on the same domain knowledge as prediction_engine.py
#  but we sample the input space broadly and add realistic noise
# ═══════════════════════════════════════════════════════════

def _fer_penalty(fer):
    if fer <= 1.0: return 0
    return min((fer - 1.0) * 150, 100)

def _mos_penalty(mos):
    if mos < 0.7: return 0
    return min((mos - 0.7) * 200, 100)

def _aals_penalty(aals):
    return min(aals * 90, 100)

def _ffr_penalty(ffr):
    return min(ffr * 200, 100)

def _uii_penalty(uii):
    return uii * 80

def _formula_chs(uii, fer, mos, aals, ffr):
    """Pure formula CHS — this is what the model learns to approximate
    (and improve with non-linear interactions)."""
    penalties = {
        'uii':  _uii_penalty(uii)  * 0.20,
        'fer':  _fer_penalty(fer)  * 0.25,
        'mos':  _mos_penalty(mos)  * 0.25,
        'aals': _aals_penalty(aals) * 0.15,
        'ffr':  _ffr_penalty(ffr)  * 0.15,
    }
    return max(0.0, 100.0 - sum(penalties.values()))

def _classify(chs):
    if chs >= 75: return 'HEALTHY'
    if chs >= 50: return 'MODERATE'
    if chs >= 25: return 'HIGH RISK'
    return 'CRITICAL'


# Sample the raw input space
uii_samples  = np.random.beta(2, 3, N_SAMPLES)           # skew toward moderate use
fer_samples  = np.random.lognormal(0.05, 0.25, N_SAMPLES) # centered near 1.1
mos_samples  = np.random.exponential(0.9, N_SAMPLES)       # often approaching or past due
aals_samples = np.clip(np.random.beta(2, 2.5, N_SAMPLES), 0, 1.5)
ffr_samples  = np.random.exponential(0.08, N_SAMPLES)      # mostly low, some high

fer_samples  = np.clip(fer_samples, 0.7, 2.5)
mos_samples  = np.clip(mos_samples, 0.1, 2.5)
ffr_samples  = np.clip(ffr_samples, 0.0, 0.8)

# ── Interaction effects (this is what the RF learns beyond linear) ──
# Old gen + high load + overdue = synergistic failure risk
# We encode this as a small interaction bonus to penalty
interaction_penalty = (
    (aals_samples > 0.7).astype(float) *
    (mos_samples > 1.0).astype(float) *
    (ffr_samples > 0.2).astype(float) * 8.0  # extra 8-point CHS drop
)

# Fuel system degradation: high FER + high load = accelerating wear
fuel_load_interaction = (
    np.clip((fer_samples - 1.2), 0, None) * (aals_samples > 0.6).astype(float) * 12.0
)

# Compute CHS with interactions
base_chs = np.array([
    _formula_chs(u, f, m, a, r)
    for u, f, m, a, r in zip(uii_samples, fer_samples, mos_samples, aals_samples, ffr_samples)
])

# Apply interaction effects + realistic noise
chs_with_interactions = np.clip(
    base_chs - interaction_penalty - fuel_load_interaction + np.random.normal(0, 2, N_SAMPLES),
    0, 100
)

# Build feature matrix and labels
X = np.column_stack([uii_samples, fer_samples, mos_samples, aals_samples, ffr_samples])
y_chs   = chs_with_interactions
y_class = np.array([_classify(c) for c in y_chs])

print(f"Generated {N_SAMPLES:,} samples")
print(f"Class distribution:")
for cls in ['HEALTHY', 'MODERATE', 'HIGH RISK', 'CRITICAL']:
    count = np.sum(y_class == cls)
    print(f"  {cls:<12}: {count:>5} ({count/N_SAMPLES*100:.1f}%)")


# ═══════════════════════════════════════════════════════════
#  TRAIN MODELS
# ═══════════════════════════════════════════════════════════

X_train, X_test, yc_train, yc_test, yr_train, yr_test = train_test_split(
    X, y_class, y_chs, test_size=0.2, random_state=42, stratify=y_class
)

# ── Model 1: Risk Classifier ───────────────────────────────
print("\nTraining Risk Classifier (Random Forest)...")
clf = RandomForestClassifier(
    n_estimators=200,
    max_depth=12,
    min_samples_leaf=5,
    class_weight='balanced',
    n_jobs=-1,
    random_state=42
)
clf.fit(X_train, yc_train)

yc_pred = clf.predict(X_test)
print("\nClassifier Performance:")
print(classification_report(yc_test, yc_pred))

# ── Model 2: Health Score Regressor ───────────────────────
print("Training Health Score Regressor (Random Forest)...")
reg = RandomForestRegressor(
    n_estimators=200,
    max_depth=14,
    min_samples_leaf=3,
    n_jobs=-1,
    random_state=42
)
reg.fit(X_train, yr_train)

yr_pred = reg.predict(X_test)
mae = mean_absolute_error(yr_test, yr_pred)
print(f"Regressor MAE: {mae:.2f} CHS points")

# ── Feature Importance ─────────────────────────────────────
feature_names = ['UII', 'FER', 'MOS', 'AALS', 'FFR']
importances   = reg.feature_importances_
print("\nFeature Importances (Regressor):")
for name, imp in sorted(zip(feature_names, importances), key=lambda x: -x[1]):
    bar = '#' * int(imp * 40)
    print(f"  {name:<6} {bar} {imp:.3f}")


# ═══════════════════════════════════════════════════════════
#  SAVE MODELS AND METADATA
# ═══════════════════════════════════════════════════════════

joblib.dump(clf, 'model/rf_classifier.pkl', compress=3)
joblib.dump(reg, 'model/rf_regressor.pkl', compress=3)

metadata = {
    'feature_names': feature_names,
    'classes':       clf.classes_.tolist(),
    'n_samples':     N_SAMPLES,
    'regressor_mae': round(float(mae), 3),
    'feature_importances': dict(zip(feature_names, importances.tolist())),
    'note': 'Trained on synthetic data. Retrain with real outcomes as they accumulate.'
}

with open('model/metadata.json', 'w') as f:
    json.dump(metadata, f, indent=2)

print("\n" + "=" * 55)
print("[OK] Models saved to model/")
print(f"   rf_classifier.pkl  - Risk level prediction")
print(f"   rf_regressor.pkl   - Health score (0-100)")
print(f"   metadata.json      - Feature names & stats")
print("=" * 55)
print("\nTo retrain with real data, add outcome labels to your")
print("DailyLog records and call retrain_with_real_data() in train_model.py")
