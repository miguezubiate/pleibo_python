from marshmallow import Schema, fields, validate, pre_load, validates_schema, ValidationError
from .models import ROLES


class Normalized(Schema):
    @pre_load
    def normalize(self, data, **kwargs):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        for key in ("email", "name"):
            if isinstance(data.get(key), str):
                data[key] = data[key].strip()
        if isinstance(data.get("email"), str):
            data["email"] = data["email"].lower()
        return data


class LoginSchema(Normalized):
    email = fields.Email(required=True, validate=validate.Length(max=254))
    password = fields.String(required=True, load_only=True, validate=validate.Length(min=1, max=128))


class CreateUserSchema(Normalized):
    name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    email = fields.Email(required=True, validate=validate.Length(max=254))
    password = fields.String(required=True, load_only=True, validate=validate.Length(min=12, max=128))
    role = fields.String(required=True, validate=validate.OneOf(ROLES))


class UpdateUserSchema(CreateUserSchema):
    name = fields.String(validate=validate.Length(min=1, max=100))
    email = fields.Email(validate=validate.Length(max=254))
    password = fields.String(load_only=True, validate=validate.Length(min=12, max=128))
    role = fields.String(validate=validate.OneOf(ROLES))

    @validates_schema
    def nonempty(self, data, **kwargs):
        if not data:
            raise ValidationError("Envíe al menos un campo.")


class UserSchema(Schema):
    id = fields.Integer()
    name = fields.String()
    email = fields.Email()
    role = fields.String()
    created_at = fields.DateTime()


class PageQuery(Schema):
    page = fields.Integer(load_default=1, validate=validate.Range(min=1))
    per_page = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))


class PageSchema(Schema):
    items = fields.List(fields.Nested(UserSchema))
    page = fields.Integer()
    per_page = fields.Integer()
    total = fields.Integer()
    pages = fields.Integer()


class BulkDeleteSchema(Schema):
    ids = fields.List(
        fields.Integer(strict=True, validate=validate.Range(min=1)),
        required=True,
        validate=validate.Length(min=1, max=100),
    )


class TokenSchema(Schema):
    access_token = fields.String()
    token_type = fields.String()
    expires_in = fields.Integer()


class GhibliQuery(Schema):
    limit = fields.Integer(load_default=50, validate=validate.Range(min=1, max=250))
