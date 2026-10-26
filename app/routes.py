import time
from flask import current_app, g
from flask.views import MethodView
from flask_jwt_extended import create_access_token, get_jwt
from flask_smorest import Blueprint, abort
from sqlalchemy import select, text
from werkzeug.security import check_password_hash
from .extensions import db, limiter
from .models import User
from .security import require_user
from .schemas import (
    LoginSchema,
    CreateUserSchema,
    UpdateUserSchema,
    UserSchema,
    PageQuery,
    PageSchema,
    BulkDeleteSchema,
    TokenSchema,
    GhibliQuery,
)
from . import services
from .ghibli import RESOURCES, fetch_resource

auth = Blueprint("auth", __name__, url_prefix="/api/v1/auth", description="Autenticación JWT")
users = Blueprint("users", __name__, url_prefix="/api/v1/users", description="Administración de usuarios")
ghibli = Blueprint("ghibli", __name__, url_prefix="/api/v1/ghibli", description="Ghibli según rol")
health = Blueprint("health", __name__, description="Estado operativo")
SECURITY = [{"bearerAuth": []}]


@auth.route("/login", methods=["POST"])
@limiter.limit("5 per minute")
@auth.arguments(LoginSchema)
@auth.response(200, TokenSchema)
def login(data):
    user = db.session.scalar(select(User).where(User.email == data["email"]))
    password_hash = user.password_hash if user else current_app.config["DUMMY_PASSWORD_HASH"]
    valid = check_password_hash(password_hash, data["password"])
    if not user or not valid:
        abort(401, message="Credenciales inválidas.")
    return {
        "access_token": create_access_token(
            identity=str(user.id), additional_claims={"ver": user.token_version}
        ),
        "token_type": "Bearer",
        "expires_in": 900,
    }


@auth.route("/logout", methods=["POST"])
@auth.doc(security=SECURITY)
@require_user()
@auth.response(204)
def logout():
    token = get_jwt()
    current_app.extensions["redis"].setex(
        "revoked:" + token["jti"], max(1, int(token["exp"] - time.time())), "1"
    )


@users.route("/me", methods=["GET"])
@users.doc(security=SECURITY)
@require_user()
@users.response(200, UserSchema)
def me():
    return g.user


@users.route("")
class UsersView(MethodView):
    @users.doc(security=SECURITY)
    @require_user("admin")
    @users.arguments(PageQuery, location="query")
    @users.response(200, PageSchema)
    def get(self, query):
        page = db.paginate(select(User).order_by(User.id), **query, error_out=False)
        return {
            "items": page.items,
            "page": page.page,
            "per_page": page.per_page,
            "total": page.total,
            "pages": page.pages,
        }

    @users.doc(security=SECURITY)
    @require_user("admin")
    @users.arguments(CreateUserSchema)
    @users.response(201, UserSchema)
    def post(self, data):
        return services.create_user(data)


@users.route("/<int:user_id>")
class UserView(MethodView):
    @users.doc(security=SECURITY)
    @require_user("admin")
    @users.response(200, UserSchema)
    def get(self, user_id):
        return services.get_user(user_id)

    @users.doc(security=SECURITY)
    @require_user("admin")
    @users.arguments(UpdateUserSchema)
    @users.response(200, UserSchema)
    def patch(self, data, user_id):
        return services.update_user(user_id, data)

    @users.doc(security=SECURITY)
    @require_user("admin")
    @users.response(204)
    def delete(self, user_id):
        services.delete_users([user_id])


@users.route("/bulk-delete", methods=["POST"])
@users.doc(
    security=SECURITY, description="Borrado atómico de 1 a 100 IDs. Si falta alguno, no se borra ninguno."
)
@require_user("admin")
@users.arguments(BulkDeleteSchema)
@users.response(204)
def bulk_delete(data):
    services.delete_users(data["ids"])


def authorize_resource(resource):
    if resource not in RESOURCES:
        abort(404, message="Recurso desconocido.")
    if g.user.role not in ("admin", resource):
        abort(403, message="Su rol no permite consultar este recurso.")


@ghibli.route("/<string:resource>", methods=["GET"])
@ghibli.doc(security=SECURITY, responses={200: {"description": "Lista JSON del proveedor"}})
@require_user()
@ghibli.arguments(GhibliQuery, location="query")
def resource_list(query, resource):
    authorize_resource(resource)
    return fetch_resource(resource, limit=query["limit"])


@ghibli.route("/<string:resource>/<uuid:item_id>", methods=["GET"])
@ghibli.doc(security=SECURITY, responses={200: {"description": "Objeto JSON del proveedor"}})
@require_user()
def resource_detail(resource, item_id):
    authorize_resource(resource)
    return fetch_resource(resource, item_id=str(item_id))


@health.route("/health/live", methods=["GET"])
@limiter.exempt
def live():
    return {"status": "ok"}


@health.route("/health/ready", methods=["GET"])
@limiter.exempt
def ready():
    db.session.execute(text("SELECT 1 FROM security_lock WHERE id = 1")).scalar_one()
    current_app.extensions["redis"].ping()
    return {"status": "ready"}
