import logging
import os
import time
import uuid
from datetime import timedelta
from urllib.parse import urlparse
import click
import redis
from flask import Flask, g, request
from flask_smorest import Api
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash
from .extensions import db, migrate, jwt, limiter
from .security import register_jwt
from .ghibli import build_session


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True, "pool_recycle": 280},
        JWT_SECRET_KEY=os.getenv("JWT_SECRET_KEY"),
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
        JWT_TOKEN_LOCATION=["headers"],
        JWT_DECODE_ISSUER="ghibli-users-api",
        JWT_ENCODE_ISSUER="ghibli-users-api",
        JWT_DECODE_AUDIENCE="ghibli-users",
        JWT_ENCODE_AUDIENCE="ghibli-users",
        REDIS_URL=os.getenv("REDIS_URL", "redis://redis:6379/0"),
        RATELIMIT_STORAGE_URI=os.getenv("REDIS_URL", "redis://redis:6379/0"),
        RATELIMIT_SWALLOW_ERRORS=False,
        GHIBLI_BASE_URL=os.getenv("GHIBLI_BASE_URL", "https://ghibliapi.vercel.app").rstrip("/"),
        API_TITLE="Users & Ghibli API",
        API_VERSION="v1",
        OPENAPI_VERSION="3.0.3",
        OPENAPI_URL_PREFIX="/",
        OPENAPI_JSON_PATH="openapi.json",
        OPENAPI_SWAGGER_UI_PATH="/docs" if os.getenv("ENABLE_DOCS", "true").lower() == "true" else None,
        OPENAPI_SWAGGER_UI_URL="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/",
        MAX_CONTENT_LENGTH=16384,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SQLALCHEMY_DATABASE_URI"]:
        raise RuntimeError("DATABASE_URL es obligatoria")
    if app.config["SQLALCHEMY_DATABASE_URI"].startswith("mysql"):
        app.config["SQLALCHEMY_ENGINE_OPTIONS"]["isolation_level"] = "READ COMMITTED"
    secret = app.config["JWT_SECRET_KEY"] or ""
    if len(secret) < 64 or len(set(secret)) < 12:
        raise RuntimeError("JWT_SECRET_KEY requiere al menos 64 caracteres aleatorios")
    if urlparse(app.config["GHIBLI_BASE_URL"]).scheme != "https":
        raise RuntimeError("GHIBLI_BASE_URL debe usar HTTPS")
    # Solo activar cuando el proxy sea el único origen de tráfico a Gunicorn.
    if os.getenv("TRUST_PROXY", "false").lower() == "true":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app.extensions["redis"] = redis.Redis.from_url(
        app.config["REDIS_URL"], socket_connect_timeout=2, socket_timeout=2, decode_responses=True
    )
    app.extensions["ghibli_http"] = build_session()
    app.config["DUMMY_PASSWORD_HASH"] = generate_password_hash(uuid.uuid4().hex)
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    register_jwt(jwt)
    limiter.init_app(app)
    api = Api(app)
    api.spec.components.security_scheme(
        "bearerAuth", {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
    )
    from .routes import auth, users, ghibli, health

    for blueprint in (auth, users, ghibli, health):
        api.register_blueprint(blueprint)

    @app.before_request
    def start_request():
        g.request_id = str(uuid.uuid4())
        g.started = time.monotonic()

    @app.after_request
    def finish_request(response):
        response.headers["X-Request-ID"] = getattr(g, "request_id", "unknown")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        app.logger.info(
            "request id=%s method=%s path=%s status=%s duration_ms=%.1f",
            getattr(g, "request_id", "unknown"),
            request.method,
            request.path,
            response.status_code,
            (time.monotonic() - getattr(g, "started", time.monotonic())) * 1000,
        )
        return response

    @app.errorhandler(HTTPException)
    def http_error(exc):
        db.session.rollback()
        data = getattr(exc, "data", {}) or {}
        body = {
            "code": exc.code,
            "message": data.get("message", exc.description),
            "request_id": getattr(g, "request_id", None),
        }
        if "messages" in data:
            body["errors"] = data["messages"]
        response = exc.get_response()
        response.data = app.json.dumps(body)
        response.content_type = "application/json"
        return response

    @app.errorhandler(IntegrityError)
    def conflict(exc):
        db.session.rollback()
        return {"code": 409, "message": "Conflicto de datos; el correo debe ser único."}, 409

    @app.errorhandler(SQLAlchemyError)
    @app.errorhandler(redis.RedisError)
    def unavailable(exc):
        db.session.rollback()
        app.logger.error("dependency_unavailable type=%s", type(exc).__name__)
        return {"code": 503, "message": "Dependencia temporalmente no disponible."}, 503

    @app.errorhandler(Exception)
    def unexpected(exc):
        db.session.rollback()
        app.logger.error(
            "unhandled_error type=%s request_id=%s", type(exc).__name__, getattr(g, "request_id", None)
        )
        return {"code": 500, "message": "Error interno.", "request_id": getattr(g, "request_id", None)}, 500

    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--name", prompt=True)
    @click.password_option(confirmation_prompt=True)
    def create_admin(email, name, password):
        """Crear un admin sin contraseña predeterminada (acceso al host requerido)."""
        from .schemas import CreateUserSchema
        from .services import create_user

        try:
            data = CreateUserSchema().load(dict(email=email, name=name, password=password, role="admin"))
            create_user(data)
        except Exception as exc:
            db.session.rollback()
            raise click.ClickException(
                "No se creó el administrador; valide datos, correo único y migraciones."
            ) from exc
        click.echo("Administrador creado.")

    return app
