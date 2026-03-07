# import necessary libraries
import requests
import datetime
import redis
import json
import os
from supabase import create_client
from aqi_service import extract_from_redis

# for local development use dotenv to load environment variables
# from dotenv import load_dotenv
# load environment variables
# load_dotenv()

# lat and lon for Mumbai
LAT = 18.9766
LON = 72.8338

# load environment variables
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
REDIS_URL = os.getenv("REDIS_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# create supabase client
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# check for required environment variables
if not OPENWEATHER_API_KEY or not REDIS_URL:
    raise RuntimeError("Missing required environment variables")

REDIS_KEY = "air_quality_history"
MAX_HOURS = 3

# connect to redis
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

# function to fetch data and store in redis
def fetch_and_store():
    dataaqi = requests.get(
        f"http://api.openweathermap.org/data/2.5/air_pollution?lat={LAT}&lon={LON}&appid={OPENWEATHER_API_KEY}",
        timeout=10
    ).json()

    # Weather API
    dataweather = requests.get(
    f"https://api.openweathermap.org/data/2.5/weather?lat={LAT}&lon={LON}&appid={OPENWEATHER_API_KEY}",
        timeout=10
    ).json()


    pm2_5=dataaqi['list'][0]['components']['pm2_5']
    pm10=dataaqi['list'][0]['components']['pm10']

    timestamp=dataaqi['list'][0]['dt']
    timestamp=datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

    temp=dataweather['main']['temp']-273
    humidity=dataweather['main']['humidity']
    windS=dataweather['wind']['speed']
    windD=dataweather['wind']['deg']

    record={
        "pm2_5":pm2_5,
        "pm10":pm10,
        "time":timestamp,
        "temp":round(temp,2),
        "humidity":humidity,
        "windS":windS,
        "windD":windD
    }
    # push new reading
    r.rpush(REDIS_KEY, json.dumps(record))

    # keep only last 3 readings
    r.ltrim(REDIS_KEY, -MAX_HOURS, -1)

def store_for_updating_model(timestamp_utc, ws_ms, wd_deg, month, hour_of_day, temperature, humidity, pm25, pm10, pm25_lag1, pm25_lag2, pm10_lag1, pm10_lag2, pm25_rm3, pm10_rm3, current_aqi, predicted_aqi):
    supabase.table("aqi_history_all_features").insert({
        "timestamp_utc": timestamp_utc,
        "ws_ms": ws_ms,
        "wd_deg": wd_deg,
        "month": month,
        "hour_of_day": hour_of_day,
        "temperature": temperature,
        "humidity": humidity,
        "pm25": pm25,
        "pm10": pm10,
        "pm25_lag1": pm25_lag1,
        "pm25_lag2": pm25_lag2,
        "pm10_lag1": pm10_lag1,
        "pm10_lag2": pm10_lag2,
        "pm25_rm3": pm25_rm3,
        "pm10_rm3": pm10_rm3,
        "current_aqi": current_aqi,
        "predicted_aqi_3h": predicted_aqi
    }).execute()

def store_for_app(timestamp_utc, pm25, pm10, current_aqi, predicted_aqi):
    supabase.table("aqi_history").insert({
        "timestamp_utc": timestamp_utc,
        "pm2_5": pm25,
        "pm10": pm10,
        "current_aqi": current_aqi,
        "predicted_aqi_3h": predicted_aqi
    }).execute()


if __name__ == "__main__":
    fetch_and_store()
    redis_data = extract_from_redis()
    store_for_updating_model(redis_data['datetime'],redis_data['WS (m/s)'],redis_data['WD (deg)'],redis_data['month'],redis_data['hourofday'],redis_data['temp'],redis_data['humidity'],redis_data['PM2_5'],redis_data['PM10'],redis_data['PM2_5(lag1)'],redis_data['PM2_5(lag2)'],redis_data['PM10(lag1)'],redis_data['PM10(lag2)'],redis_data['PM2_5(rolling_mean_3)'],redis_data['PM10(rolling_mean_3)'],redis_data['current_aqi'], redis_data['predicted_aqi'])
    store_for_app(redis_data['datetime'], redis_data['PM2_5'], redis_data['PM10'], redis_data['current_aqi'], redis_data['predicted_aqi'])
