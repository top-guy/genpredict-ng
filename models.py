from datetime import datetime
from flask_login import UserMixin
import bcrypt
from extensions import db


# ─────────────────────────────────────────────
#  USER MODEL
# ─────────────────────────────────────────────
class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id           = db.Column(db.Integer, primary_key=True)
    username     = db.Column(db.String(80), unique=True, nullable=False)
    email        = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    business_name = db.Column(db.String(150))
    phone        = db.Column(db.String(20))
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    generators   = db.relationship('Generator', backref='owner', lazy=True,
                                   cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(
            password.encode('utf-8'), bcrypt.gensalt()
        ).decode('utf-8')

    def check_password(self, password):
        return bcrypt.checkpw(
            password.encode('utf-8'),
            self.password_hash.encode('utf-8')
        )

    @property
    def generator_count(self):
        return len(self.generators)

    def can_add_generator(self):
        return self.generator_count < 2

    def __repr__(self):
        return f'<User {self.username}>'


# ─────────────────────────────────────────────
#  GENERATOR MODEL
# ─────────────────────────────────────────────
NIGERIAN_BRANDS = [
    'Sumec', 'Firman', 'Elepaq', 'Tiger', 'Thermocool',
    'Mikano', 'Perkins', 'FG Wilson', 'Cummins', 'Lister',
    'Honda', 'Yamaha', 'Kipor', 'Other'
]

FUEL_TYPES = ['Diesel', 'Petrol', 'Gas (LPG)']


class Generator(db.Model):
    __tablename__ = 'generators'

    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name           = db.Column(db.String(100), nullable=False)  # e.g. "Office Gen"
    make           = db.Column(db.String(80))                   # brand
    model          = db.Column(db.String(80))
    kva_rating     = db.Column(db.Float, nullable=False)        # e.g. 10.0 KVA
    fuel_type      = db.Column(db.String(20), default='Diesel')
    purchase_year  = db.Column(db.Integer)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    daily_logs         = db.relationship('DailyLog', backref='generator', lazy=True,
                                         cascade='all, delete-orphan',
                                         order_by='DailyLog.log_date.desc()')
    predictions        = db.relationship('Prediction', backref='generator', lazy=True,
                                         cascade='all, delete-orphan',
                                         order_by='Prediction.computed_at.desc()')
    maintenance_records = db.relationship('MaintenanceRecord', backref='generator', lazy=True,
                                          cascade='all, delete-orphan',
                                          order_by='MaintenanceRecord.maintenance_date.desc()')

    @property
    def age_years(self):
        if self.purchase_year:
            return max(0, datetime.utcnow().year - self.purchase_year)
        return 0

    @property
    def latest_prediction(self):
        return self.predictions[0] if self.predictions else None

    @property
    def latest_log(self):
        return self.daily_logs[0] if self.daily_logs else None

    @property
    def last_maintenance_date(self):
        if self.maintenance_records:
            return self.maintenance_records[0].maintenance_date
        return None

    def __repr__(self):
        return f'<Generator {self.name} ({self.kva_rating} KVA)>'


# ─────────────────────────────────────────────
#  DAILY LOG MODEL  (Raw Layer inputs)
# ─────────────────────────────────────────────
FAULT_TYPES = [
    'Overheating', 'Excessive Smoke', 'Oil Pressure Warning',
    'Voltage Fluctuation', 'Frequent Shutdown', 'Hard Starting',
    'Abnormal Noise', 'Fuel Leak', 'Battery Issue', 'Other'
]


class DailyLog(db.Model):
    __tablename__ = 'daily_logs'

    id               = db.Column(db.Integer, primary_key=True)
    generator_id     = db.Column(db.Integer, db.ForeignKey('generators.id'), nullable=False)
    log_date         = db.Column(db.Date, nullable=False, default=datetime.utcnow().date)
    usage_hours      = db.Column(db.Float, nullable=False)       # 0–24 hrs
    load_level       = db.Column(db.Integer, nullable=False)     # 0–100 %
    fuel_consumed    = db.Column(db.Float, nullable=False)       # litres/day
    fault_count      = db.Column(db.Integer, default=0)
    fault_types      = db.Column(db.String(300))                 # comma-separated
    nepa_outage_hours = db.Column(db.Float, default=0)           # PHCN/NEPA hours without power
    notes            = db.Column(db.Text)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<DailyLog {self.log_date} - Gen#{self.generator_id}>'


# ─────────────────────────────────────────────
#  MAINTENANCE RECORD MODEL
# ─────────────────────────────────────────────
MAINTENANCE_TYPES = [
    'Routine Oil Change', 'Filter Replacement (Oil/Fuel/Air)',
    'Spark Plug / Injector Service', 'Coolant Check & Top-up',
    'Belt & Hose Inspection', 'Battery Service',
    'Full Service (Major)', 'Repair / Part Replacement', 'Other'
]


class MaintenanceRecord(db.Model):
    __tablename__ = 'maintenance_records'

    id               = db.Column(db.Integer, primary_key=True)
    generator_id     = db.Column(db.Integer, db.ForeignKey('generators.id'), nullable=False)
    maintenance_date = db.Column(db.Date, nullable=False)
    maintenance_type = db.Column(db.String(100))
    description      = db.Column(db.Text)
    cost_naira       = db.Column(db.Float)
    technician       = db.Column(db.String(100))
    next_due_date    = db.Column(db.Date)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Maintenance {self.maintenance_date} - {self.maintenance_type}>'


# ─────────────────────────────────────────────
#  PREDICTION MODEL  (Predicting Layer output)
# ─────────────────────────────────────────────
RISK_LEVELS = ['HEALTHY', 'MODERATE', 'HIGH RISK', 'CRITICAL']


class Prediction(db.Model):
    __tablename__ = 'predictions'

    id              = db.Column(db.Integer, primary_key=True)
    generator_id    = db.Column(db.Integer, db.ForeignKey('generators.id'), nullable=False)
    computed_at     = db.Column(db.DateTime, default=datetime.utcnow)

    # Processing Layer — derived indicators (0–1 normalized except CHS)
    health_score    = db.Column(db.Float)   # CHS: 0–100
    risk_level      = db.Column(db.String(20))   # HEALTHY/MODERATE/HIGH RISK/CRITICAL
    uii             = db.Column(db.Float)   # Usage Intensity Index
    fer             = db.Column(db.Float)   # Fuel Efficiency Ratio
    mos             = db.Column(db.Float)   # Maintenance Overdue Score
    aals            = db.Column(db.Float)  # Age-Adjusted Load Stress
    ffr             = db.Column(db.Float)   # Fault Frequency Rate

    # Predicting Layer — output
    recommendations = db.Column(db.Text)    # JSON string
    days_to_service = db.Column(db.Integer) # Estimated days until next service needed
    logs_used       = db.Column(db.Integer) # Number of log entries used in prediction
    model_used      = db.Column(db.String(50)) # Model used for prediction

    def __repr__(self):
        return f'<Prediction CHS={self.health_score} Risk={self.risk_level} Gen#{self.generator_id}>'
