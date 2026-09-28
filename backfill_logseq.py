"""One-off backfill of Garmin sleep/run metrics into the Logseq journal.

Writes via services.logseq.logseq_client, which talks SFTP-over-SSH directly to
the journal .md files on the host machine. The old Logseq HTTP API on port 3000
is gone, so this script no longer sets _LOGSEQ_HOST / LOGSEQ_API_TOKEN (those
attributes do not exist on the client any more; assigning them silently created
dead module attributes and made the failure message misleading).

Requires the LOGSEQ_SSH_* / LOGSEQ_GRAPH_PATH vars to be set, so .env is always
loaded up front rather than only when Garmin credentials happen to be missing.
"""
import datetime
import os
import sys
from pathlib import Path

# Add project root to sys.path so we can import services
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from dotenv import load_dotenv

from services.garmin.client import GarminConnectClient
from services.logseq import logseq_client

# Load .env unconditionally: the Logseq SSH settings live there too, not just
# the Garmin credentials.
load_dotenv()


def backfill():
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        print("GARMIN_EMAIL and GARMIN_PASSWORD must be set in the environment or .env")
        return

    if not os.environ.get("LOGSEQ_SSH_HOST") or not os.environ.get("LOGSEQ_GRAPH_PATH"):
        print(
            "LOGSEQ_SSH_HOST and LOGSEQ_GRAPH_PATH must be set — the backfill writes "
            "to the journal over SSH/SFTP, not via the old HTTP API."
        )
        return

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
        
        activities = client.client.get_activities_by_date(target_date.isoformat(), target_date.isoformat(), activitytype="running")
        _run_distance = None
        _run_avg_speed = None
        _run_avg_hr = None
        
        if activities and len(activities) > 0:
            act = activities[0]
            if act.get("distance"):
                _run_distance = round(act["distance"] / 1000.0, 2)
            _run_avg_speed = act.get("averageSpeed")
            if act.get("averageHR"):
                _run_avg_hr = int(act["averageHR"])

        props = logseq_client.build_props(
            sleep_duration_hours=_sleep_duration,
            sleep_bed_time=_bed_time,
            sleep_wake_time=_wake_time,
            sleep_quality=_sleep_quality,
            run_distance_km=_run_distance,
            run_avg_speed_ms=_run_avg_speed,
            run_avg_heart_rate=_run_avg_hr,
        )
        
        if props:
            print(f"Writing properties for {target_date}...")
            success = logseq_client.write_props_dict(props, date=target_date)
            if success:
                print(f"Successfully wrote to {target_date}")
            else:
                print(
                    f"Failed to write to {target_date}. Check LOGSEQ_SSH_HOST / "
                    f"LOGSEQ_SSH_USER / LOGSEQ_GRAPH_PATH and that the SSH key is authorised."
                )
        else:
            print(f"No properties to write for {target_date}")

if __name__ == "__main__":
    backfill()
