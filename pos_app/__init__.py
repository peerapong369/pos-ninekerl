import os
from pathlib import Path

from flask import Flask, session
from dotenv import load_dotenv

from .auth import auth_blueprint
from .database import init_db, db_session
from .models import seed_sample_data
from .views import main_blueprint


BASE_DIR = Path(__file__).resolve().parent.parent


def create_app():
    load_dotenv()

    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    app.config.from_mapping(
        SECRET_KEY="dev-secret-key",
        SQLALCHEMY_DATABASE_URI="sqlite:///pos.db",
        SQLALCHEMY_ECHO=False,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_NAME="pos_ninekerl_session",
        PROMPTPAY_TARGET=os.getenv("PROMPTPAY_TARGET", "0823293693"),
        LINE_CHANNEL_ACCESS_TOKEN=os.getenv("LINE_CHANNEL_ACCESS_TOKEN"),
        LINE_CHANNEL_SECRET=os.getenv("LINE_CHANNEL_SECRET"),
        TABLE_MENU_BASE_URL=os.getenv("TABLE_MENU_BASE_URL"),
    )

    upload_dir = BASE_DIR / "static" / "uploads" / "menu"
    upload_dir.mkdir(parents=True, exist_ok=True)
    app.config["MENU_IMAGE_UPLOAD_FOLDER"] = str(upload_dir)
    app.config["MENU_IMAGE_RELATIVE_FOLDER"] = "uploads/menu"
    app.config["MENU_IMAGE_ALLOWED_EXTENSIONS"] = {"png", "jpg", "jpeg", "gif", "webp", "svg"}

    app.config["AUTH_USERS"] = {
        "kitchen": {
            "username": os.getenv("KITCHEN_USERNAME", "kitchen"),
            "password": os.getenv("KITCHEN_PASSWORD", "kitchen123"),
            "roles": ["kitchen"],
        },
        "admin": {
            "username": os.getenv("ADMIN_USERNAME", "admin"),
            "password": os.getenv("ADMIN_PASSWORD", "admin123"),
            "roles": ["admin", "kitchen"],
        },
        "adminpp": {
            "username": os.getenv("ADMIN_PLUS_USERNAME", "adminpp"),
            "password": os.getenv("ADMIN_PLUS_PASSWORD", "adminpp123"),
            "roles": ["admin", "kitchen", "adminpp"],
        },
    }

    init_db(app.config["SQLALCHEMY_DATABASE_URI"])
    seed_sample_data()
    app.register_blueprint(auth_blueprint)
    app.register_blueprint(main_blueprint)

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        db_session.remove()

    @app.context_processor
    def inject_user():
        return {"current_user": session.get("user")}

    return app
