from flask import Flask, jsonify, render_template
from flask_caching import Cache
from supabase import create_client
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import pytz
import os

from dotenv import load_dotenv
load_dotenv()

IST = pytz.timezone("Asia/Kolkata")

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True

cache = Cache(config={
    "CACHE_TYPE": "RedisCache",
    "CACHE_REDIS_URL": os.getenv("REDIS_URL"),
    "CACHE_DEFAULT_TIMEOUT": 300
})
cache.init_app(app)


def get_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("Supabase environment variables not set")
    return create_client(url, key)


HEALTH_ADVISORY = [
    (0,   50,  "Good",        "#10b981", "Air quality is satisfactory. Enjoy outdoor activities."),
    (51,  100, "Satisfactory","#84cc16", "Acceptable quality. Sensitive individuals should limit prolonged outdoor exertion."),
    (101, 200, "Moderate",    "#f59e0b", "Sensitive groups may experience health effects."),
    (201, 300, "Poor",        "#f97316", "Everyone may begin to experience health effects. Avoid outdoor exertion."),
    (301, 400, "Very Poor",   "#ef4444", "Health alert: serious effects possible. Avoid prolonged outdoor activity."),
    (401, 500, "Severe",      "#7c3aed", "Health emergency. Remain indoors and keep windows closed."),
]

def get_advisory(aqi: int) -> dict:
    for lo, hi, category, color, message in HEALTH_ADVISORY:
        if lo <= aqi <= hi:
            return {"category": category, "color": color, "message": message, "aqi": aqi}
    return {"category": "Unknown", "color": "#64748b", "message": "AQI out of measurable range.", "aqi": aqi}


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/current")
@cache.cached(timeout=300)
def current():
    supabase = get_supabase()
    res = (
        supabase.table("aqi_history")
        .select("*")
        .order("timestamp_utc", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        return jsonify({"error": "No data found"}), 404
    return jsonify(res.data[0])


@app.route("/api/history")
@cache.cached(timeout=300)
def history():
    supabase = get_supabase()
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    res = (
        supabase.table("aqi_history")
        .select("timestamp_utc,pm2_5,pm10,current_aqi,predicted_aqi_3h")
        .gte("timestamp_utc", since)
        .order("timestamp_utc")
        .execute()
    )
    return jsonify(res.data)


@app.route("/api/weather")
@cache.cached(timeout=300)
def weather():
    supabase = get_supabase()
    res = (
        supabase.table("aqi_history_all_features")
        .select("timestamp_utc,temperature,humidity,ws_ms,wd_deg")
        .order("timestamp_utc", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        return jsonify({"error": "No weather data found"}), 404
    return jsonify(res.data[0])


@app.route("/api/model-scorecard")
@cache.cached(timeout=300)
def model_scorecard():
    supabase = get_supabase()
    res = (
        supabase.table("aqi_history_all_features")
        .select("current_aqi,predicted_aqi_3h")
        .execute()
    )
    if not res.data:
        return jsonify({"error": "No data available for scoring"}), 404
    valid = [r for r in res.data if r["current_aqi"] is not None and r["predicted_aqi_3h"] is not None]
    if not valid:
        return jsonify({"error": "No valid rows for MAE calculation"}), 404
    mae = sum(abs(r["current_aqi"] - r["predicted_aqi_3h"]) for r in valid) / len(valid)
    return jsonify({"mae": round(mae, 2), "sample_size": len(valid)})


@app.route("/api/daily-summary")
@cache.cached(timeout=300)
def daily_summary():
    supabase = get_supabase()
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    res = (
        supabase.table("aqi_history")
        .select("timestamp_utc,current_aqi")
        .gte("timestamp_utc", since)
        .order("timestamp_utc")
        .execute()
    )
    if not res.data:
        return jsonify([])
    daily = defaultdict(list)
    for row in res.data:
        if row["current_aqi"] is None:
            continue
        date = row["timestamp_utc"][:10]
        daily[date].append(row["current_aqi"])
    summary = [
        {
            "date": date,
            "min_aqi": round(min(values)),
            "max_aqi": round(max(values)),
            "avg_aqi": round(sum(values) / len(values), 1),
        }
        for date, values in sorted(daily.items())
    ]
    return jsonify(summary)


@app.route("/api/worst-hours")
@cache.cached(timeout=300)
def worst_hours():
    supabase = get_supabase()
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    res = (
        supabase.table("aqi_history_all_features")
        .select("hour_of_day,current_aqi")
        .gte("timestamp_utc", since)
        .execute()
    )
    if not res.data:
        return jsonify([])
    hourly = defaultdict(list)
    for row in res.data:
        if row["current_aqi"] is None or row["hour_of_day"] is None:
            continue
        hourly[row["hour_of_day"]].append(row["current_aqi"])
    result = [
        {
            "hour": hour,
            "avg_aqi": round(sum(values) / len(values), 1),
            "reading_count": len(values),
        }
        for hour, values in sorted(hourly.items())
    ]
    return jsonify(result)


@app.route("/api/data-freshness")
@cache.cached(timeout=60)
def data_freshness():
    supabase = get_supabase()
    res = (
        supabase.table("aqi_history")
        .select("timestamp_utc")
        .order("timestamp_utc", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        return jsonify({"error": "No records found"}), 404
    latest_str = res.data[0]["timestamp_utc"]
    try:
        latest = datetime.fromisoformat(latest_str)
    except ValueError:
        latest = datetime.strptime(latest_str, "%Y-%m-%dT%H:%M:%S")
    if latest.tzinfo is None:
        latest = IST.localize(latest)
    age_minutes = (datetime.now(timezone.utc) - latest).total_seconds() / 60
    return jsonify({
        "latest_timestamp": latest_str,
        "age_minutes": round(age_minutes, 1),
        "is_stale": age_minutes > 90,
    })


@app.route("/api/trend")
@cache.cached(timeout=300)
def trend():
    supabase = get_supabase()
    res = (
        supabase.table("aqi_history")
        .select("timestamp_utc,current_aqi")
        .order("timestamp_utc", desc=True)
        .limit(3)
        .execute()
    )
    rows = [r for r in res.data if r["current_aqi"] is not None]
    if len(rows) < 3:
        return jsonify({"trend": "unknown", "reason": "Not enough data points"})
    values = [r["current_aqi"] for r in reversed(rows)]
    slope = values[2] - values[0]
    direction = "up" if slope > 10 else ("down" if slope < -10 else "stable")
    return jsonify({"trend": direction, "values": values, "slope": round(slope, 1)})


@app.route("/api/health-advisory")
@cache.cached(timeout=300)
def health_advisory():
    supabase = get_supabase()
    res = (
        supabase.table("aqi_history")
        .select("current_aqi")
        .order("timestamp_utc", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data or res.data[0]["current_aqi"] is None:
        return jsonify({"error": "No AQI data available"}), 404
    return jsonify(get_advisory(res.data[0]["current_aqi"]))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
