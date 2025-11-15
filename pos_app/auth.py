from __future__ import annotations

from functools import wraps
from typing import Callable, TypeVar

from flask import (
    Blueprint,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

F = TypeVar("F", bound=Callable[..., object])

auth_blueprint = Blueprint("auth", __name__, url_prefix="/auth")


def login_required(role: str) -> Callable[[F], F]:
    """Simple role-based access decorator using Flask sessions."""

    def decorator(view: F) -> F:
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = session.get("user")
            if not user or role not in user.get("roles", []):
                next_url = request.url
                return redirect(url_for("auth.login", role=role, next=next_url))
            return view(*args, **kwargs)

        return wrapped  # type: ignore[return-value]

    return decorator


@auth_blueprint.route("/login", methods=["GET", "POST"])
def login():
    role = request.args.get("role", "kitchen")
    next_url = request.args.get("next") or url_for("main.home")
    error = None

    if request.method == "POST":
        role = request.form.get("role", role)
        next_url = request.form.get("next") or next_url
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user_config = current_app.config["AUTH_USERS"].get(role)

        if user_config and username == user_config["username"] and password == user_config["password"]:
            session["user"] = {
                "username": username,
                "roles": user_config.get("roles", [role]),
            }
            return redirect(next_url)

        error = "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"

    return render_template(
        "auth/login.html",
        role=role,
        next_url=next_url,
        error=error,
    )


@auth_blueprint.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("main.home"))
