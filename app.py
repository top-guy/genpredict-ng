import os
from flask import Flask
from extensions import db, login_manager
from models import User
from dotenv import load_dotenv

load_dotenv()


def create_app():
    app = Flask(__name__)

    # ── Config ─────────────────────────────────────────────
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-CHANGE-IN-PRODUCTION')

    # Handle Render's postgres:// → postgresql:// (SQLAlchemy requirement)
    db_url = os.environ.get('DATABASE_URL', 'sqlite:///genpredict.db')
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2MB max upload

    # ── Extensions ─────────────────────────────────────────
    db.init_app(app)
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # ── Blueprints ─────────────────────────────────────────
    from auth import auth_bp
    from routes import main_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp)

    # ── DB Init ────────────────────────────────────────────
    with app.app_context():
        db.create_all()

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1')
