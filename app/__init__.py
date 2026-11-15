"""Study tools: a small local web app that hosts several learning tools."""
from urllib.parse import urlsplit

from flask import Flask, abort, render_template, request

from app.core import db
from app.core.config import settings
from app.core.registry import discover

LOCAL_HOSTS = {"localhost", "127.0.0.1"}


def create_app(config=None) -> Flask:
    app = Flask(__name__)
    app.config.update(settings())
    if config:
        app.config.update(config)
    app.json.ensure_ascii = False

    tools = discover()
    db.init_db(app.config["DB_PATH"], [tool.schema for tool in tools])
    app.teardown_appcontext(db.close_db)
    for tool in tools:
        app.register_blueprint(tool.blueprint, url_prefix=f"/{tool.slug}")

    @app.before_request
    def local_only():
        """The app is for this machine only: refuse requests that another site could trigger."""
        if urlsplit(f"//{request.host}").hostname not in LOCAL_HOSTS:
            abort(403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("Origin")
            if origin and urlsplit(origin).hostname not in LOCAL_HOSTS:
                abort(403)
            if request.get_data() and not request.is_json:
                abort(415)

    @app.context_processor
    def nav():
        return {"tools": tools}

    @app.get("/")
    def home():
        conn = db.get_db()
        cards = [(tool, tool.status(conn) if tool.status else "") for tool in tools]
        return render_template("home.html", cards=cards)

    return app
