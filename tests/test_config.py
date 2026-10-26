import secrets
import pytest
from app import create_app


def test_config_required():
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app({"SQLALCHEMY_DATABASE_URI": None})
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        create_app({"SQLALCHEMY_DATABASE_URI": "sqlite://", "JWT_SECRET_KEY": "short"})
    with pytest.raises(RuntimeError, match="HTTPS"):
        create_app(
            {
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
                "JWT_SECRET_KEY": secrets.token_hex(48),
                "GHIBLI_BASE_URL": "http://example.com",
            }
        )
