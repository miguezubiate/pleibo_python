import json
from flask import current_app
from flask_smorest import abort
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

RESOURCES = {"films", "people", "locations", "species", "vehicles"}


def build_session():
    session = requests.Session()
    retry = Retry(
        total=1,
        backoff_factor=0.2,
        status_forcelist=[502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10))
    return session


def fetch_resource(resource, item_id=None, limit=50):
    suffix = f"/{item_id}" if item_id else ""
    key = f"ghibli:{resource}:{item_id or 'list'}:{limit}"
    redis = current_app.extensions["redis"]
    cached = redis.get(key)
    if cached:
        return json.loads(cached)
    try:
        response = current_app.extensions["ghibli_http"].get(
            current_app.config["GHIBLI_BASE_URL"] + "/" + resource + suffix,
            params={"limit": limit} if not item_id else None,
            timeout=(2, 4),
            allow_redirects=False,
        )
        if response.status_code == 404:
            abort(404, message="Recurso Ghibli no encontrado.")
        if response.status_code != 200:
            abort(502, message="El proveedor Ghibli no está disponible.")
        data = response.json()
        if not isinstance(data, dict if item_id else list):
            abort(502, message="Respuesta inválida del proveedor.")
    except requests.Timeout:
        abort(504, message="Tiempo de espera agotado con Ghibli.")
    except (requests.RequestException, ValueError):
        abort(502, message="No fue posible consultar Ghibli.")
    redis.setex(key, 60, json.dumps(data))
    return data
