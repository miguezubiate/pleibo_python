from alembic import context
from flask import current_app

config = context.config
db = current_app.extensions["migrate"].db
target_metadata = db.metadata
if context.is_offline_mode():
    context.configure(url=db.engine.url.render_as_string(hide_password=False), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with db.engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
