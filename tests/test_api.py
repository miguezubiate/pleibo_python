from datetime import timedelta
from unittest.mock import Mock
import pytest
import requests
from flask_jwt_extended import create_access_token
from app.extensions import db
from app.models import User
from app.ghibli import build_session
from conftest import PASSWORD

U = "/api/v1/users"


def test_crud_pagination_and_no_password(client, admin):
    payload = {"name": "  Ana  ", "email": "  ANA@example.com ", "role": "films", "password": PASSWORD}
    response = client.post(U, json=payload, headers=admin)
    assert response.status_code == 201
    user = response.json
    assert user["name"] == "Ana" and user["email"] == "ana@example.com"
    assert "password" not in user and "password_hash" not in user
    uid = user["id"]
    assert client.get(f"{U}/{uid}", headers=admin).json == user
    page = client.get(U + "?per_page=1&page=2", headers=admin)
    assert page.json["total"] == 2 and len(page.json["items"]) == 1
    assert client.patch(f"{U}/{uid}", headers=admin, json={"name": "Ana Maria"}).json["name"] == "Ana Maria"
    assert client.delete(f"{U}/{uid}", headers=admin).status_code == 204
    assert client.get(f"{U}/{uid}", headers=admin).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"role": "root"},
        {"password": "short"},
        {"email": "bad"},
        {"name": " "},
        {"id": 99},
        {"token_version": 99},
        {"name": None},
    ],
)
def test_invalid_create(client, admin, payload):
    base = {"name": "Ana", "email": "ana@example.com", "role": "films", "password": PASSWORD}
    if payload:
        base.update(payload)
    else:
        base = {}
    assert client.post(U, json=base, headers=admin).status_code == 422


def test_duplicate_email_atomic(client, admin, create):
    uid, _ = create()
    assert (
        client.patch(
            f"{U}/{uid}", json={"email": "ADMIN@example.com", "name": "Wrong"}, headers=admin
        ).status_code
        == 409
    )
    assert client.get(f"{U}/{uid}", headers=admin).json["name"] == "User"


def test_bulk_delete_atomic(client, admin, create):
    uid, _ = create()
    assert client.post(U + "/bulk-delete", headers=admin, json={"ids": [uid, 999999]}).status_code == 404
    assert client.get(f"{U}/{uid}", headers=admin).status_code == 200
    assert client.post(U + "/bulk-delete", headers=admin, json={"ids": [uid, uid]}).status_code == 204


@pytest.mark.parametrize("ids", [[], [0], [True], ["1"], list(range(1, 102))])
def test_invalid_bulk(client, admin, ids):
    assert client.post(U + "/bulk-delete", headers=admin, json={"ids": ids}).status_code == 422


def test_last_admin_protected(client, admin):
    assert client.delete(U + "/1", headers=admin).status_code == 409
    assert client.patch(U + "/1", json={"role": "films"}, headers=admin).status_code == 409
    assert client.get(U + "/me", headers=admin).json["role"] == "admin"


def test_can_replace_admin(client, admin, create):
    uid, second = create("admin")
    assert client.delete(U + "/1", headers=second).status_code == 204
    assert client.get(U, headers=admin).status_code == 401
    assert client.get(U, headers=second).status_code == 200


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", U),
        ("get", U + "/1"),
        ("post", U),
        ("patch", U + "/1"),
        ("delete", U + "/1"),
        ("post", U + "/bulk-delete"),
    ],
)
def test_nonadmin_forbidden(client, create, method, path):
    _, token = create()
    assert getattr(client, method)(path, headers=token).status_code == 403


def test_auth_rejections(client, admin, app):
    assert client.get(U).status_code == 401
    assert client.get(U, headers={"Authorization": "Bearer bad"}).status_code == 401
    for email in ["missing@example.com", "admin@example.com"]:
        assert client.post("/api/v1/auth/login", json={"email": email, "password": "bad"}).status_code == 401
    with app.app_context():
        expired = create_access_token(
            identity="1", additional_claims={"ver": 1}, expires_delta=timedelta(seconds=-2)
        )
    assert client.get(U, headers={"Authorization": "Bearer " + expired}).status_code == 401
    assert client.post("/api/v1/auth/logout", headers=admin).status_code == 204
    assert client.get(U, headers=admin).status_code == 401


def test_role_and_password_revoke_token(client, admin, create):
    uid, token = create()
    assert client.patch(f"{U}/{uid}", json={"role": "people"}, headers=admin).status_code == 200
    assert client.get(U + "/me", headers=token).status_code == 401
    login = client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": PASSWORD})
    token = {"Authorization": "Bearer " + login.json["access_token"]}
    assert (
        client.patch(f"{U}/{uid}", json={"password": "New-Password-98765"}, headers=admin).status_code == 200
    )
    assert client.get(U + "/me", headers=token).status_code == 401


@pytest.mark.parametrize("role", ["admin", "films", "people", "locations", "species", "vehicles"])
def test_full_role_matrix(client, create, app, role):
    _, token = create(role)
    mock = Mock()
    mock.get.return_value.status_code = 200
    mock.get.return_value.json.return_value = [{"id": "sample"}]
    app.extensions["ghibli_http"] = mock
    for resource in ("films", "people", "locations", "species", "vehicles"):
        response = client.get("/api/v1/ghibli/" + resource, headers=token)
        assert response.status_code == (200 if role in ("admin", resource) else 403)
    assert client.get("/api/v1/ghibli/unknown", headers=token).status_code == 404


