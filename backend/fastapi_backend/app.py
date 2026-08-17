from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from supabase import create_client
from datetime import datetime, timedelta, timezone
import pytz
import os
from models.model import AQI_Model,AQI_Weather
from contextlib import asynccontextmanager
import redis.asyncio as redis
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from fastapi_cache.decorator import cache

from dotenv import load_dotenv
load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_client = redis.from_url(
        os.getenv("REDIS_URL"),
        decode_responses=False,
    )

    FastAPICache.init(
        RedisBackend(redis_client),
        prefix="aqi-fastapi-cache",
    )

    yield

    await redis_client.aclose()


app = FastAPI(lifespan=lifespan)

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
templates = Jinja2Templates(directory=str(FRONTEND_DIR / "templates"))

app.mount(
    "/static",
    StaticFiles(directory=str(FRONTEND_DIR / "static")),
    name="static",
)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={},
    )


@app.get("/manifest.json")
def manifest():
    return FileResponse(FRONTEND_DIR / "static" / "manifest.json")

IST=pytz.timezone("Asia/Kolkata")

@app.get("/health")
def get_health():
    return {"status": "ok"}

supabase=create_client(os.getenv("SUPABASE_URL"),os.getenv("SUPABASE_SERVICE_ROLE_KEY"))

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

@app.get("/api/current",response_model=AQI_Model)
@cache(expire=300)
def current():
    res=(
        supabase.table("aqi_history")
        .select("*")
        .order("timestamp_utc", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="No data found")
    return res.data[0]

@app.get("/api/history",response_model=list[AQI_Model])
@cache(expire=300)
def history():
    since=(datetime.now(timezone.utc)-timedelta(hours=24)).isoformat()
    res = (
        supabase.table("aqi_history")
        .select("timestamp_utc,pm2_5,pm10,current_aqi,predicted_aqi_3h")
        .gte("timestamp_utc", since)
        .order("timestamp_utc")
        .execute()
    )
    return res.data

@app.get("/api/weather",response_model=AQI_Weather)
@cache(expire=300)
def weather():
    res = (
        supabase.table("aqi_history_all_features")
        .select("timestamp_utc,temperature,humidity,ws_ms,wd_deg")
        .order("timestamp_utc", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="No weather data found")
    return res.data[0]

@app.get("/api/model-scorecard")
@cache(expire=300)
def model_scorecard():
    res = supabase.rpc("get_model_scorecard").execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="No scorecard data found")
    return res.data[0]

@app.get("/api/daily-summary")
@cache(expire=300)
def daily_summary():
    res = supabase.rpc("get_daily_summary").execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="No daily summary data found")
    return res.data


@app.get("/api/worst-hours")
@cache(expire=300)
def worst_hours():
    res = supabase.rpc("get_worst_hours").execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="No worst hours data found")
    return res.data

@app.get("/api/data-freshness")
@cache(expire=60)
def data_freshness():
    res = (
        supabase.table("aqi_history")
        .select("timestamp_utc")
        .order("timestamp_utc", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="No data found")
    latest_str = res.data[0]["timestamp_utc"]
    try:
        latest = datetime.fromisoformat(
            latest_str.replace("Z", "+00:00")
        )
    except ValueError:
        latest = datetime.strptime(
            latest_str, "%Y-%m-%dT%H:%M:%S"
        )
    if latest.tzinfo is None:
        latest = IST.localize(latest)

    latest = latest.astimezone(timezone.utc)
    now_utc = datetime.now(timezone.utc)
    age_minutes = (
        now_utc - latest
    ).total_seconds() / 60

    return {
        "latest_timestamp": latest_str,
        "age_minutes": round(age_minutes, 1),
        "is_stale": age_minutes > 90,
    }

@app.get("/api/trend")
@cache(expire=300)
def trend():
    res = (
        supabase.table("aqi_history")
        .select("timestamp_utc,current_aqi")
        .order("timestamp_utc", desc=True)
        .limit(3)
        .execute()
    )
    rows = [r for r in res.data if r["current_aqi"] is not None]
    if len(rows) < 3:
        raise HTTPException(status_code=404, detail="Not enough data points")
    values = [r["current_aqi"] for r in reversed(rows)]
    slope = values[2] - values[0]
    direction = "up" if slope > 10 else ("down" if slope < -10 else "stable")
    return {"trend": direction, "values": values, "slope": round(slope, 1)}

@app.get("/api/health-advisory")
@cache(expire=300)
def health_advisory():
    res = (
        supabase.table("aqi_history")
        .select("current_aqi")
        .order("timestamp_utc", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data or res.data[0]["current_aqi"] is None:
        raise HTTPException(status_code=404, detail="No AQI data available")
    return get_advisory(res.data[0]["current_aqi"])
