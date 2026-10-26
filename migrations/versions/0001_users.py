"""Users and serialization lock."""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint(
            "role IN ('admin','films','people','locations','species','vehicles')", name="ck_users_role"
        ),
    )
    op.create_table("security_lock", sa.Column("id", sa.Integer(), primary_key=True))
    op.execute("INSERT INTO security_lock (id) VALUES (1)")


def downgrade():
    op.drop_table("users")
    op.drop_table("security_lock")
