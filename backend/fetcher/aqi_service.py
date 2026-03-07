#import libraries
import redis
import json
from datetime import datetime
import pytz
import pandas as pd
import joblib
import os

# for local development use dotenv to load environment variables
# from dotenv import load_dotenv
#load environment variables
# load_dotenv()

#load model and redis connection
REDIS_URL = os.getenv("REDIS_URL")
r=redis.Redis.from_url(REDIS_URL, decode_responses=True)

# load model
base_dir=os.path.dirname(os.path.abspath(__file__))
model_path=os.path.join(base_dir, '..', 'model', 'xgb_aqi_model_3hr.pkl')
model=joblib.load(model_path)

#function to extract data from redis and make prediction
def extract_from_redis():
    #fetch data from redis
    fetch_d=r.lrange("air_quality_history", 0, -1)
    fetch_d=[json.loads(x) for x in fetch_d]
    df=pd.DataFrame(fetch_d)

    #check if enough data is present
    if len(df)<3:
        return None
    
    #prepare time features
    time=df['time'].iloc[-1]
    dt_utc = datetime.strptime(time, "%Y-%m-%d %H:%M:%S")
    dt_utc = pytz.utc.localize(dt_utc)
    ist = pytz.timezone("Asia/Kolkata")
    dt = dt_utc.astimezone(ist)
    month=dt.month
    hour=dt.hour


    #prepare data for prediction
    data={
        'WS (m/s)':float(df['windS'].iloc[-1]),
        'WD (deg)':float(df['windD'].iloc[-1]),
        'month':month,
        'hourofday':hour,
        'PM2_5':float(df['pm2_5'].iloc[-1]),
        'PM10':float(df['pm10'].iloc[-1]),
        'temp':float(df['temp'].iloc[-1]),
        'humidity':float(df['humidity'].iloc[-1]),
        'PM2_5(lag1)':float(df['pm2_5'].iloc[-2]),
        'PM2_5(lag2)':float(df['pm2_5'].iloc[-3]),
        'PM10(lag1)':float(df['pm10'].iloc[-2]),
        'PM10(lag2)':float(df['pm10'].iloc[-3]),
        'PM2_5(rolling_mean_3)':round(float(df['pm2_5'].iloc[-3:].mean()), 2),
        'PM10(rolling_mean_3)':round(float(df['pm10'].iloc[-3:].mean()), 2)
    }


    #extact dt,pm25,pm10
    datet=dt

    #make prediction
    data=pd.DataFrame([data])
    prediction=model.predict(data)
    prediction=round(prediction[0])

    PM25_BP = [
    (0, 30, 0, 50),
    (30.01, 60, 51, 100),
    (60.01, 90, 101, 200),
    (90.01, 120, 201, 300),
    (120.01, 250, 301, 400),
    (250.01, 500, 401, 500)
    ]

    PM10_BP = [
    (0, 50, 0, 50),
    (50.01, 100, 51, 100),
    (100.01, 250, 101, 200),
    (250.01, 350, 201, 300),
    (350.01, 430, 301, 400),
    (430.01, 600, 401, 500)
    ]

    fetch_d=r.lrange("air_quality_history", -1, -1)
    fetch_d=[json.loads(x) for x in fetch_d]

    if not fetch_d:
        return None

    pm2_5=fetch_d[0]['pm2_5']
    pm10=fetch_d[0]['pm10']

    #function to calculate sub-index
    def calculate_sub_i(concentration, breakpoints):
        if concentration is None:
            return None

        for c_low, c_high, i_low, i_high in breakpoints:
            if c_low <= concentration <= c_high:
                return ((i_high - i_low) / (c_high - c_low)) * (concentration - c_low) + i_low
            
        return None
    
    if pm2_5 is None or pm10 is None:
        return None

    #calculate AQI
    PM25=calculate_sub_i(pm2_5, PM25_BP)
    PM10=calculate_sub_i(pm10, PM10_BP)

    aqi=max(PM25, PM10)

    data={
        'datetime': datet.strftime("%Y-%m-%d %H:%M:%S"),
        'WS (m/s)':float(df['windS'].iloc[-1]),
        'WD (deg)':float(df['windD'].iloc[-1]),
        'month':month,
        'hourofday':hour,
        'PM2_5':float(df['pm2_5'].iloc[-1]),
        'PM10':float(df['pm10'].iloc[-1]),
        'temp':float(df['temp'].iloc[-1]),
        'humidity':float(df['humidity'].iloc[-1]),
        'PM2_5(lag1)':float(df['pm2_5'].iloc[-2]),
        'PM2_5(lag2)':float(df['pm2_5'].iloc[-3]),
        'PM10(lag1)':float(df['pm10'].iloc[-2]),
        'PM10(lag2)':float(df['pm10'].iloc[-3]),
        'PM2_5(rolling_mean_3)':round(float(df['pm2_5'].iloc[-3:].mean()), 2),
        'PM10(rolling_mean_3)':round(float(df['pm10'].iloc[-3:].mean()), 2),
        'current_aqi': round(aqi),
        'predicted_aqi': prediction
    }
    return data
extract_from_redis()