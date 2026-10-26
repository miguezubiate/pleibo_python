import os
import secrets
import pytest
import fakeredis
from flask_migrate import upgrade
from werkzeug.security import generate_password_hash
from app import create_app
from app.extensions import db
from app.models import User

PASSWORD = "Correct-Horse-Battery-2026"


@pytest.fixture
def app(tmp_path):
    uri = os.getenv("TEST_DATABASE_URL", "sqlite:///" + str(tmp_path / "test.db"))
    application = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": uri,
            "JWT_SECRET_KEY": secrets.token_hex(48),
            "RATELIMIT_ENABLED": False,
            "RATELIMIT_STORAGE_URI": "memory://",
        }
    )
    application.extensions["redis"] = fakeredis.FakeRedis(decode_responses=True)
    with application.app_context():
        upgrade(directory="migrations")
        db.session.query(User).delete()
        db.session.add(
            User(
                id=1,
                name="Admin",
                email="admin@example.com",
                role="admin",
                password_hash=generate_password_hash(PASSWORD),
                token_version=1,
            )
        )
        db.session.commit()
    yield application
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin(client):
    response = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": PASSWORD})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json["access_token"]}


@pytest.fixture
def create(client, admin):
    def factory(role="films", email="user@example.com"):
        response = client.post(
            "/api/v1/users",
            headers=admin,
            json={"name": "User", "email": email, "role": role, "password": PASSWORD},
        )
        assert response.status_code == 201, response.json
        login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        return response.json["id"], {"Authorization": "Bearer " + login.json["access_token"]}

    return factory
