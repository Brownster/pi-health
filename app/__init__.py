from __future__ import annotations

from pathlib import Path
from typing import Mapping, MutableMapping

from flask import Flask, send_from_directory

from .config import Config
from .logging import init_logging
from .routes.compose_editor import compose_editor
from .routes.containers import containers_api
from .routes.ops_copilot import build_agent, ops_copilot_api
from .routes.system import system_api


def _resolve_static_folder() -> str:
    base_dir = Path(__file__).resolve().parent.parent
    return str(base_dir / "static")


def create_app(config_object: object | Mapping[str, object] | None = None) -> Flask:
    app = Flask(__name__, static_folder=_resolve_static_folder())

    init_logging(app)

    app.config.from_object(Config)
    if config_object:
        if isinstance(config_object, Mapping):
            app.config.from_mapping(config_object)
        else:
            app.config.from_object(config_object)

    _initialise_extensions(app)
    _register_blueprints(app)
    _register_static_routes(app)

    return app


def _initialise_extensions(app: Flask) -> None:
    config: MutableMapping[str, object] = app.config
    agent = build_agent(config)
    app.extensions.setdefault('ops_copilot_agent', agent)


def _register_blueprints(app: Flask) -> None:
    app.register_blueprint(system_api)
    app.register_blueprint(containers_api)
    app.register_blueprint(ops_copilot_api)
    app.register_blueprint(compose_editor)


def _register_static_routes(app: Flask) -> None:
    @app.route('/')
    def serve_frontend():
        return send_from_directory(app.static_folder, 'index.html')

    @app.route('/system.html')
    def serve_system():
        return send_from_directory(app.static_folder, 'system.html')

    @app.route('/containers.html')
    def serve_containers():
        return send_from_directory(app.static_folder, 'containers.html')

    @app.route('/ops-copilot.html')
    def serve_ops_copilot():
        return send_from_directory(app.static_folder, 'ops-copilot.html')

    @app.route('/edit.html')
    def serve_edit():
        return send_from_directory(app.static_folder, 'edit.html')

    @app.route('/login.html')
    def serve_login():
        return send_from_directory(app.static_folder, 'login.html')

    @app.route('/coraline-banner.jpg')
    def serve_banner():
        return send_from_directory(app.static_folder, 'coraline-banner.jpg')
