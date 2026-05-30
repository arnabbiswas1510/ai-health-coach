#!/usr/bin/env python3
import logging
import os
import subprocess
import time
from pathlib import Path
import yaml
from garminconnect import Garmin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("daemon")

def check_and_run():
    project_dir = Path(__file__).parent.resolve()
    config_path = project_dir / "coach_config.yaml"
    tokens_dir = project_dir / "tokens"
    data_dir = project_dir / "data"
    last_id_file = data_dir / "last_processed_id.txt"

    # 1. Parse athlete email from config
    if not config_path.exists():
        logger.error(f"Config file not found at {config_path}")
        return

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    email = config.get("athlete", {}).get("email")
    if not email:
        logger.error("Athlete email is missing in coach_config.yaml")
        return

    # 2. Login to Garmin Connect (utilizing cached tokens)
    logger.info("Checking Garmin Connect for updates...")
    try:
        # Login via tokenstore without password (requires one initial login with password)
        client = Garmin(email=email, password="", prompt_mfa=None)
        client.login(tokenstore=str(tokens_dir))
    except Exception as e:
        logger.error(f"Failed to log in using cached tokens: {e}")
        logger.error("Please run the coach container once interactively to log in/refresh tokens.")
        return

    # 3. Retrieve latest activity
    try:
        activities = client.get_activities(0, 1)
    except Exception as e:
        logger.error(f"Failed to fetch activities: {e}")
        return

    if not activities:
        logger.info("No activities found on your account.")
        return

    latest_activity = activities[0]
    activity_id = str(latest_activity.get("activityId"))
    activity_name = latest_activity.get("activityName", "Activity")
    start_time = latest_activity.get("startTimeLocal", "")

    logger.info(f"Latest activity: ID={activity_id} ({activity_name}, start={start_time})")

    # 4. Compare with last processed ID
    last_processed_id = ""
    if last_id_file.exists():
        last_processed_id = last_id_file.read_text(encoding="utf-8").strip()

    if activity_id == last_processed_id:
        logger.info("No new runs detected. Plan is up to date.")
        return

    # 5. New activity! Run the CLI analysis
    logger.info(f"New activity detected! (ID: {activity_id} != {last_processed_id})")
    logger.info("Running coach analysis workflow...")

    # Run the python CLI script directly inside the container
    cmd = ["python", "cli/garmin_ai_coach_cli.py", "--config", "/app/coach_config.yaml"]
    try:
        res = subprocess.run(cmd, cwd=str(project_dir), capture_output=True, text=True)
        if res.returncode == 0:
            logger.info("Coach analysis completed successfully!")
            # Update local id record
            data_dir.mkdir(parents=True, exist_ok=True)
            last_id_file.write_text(activity_id, encoding="utf-8")
            logger.info(f"Updated last processed ID to {activity_id}")
        else:
            logger.error("Coach analysis execution failed:")
            logger.error(res.stderr)
    except Exception as e:
        logger.error(f"Failed to run coach command: {e}")

def main():
    poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "3600"))
    logger.info(f"Garmin AI Coach daemon started. Polling interval: {poll_interval} seconds.")
    
    # Run once immediately on start
    try:
        check_and_run()
    except Exception as e:
        logger.exception(f"Unhandled error in check_and_run: {e}")

    # Enter loop
    while True:
        try:
            time.sleep(poll_interval)
            check_and_run()
        except KeyboardInterrupt:
            logger.info("Daemon stopped by user.")
            break
        except Exception as e:
            logger.exception(f"Unhandled error in daemon loop: {e}")

if __name__ == "__main__":
    main()
