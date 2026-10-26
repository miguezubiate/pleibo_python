from functools import wraps
from flask import g, current_app
from flask_jwt_extended import verify_jwt_in_request, get_jwt, get_jwt_identity
from flask_smorest import abort
from .extensions import db
from .models import User


def require_user(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            verify_jwt_in_request()
            try:
                user_id = int(get_jwt_identity())
            except (TypeError, ValueError):
                abort(401, message="Token inválido.")
            user = db.session.get(User, user_id)
            if not user or user.token_version != get_jwt().get("ver"):
                abort(401, message="Sesión inválida; inicie sesión nuevamente.")
            if role and user.role != role:
                abort(403, message="No cuenta con permisos suficientes.")
            g.user = user
            return fn(*args, **kwargs)

        return wrapped

    return decorator


def register_jwt(jwt):
    @jwt.token_in_blocklist_loader
    def revoked(header, payload):
        return bool(current_app.extensions["redis"].exists("revoked:" + payload["jti"]))

    @jwt.expired_token_loader
    def expired(header, payload):
        return {"code": 401, "message": "Token expirado."}, 401

    @jwt.invalid_token_loader
    def invalid(reason):
        return {"code": 401, "message": "Token inválido."}, 401

    @jwt.unauthorized_loader
    def missing(reason):
        return {"code": 401, "message": "Se requiere un Bearer Token para la petición."}, 401

    @jwt.revoked_token_loader
    def blocked(header, payload):
        return {"code": 401, "message": "Token revocado."}, 401
