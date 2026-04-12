import json
from datetime import datetime, date, timedelta
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, abort, make_response, jsonify, send_file)
from flask_login import login_required, current_user

from extensions import db
from models import (Generator, DailyLog, Prediction, MaintenanceRecord,
                    NIGERIAN_BRANDS, FUEL_TYPES, FAULT_TYPES, MAINTENANCE_TYPES)
from prediction_engine import run_prediction
from report_gen import generate_pdf_report, generate_whatsapp_link

main_bp = Blueprint('main', __name__, template_folder='templates')


def _get_generator_or_404(gen_id):
    """Fetch a generator that belongs to the current user, else 404."""
    gen = Generator.query.get_or_404(gen_id)
    if gen.user_id != current_user.id:
        abort(403)
    return gen


# ═══════════════════════════════════════════════════════════
#  LANDING / INDEX
# ═══════════════════════════════════════════════════════════
@main_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('index.html')


# ═══════════════════════════════════════════════════════════
#  DASHBOARD
# ═══════════════════════════════════════════════════════════
@main_bp.route('/dashboard')
@login_required
def dashboard():
    generators = Generator.query.filter_by(user_id=current_user.id).all()

    # Build summary cards
    gen_cards = []
    for gen in generators:
        pred = gen.latest_prediction
        last_log = gen.latest_log
        gen_cards.append({
            'generator': gen,
            'prediction': pred,
            'last_log': last_log,
            'logs_count': len(gen.daily_logs),
        })

    return render_template('dashboard.html',
                           gen_cards=gen_cards,
                           can_add=current_user.can_add_generator())


# ═══════════════════════════════════════════════════════════
#  GENERATORS
# ═══════════════════════════════════════════════════════════
@main_bp.route('/generators/add', methods=['GET', 'POST'])
@login_required
def add_generator():
    if not current_user.can_add_generator():
        flash('You have reached the maximum of 2 generators per account.', 'warning')
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        name         = request.form.get('name', '').strip()
        make         = request.form.get('make', '').strip()
        model        = request.form.get('model', '').strip()
        kva_rating   = request.form.get('kva_rating', type=float)
        fuel_type    = request.form.get('fuel_type', 'Diesel')
        purchase_year = request.form.get('purchase_year', type=int)

        if not name or not kva_rating:
            flash('Generator name and KVA rating are required.', 'danger')
            return render_template('generators/add.html',
                                   brands=NIGERIAN_BRANDS, fuel_types=FUEL_TYPES)

        gen = Generator(
            user_id=current_user.id,
            name=name, make=make, model=model,
            kva_rating=kva_rating, fuel_type=fuel_type,
            purchase_year=purchase_year
        )
        db.session.add(gen)
        db.session.commit()
        flash(f'Generator "{name}" added successfully!', 'success')
        return redirect(url_for('main.generator_detail', gen_id=gen.id))

    return render_template('generators/add.html',
                           brands=NIGERIAN_BRANDS, fuel_types=FUEL_TYPES)


@main_bp.route('/generators/<int:gen_id>')
@login_required
def generator_detail(gen_id):
    gen = _get_generator_or_404(gen_id)
    recent_logs = gen.daily_logs[:10]
    recent_preds = gen.predictions[:5]
    maintenance = gen.maintenance_records[:5]
    return render_template('generators/detail.html',
                           gen=gen,
                           recent_logs=recent_logs,
                           recent_preds=recent_preds,
                           maintenance=maintenance)


