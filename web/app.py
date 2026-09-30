import os
import time

from flask import Flask, request, render_template
from pymongo import MongoClient
from datetime import datetime, UTC
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)

app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1
)

MONGO_HOST = os.getenv("MONGO_HOST", "mongodb")
MONGO_PORT = os.getenv("MONGO_PORT", "27017")

APP_ENV = os.getenv("APP_ENV", "local")
APP_VERSION = os.getenv("APP_VERSION", "v1.2")
HOSTNAME = os.getenv("HOSTNAME", "unknown")

REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "endpoint"]
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["endpoint"]
)

MONGO_ERRORS = Counter("mongodb_errors_total", "Total MongoDB operation errors")

client = MongoClient(
    f"mongodb://{MONGO_HOST}:{MONGO_PORT}/", serverSelectionTimeoutMS=2000
)
db = client["access_logs"]
collection = db["visits"]


@app.route("/")
def index():
    REQUEST_COUNT.labels(method=request.method, endpoint="/").inc()

    with REQUEST_LATENCY.labels(endpoint="/").time():
        ip = request.remote_addr
        collection.insert_one({"ip": ip, "timestamp": datetime.now(UTC)})
        count = collection.count_documents({"ip": ip})

        return render_template(
            "index.html",
            ip=ip,
            count=count,
            app_env=APP_ENV,
            app_version=APP_VERSION,
            hostname=HOSTNAME,
        )


@app.route("/stats")
def stats():
    ip_counts = collection.aggregate(
        [{"$group": {"_id": "$ip", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}]
    )
    return render_template("stats.html", stats=ip_counts)


@app.route("/healthz")
def healthz():
    return {"status": "ok"}, 200


@app.route("/readyz")
def readyz():
    try:
        client.admin.command("ping")
        return {"status": "ready"}, 200
    except Exception:
        MONGO_ERRORS.inc()
        return {"status": "not ready"}, 503


@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@app.route("/work")
def work():
    seconds = float(request.args.get("seconds", "1"))

    # maximum workload = 5 seconds
    seconds = max(0.1, min(seconds, 5.0))

    end_time = time.perf_counter() + seconds
    result = 0

    while time.perf_counter() < end_time:
        result = (result * 3 + 1) % 1000003

    return {"status": "completed", "duration": seconds, "hostname": HOSTNAME}, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
