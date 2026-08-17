from pydantic import BaseModel

class Model(BaseModel):
    pass

class AQI_Model(Model):
    timestamp_utc: str
    current_aqi: int
    predicted_aqi_3h: int
    pm2_5: float
    pm10: float

class AQI_Weather(Model):
    timestamp_utc: str
    humidity:int
    temperature:float
    ws_ms:float
    wd_deg:int