@main_bp.route('/generators/<int:gen_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_generator(gen_id):
    gen = _get_generator_or_404(gen_id)

    if request.method == 'POST':
        gen.name         = request.form.get('name', gen.name).strip()
        gen.make         = request.form.get('make', '').strip()
        gen.model        = request.form.get('model', '').strip()
        gen.kva_rating   = request.form.get('kva_rating', type=float) or gen.kva_rating
        gen.fuel_type    = request.form.get('fuel_type', gen.fuel_type)
        gen.purchase_year = request.form.get('purchase_year', type=int) or gen.purchase_year
        db.session.commit()
        flash('Generator updated successfully.', 'success')
        return redirect(url_for('main.generator_detail', gen_id=gen.id))

    return render_template('generators/edit.html',
                           gen=gen, brands=NIGERIAN_BRANDS, fuel_types=FUEL_TYPES)


@main_bp.route('/generators/<int:gen_id>/delete', methods=['POST'])
@login_required
def delete_generator(gen_id):
    gen = _get_generator_or_404(gen_id)
    name = gen.name
    db.session.delete(gen)
    db.session.commit()
    flash(f'Generator "{name}" has been deleted.', 'info')
    return redirect(url_for('main.dashboard'))


# ═══════════════════════════════════════════════════════════
#  DAILY LOGS
# ═══════════════════════════════════════════════════════════
@main_bp.route('/generators/<int:gen_id>/logs/add', methods=['GET', 'POST'])
@login_required
def add_log(gen_id):
    gen = _get_generator_or_404(gen_id)

    if request.method == 'POST':
        log_date_str  = request.form.get('log_date', '')
        usage_hours   = request.form.get('usage_hours', type=float)
        load_level    = request.form.get('load_level', type=int)
        fuel_consumed = request.form.get('fuel_consumed', type=float)
        fault_count   = request.form.get('fault_count', 0, type=int)
        fault_types_list = request.form.getlist('fault_types')
        nepa_hours    = request.form.get('nepa_outage_hours', 0.0, type=float)
        notes         = request.form.get('notes', '').strip()

        if not usage_hours or load_level is None or fuel_consumed is None:
            flash('Usage hours, load level, and fuel consumed are required.', 'danger')
            return render_template('logs/add_log.html', gen=gen, fault_types=FAULT_TYPES,
                                   today=date.today().isoformat())

        try:
            log_date = datetime.strptime(log_date_str, '%Y-%m-%d').date()
        except ValueError:
            log_date = date.today()

        # Check for duplicate log on same date
        existing = DailyLog.query.filter_by(
            generator_id=gen.id, log_date=log_date
        ).first()
        if existing:
            flash(f'A log entry for {log_date} already exists for this generator. '
                  f'Edit or delete it first.', 'warning')
            return render_template('logs/add_log.html', gen=gen, fault_types=FAULT_TYPES,
                                   today=date.today().isoformat())

        log = DailyLog(
            generator_id=gen.id,
            log_date=log_date,
            usage_hours=min(usage_hours, 24.0),
            load_level=max(0, min(load_level, 100)),
            fuel_consumed=max(0.0, fuel_consumed),
            fault_count=fault_count,
            fault_types=', '.join(fault_types_list) if fault_types_list else None,
            nepa_outage_hours=min(nepa_hours, 24.0),
            notes=notes
        )
        db.session.add(log)
        db.session.commit()
        flash('Daily log entry saved! You can now run a prediction.', 'success')
        return redirect(url_for('main.generator_detail', gen_id=gen.id))

    return render_template('logs/add_log.html', gen=gen,
                           fault_types=FAULT_TYPES,
                           today=date.today().isoformat())


@main_bp.route('/generators/<int:gen_id>/logs')
@login_required
def log_history(gen_id):
    gen = _get_generator_or_404(gen_id)
    page = request.args.get('page', 1, type=int)
    logs = DailyLog.query.filter_by(generator_id=gen.id)\
                         .order_by(DailyLog.log_date.desc())\
                         .paginate(page=page, per_page=15, error_out=False)
    return render_template('logs/history.html', gen=gen, logs=logs)


@main_bp.route('/generators/<int:gen_id>/logs/<int:log_id>/delete', methods=['POST'])
@login_required
def delete_log(gen_id, log_id):
    gen = _get_generator_or_404(gen_id)
    log = DailyLog.query.get_or_404(log_id)
    if log.generator_id != gen.id:
        abort(403)
    db.session.delete(log)
    db.session.commit()
    flash('Log entry deleted.', 'info')
    return redirect(url_for('main.log_history', gen_id=gen.id))


# ═══════════════════════════════════════════════════════════
#  PREDICTIONS
# ═══════════════════════════════════════════════════════════
@main_bp.route('/generators/<int:gen_id>/predict')
@login_required
def run_prediction_view(gen_id):
    gen = _get_generator_or_404(gen_id)

    logs = DailyLog.query.filter_by(generator_id=gen.id)\
                         .order_by(DailyLog.log_date.desc()).all()
    if not logs:
        flash('You need at least one daily log entry before running a prediction.', 'warning')
        return redirect(url_for('main.add_log', gen_id=gen.id))

    maintenance = gen.maintenance_records

    # Run the 3-layer engine
    result = run_prediction(gen, logs, maintenance)
    if not result:
        flash('Unable to compute prediction. Please add more log data.', 'danger')
        return redirect(url_for('main.generator_detail', gen_id=gen.id))

    pred = Prediction(
        generator_id    = gen.id,
        health_score    = result['health_score'],
        risk_level      = result['risk_level'],
        uii             = result['uii'],
        fer             = result['fer'],
        mos             = result['mos'],
        aals            = result['aals'],
        ffr             = result['ffr'],
        recommendations = result['recommendations'],
        days_to_service = result['days_to_service'],
        logs_used       = result['logs_used'],
        model_used      = result['model_used'],
    )
    db.session.add(pred)
    db.session.commit()

    recs = json.loads(result['recommendations'])
    wa_link = generate_whatsapp_link(gen, pred)

    return render_template('predictions/result.html',
                           gen=gen, pred=pred, recs=recs,
                           wa_link=wa_link,
                           result=result)


@main_bp.route('/generators/<int:gen_id>/predictions')
@login_required
def prediction_history(gen_id):
    gen = _get_generator_or_404(gen_id)
    page = request.args.get('page', 1, type=int)
    preds = Prediction.query.filter_by(generator_id=gen.id)\
                            .order_by(Prediction.computed_at.desc())\
                            .paginate(page=page, per_page=10, error_out=False)
    return render_template('predictions/history.html', gen=gen, preds=preds)


# ═══════════════════════════════════════════════════════════
#  MAINTENANCE RECORDS
# ═══════════════════════════════════════════════════════════
@main_bp.route('/generators/<int:gen_id>/maintenance/add', methods=['GET', 'POST'])
@login_required
def add_maintenance(gen_id):
    gen = _get_generator_or_404(gen_id)

    if request.method == 'POST':
        maint_date_str   = request.form.get('maintenance_date', '')
        maint_type       = request.form.get('maintenance_type', '')
        description      = request.form.get('description', '').strip()
        cost_naira       = request.form.get('cost_naira', None, type=float)
        technician       = request.form.get('technician', '').strip()
        next_due_str     = request.form.get('next_due_date', '')

        try:
            maint_date = datetime.strptime(maint_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid maintenance date.', 'danger')
            return render_template('maintenance/add.html', gen=gen,
                                   maint_types=MAINTENANCE_TYPES,
                                   today=date.today().isoformat())

        next_due = None
        if next_due_str:
            try:
                next_due = datetime.strptime(next_due_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        record = MaintenanceRecord(
            generator_id=gen.id,
            maintenance_date=maint_date,
            maintenance_type=maint_type,
            description=description,
            cost_naira=cost_naira,
            technician=technician,
            next_due_date=next_due
        )
        db.session.add(record)
        db.session.commit()
        flash('Maintenance record saved! Run a new prediction to see updated health score.', 'success')
        return redirect(url_for('main.generator_detail', gen_id=gen.id))

    return render_template('maintenance/add.html', gen=gen,
                           maint_types=MAINTENANCE_TYPES,
                           today=date.today().isoformat())


# ═══════════════════════════════════════════════════════════
#  REPORTS — PDF & WhatsApp
# ═══════════════════════════════════════════════════════════
@main_bp.route('/generators/<int:gen_id>/report/pdf')
@login_required
def download_pdf_report(gen_id):
    gen = _get_generator_or_404(gen_id)
    pred = gen.latest_prediction

    if not pred:
        flash('Run a prediction first before downloading a report.', 'warning')
        return redirect(url_for('main.generator_detail', gen_id=gen.id))

    logs = DailyLog.query.filter_by(generator_id=gen.id)\
                         .order_by(DailyLog.log_date.desc()).limit(7).all()
    maintenance = gen.maintenance_records[:5]

    pdf_bytes = generate_pdf_report(gen, pred, maintenance, logs)
    filename  = f"genpredict_{gen.name.replace(' ', '_')}_{date.today()}.pdf"

    return send_file(
        pdf_bytes,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )


@main_bp.route('/generators/<int:gen_id>/report/whatsapp')
@login_required
def whatsapp_share(gen_id):
    gen = _get_generator_or_404(gen_id)
    pred = gen.latest_prediction
    if not pred:
        flash('Run a prediction first before sharing a report.', 'warning')
        return redirect(url_for('main.generator_detail', gen_id=gen.id))

    wa_link = generate_whatsapp_link(gen, pred)
    return redirect(wa_link)


# ═══════════════════════════════════════════════════════════
#  JSON API — Chart Data
# ═══════════════════════════════════════════════════════════
@main_bp.route('/api/generators/<int:gen_id>/trend')
@login_required
def api_trend(gen_id):
    gen = _get_generator_or_404(gen_id)

    # Last 30 prediction scores for trend chart
    preds = Prediction.query.filter_by(generator_id=gen.id)\
                            .order_by(Prediction.computed_at.asc()).limit(30).all()
    labels = [p.computed_at.strftime('%d %b %y') for p in preds]
    scores = [p.health_score for p in preds]
    risks  = [p.risk_level for p in preds]

    return jsonify({'labels': labels, 'scores': scores, 'risks': risks})


@main_bp.route('/api/generators/<int:gen_id>/logs/trend')
@login_required
def api_logs_trend(gen_id):
    gen = _get_generator_or_404(gen_id)

    # Last 14 daily logs for usage chart
    logs = DailyLog.query.filter_by(generator_id=gen.id)\
                         .order_by(DailyLog.log_date.asc()).limit(14).all()
    labels  = [l.log_date.strftime('%d %b') for l in logs]
    usage   = [l.usage_hours for l in logs]
    load    = [l.load_level for l in logs]
    fuel    = [l.fuel_consumed for l in logs]
    faults  = [l.fault_count for l in logs]

    return jsonify({
        'labels': labels,
        'usage': usage, 'load': load,
        'fuel': fuel, 'faults': faults
    })
