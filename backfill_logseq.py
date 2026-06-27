import os
import sys
import datetime
from pathlib import Path

# Add project root to sys.path so we can import services
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from services.logseq import logseq_client
from services.logseq import logseq_client
from services.garmin.client import GarminConnectClient

# Override LOGSEQ_HOST to connect locally on Windows
logseq_client._LOGSEQ_HOST = "http://127.0.0.1:3000"
logseq_client.LOGSEQ_API_TOKEN = os.environ.get("LOGSEQ_API_TOKEN", "")

def backfill():
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        from dotenv import load_dotenv
        load_dotenv()
        email = os.environ.get("GARMIN_EMAIL")
        password = os.environ.get("GARMIN_PASSWORD")
        
    client = GarminConnectClient(token_dir="tokens")
    try:
        client.connect(email, password)
    except Exception as e:
        print(f"Failed to login to Garmin: {e}")
        return

    today = datetime.date.today()
    
    # Backfill the last 7 days
    for i in range(6, -1, -1):
        target_date = today - datetime.timedelta(days=i)
        print(f"Fetching data for {target_date}...")
        
        sleep_data = client.client.get_sleep_data(target_date.isoformat()) or {}
        daily_dto = sleep_data.get("dailySleepDTO") or {}
        sleep_seconds = daily_dto.get("sleepTimeSeconds") or 0
        _sleep_duration = round(int(sleep_seconds) / 3600, 1) if sleep_seconds else None
        
        _bed_time = daily_dto.get("sleepStartTimestampLocal")
        if _bed_time and isinstance(_bed_time, str):
            _bed_time = _bed_time.split("T")[-1][:5] if "T" in _bed_time else None
        else:
            _bed_time = None
            
        _wake_time = daily_dto.get("sleepEndTimestampLocal")
        if _wake_time and isinstance(_wake_time, str):
            _wake_time = _wake_time.split("T")[-1][:5] if "T" in _wake_time else None
        else:
            _wake_time = None
            
        scores = daily_dto.get("sleepScores") or {}
        overall = scores.get("overall") or {}
        _sleep_quality = overall.get("value")
        
        props = logseq_client.build_props(
            sleep_duration_hours=_sleep_duration,
            sleep_bed_time=_bed_time,
            sleep_wake_time=_wake_time,
            sleep_quality=_sleep_quality,
        )
        
        if props:
            print(f"Writing properties for {target_date}...")
            success = logseq_client.write_props_dict(props, date=target_date)
            if success:
                print(f"Successfully wrote to {target_date}")
            else:
                print(f"Failed to write to {target_date}. Is Logseq running on port 3000?")
        else:
            print(f"No properties to write for {target_date}")

if __name__ == "__main__":
    backfill()