@pytest.mark.parametrize(
    "failure,status", [(requests.Timeout(), 504), (requests.ConnectionError(), 502), (ValueError(), 502)]
)
def test_upstream_failures(client, admin, app, failure, status):
    mock = Mock()
    mock.get.side_effect = failure
    app.extensions["ghibli_http"] = mock
    assert client.get("/api/v1/ghibli/films", headers=admin).status_code == status


@pytest.mark.parametrize("upstream,status", [(404, 404), (500, 502), (302, 502)])
def test_upstream_status(client, admin, app, upstream, status):
    mock = Mock()
    mock.get.return_value.status_code = upstream
    app.extensions["ghibli_http"] = mock
    assert client.get("/api/v1/ghibli/films", headers=admin).status_code == status


def test_cache_and_detail(client, admin, app):
    mock = Mock()
    mock.get.return_value.status_code = 200
    mock.get.return_value.json.return_value = [{"title": "Totoro"}]
    app.extensions["ghibli_http"] = mock
    for _ in range(2):
        assert client.get("/api/v1/ghibli/films", headers=admin).json == [{"title": "Totoro"}]
    assert mock.get.call_count == 1
    mock.get.return_value.json.return_value = {"title": "Totoro"}
    assert (
        client.get("/api/v1/ghibli/films/2baf70d1-42bb-4437-b551-e5fed5a87abe", headers=admin).status_code
        == 200
    )
    assert client.get("/api/v1/ghibli/films/not-a-uuid", headers=admin).status_code == 404
    assert client.get("/api/v1/ghibli/films?limit=99999", headers=admin).status_code == 422


def test_invalid_upstream_shape(client, admin, app):
    mock = Mock()
    mock.get.return_value.status_code = 200
    mock.get.return_value.json.return_value = "not-json-object"
    app.extensions["ghibli_http"] = mock
    assert client.get("/api/v1/ghibli/films", headers=admin).status_code == 502


def test_health_docs_validation(client, admin):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert client.get("/docs").status_code == 200
    spec = client.get("/openapi.json").json
    assert "bearerAuth" in spec["components"]["securitySchemes"]
    assert "/api/v1/users" in spec["paths"]
    assert client.get(U + "?per_page=101", headers=admin).status_code == 422
    assert client.patch(U + "/1", json={}, headers=admin).status_code == 422
    assert client.post(U, data="x" * 20000, content_type="application/json", headers=admin).status_code == 413
    assert client.get("/unknown").json["code"] == 404
    assert client.get("/health/live").headers["X-Content-Type-Options"] == "nosniff"


def test_redis_down_fails_closed(client, admin, app):
    import redis

    broken = Mock()
    broken.exists.side_effect = redis.ConnectionError()
    broken.ping.side_effect = redis.ConnectionError()
    app.extensions["redis"] = broken
    assert client.get(U, headers=admin).status_code == 503
    assert client.get("/health/ready").status_code == 503


def test_cli_admin(app):
    runner = app.test_cli_runner()
    args = ["create-admin", "--email", "cli@example.com", "--name", "CLI", "--password", PASSWORD]
    assert runner.invoke(args=args).exit_code == 0
    assert runner.invoke(args=args).exit_code != 0
    with app.app_context():
        user = db.session.query(User).filter_by(email="cli@example.com").one()
        assert user.role == "admin" and user.password_hash != PASSWORD


def test_http_retry_configuration():
    session = build_session()
    retry = session.get_adapter("https://").max_retries
    assert retry.total == 1 and retry.allowed_methods == ["GET"]


def test_rate_limit_real_redis():
    import os
    import secrets
    from app import create_app

    url = os.getenv("TEST_REDIS_URL")
    if not url:
        pytest.skip("Redis real disponible en CI")
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "JWT_SECRET_KEY": secrets.token_hex(48),
            "REDIS_URL": url,
            "RATELIMIT_STORAGE_URI": url,
            "RATELIMIT_KEY_PREFIX": secrets.token_hex(8),
        }
    )
    client = app.test_client()
    # Requests inválidos también consumen la cuota del endpoint de login.
    statuses = [client.post("/api/v1/auth/login", json={}).status_code for _ in range(6)]
    assert statuses == [422] * 5 + [429]


def test_concurrent_last_admin_mysql(app, client, admin, create):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    if not app.config["SQLALCHEMY_DATABASE_URI"].startswith("mysql"):
        pytest.skip("Requiere bloqueos InnoDB: disponible en CI MySQL")
    uid, second = create("admin")
    barrier = Barrier(2)

    def delete_self(user_id, token):
        with app.test_client() as concurrent_client:
            barrier.wait(timeout=5)
            return concurrent_client.delete(f"{U}/{user_id}", headers=token).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        one = executor.submit(delete_self, 1, admin)
        two = executor.submit(delete_self, uid, second)
        statuses = [one.result(timeout=15), two.result(timeout=15)]
    assert sorted(statuses) == [204, 409]
    with app.app_context():
        assert db.session.query(User).filter_by(role="admin").count() == 1
