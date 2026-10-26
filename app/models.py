from datetime import datetime, timezone
from .extensions import db

ROLES = ("admin", "films", "people", "locations", "species", "vehicles")

# Modelo SQL ALchemy para security
class SecurityLock(db.Model):
    __tablename__ = "security_lock"
    id = db.Column(db.Integer, primary_key=True)

# Modelo SQL ALchemy para User
class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(254), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    token_version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    __table_args__ = (
        db.CheckConstraint(
            "role IN ('admin','films','people','locations','species','vehicles')", name="ck_users_role"
        ),
    )
