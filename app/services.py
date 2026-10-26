from flask import g, current_app
from flask_smorest import abort
from flask_jwt_extended import get_jwt
from sqlalchemy import select, func
from werkzeug.security import generate_password_hash
from .extensions import db
from .models import User, SecurityLock


def mutation_lock():
    lock = db.session.execute(
        select(SecurityLock).where(SecurityLock.id == 1).with_for_update()
    ).scalar_one_or_none()
    if lock is None:
        abort(503, message="Ejecute las migraciones antes de operar.")
    if hasattr(g, "user"):
        actor = db.session.execute(
            select(User).where(User.id == g.user.id).execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if actor is None or actor.token_version != get_jwt().get("ver"):
            abort(401, message="Sesión revocada durante la operación.")
        if actor.role != "admin":
            abort(403, message="Permiso de administrador revocado.")


def ensure_admin():
    db.session.flush()
    if db.session.scalar(select(func.count()).select_from(User).where(User.role == "admin")) == 0:
        abort(409, message="Debe conservar al menos un administrador.")


def get_user(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404, message="Usuario no encontrado.")
    return user


def create_user(data):
    mutation_lock()
    values = dict(data)
    password = values.pop("password")
    user = User(**values, password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()
    current_app.logger.info(
        "user_created actor=%s target=%s", getattr(g, "user", None) and g.user.id, user.id
    )
    return user


def update_user(user_id, data):
    mutation_lock()
    user = get_user(user_id)
    for key, value in data.items():
        if key == "password":
            user.password_hash = generate_password_hash(value)
        else:
            setattr(user, key, value)
    if "role" in data or "password" in data:
        user.token_version += 1
    ensure_admin()
    db.session.commit()
    current_app.logger.info("user_updated actor=%s target=%s", g.user.id, user_id)
    return user


def delete_users(ids):
    mutation_lock()
    users = [get_user(user_id) for user_id in sorted(set(ids))]
    actor = g.user.id
    for user in users:
        db.session.delete(user)
    ensure_admin()
    db.session.commit()
    current_app.logger.info("users_deleted actor=%s targets=%s", actor, sorted(set(ids)))
