#!/usr/bin/env python3
import logging
import subprocess
from pathlib import Path

import yaml
from garminconnect import Garmin

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def main():
    project_dir = Path(__file__).parent.resolve()
    config_path = project_dir / "coach_config.yaml"
    tokens_dir = project_dir / "tokens"
    data_dir = project_dir / "data"
    last_id_file = data_dir / "last_processed_id.txt"

    # 1. Parse athlete email from config
    if not config_path.exists():
        logger.error("Config file not found at %s", config_path)
        return

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    email = config.get("athlete", {}).get("email")
    if not email:
        logger.error("Athlete email is missing in coach_config.yaml")
        return

    # 2. Login to Garmin Connect (utilizing cached tokens)
    logger.info("Initializing Garmin client check...")
    try:
        # We pass a blank password because we expect to login via tokenstore
        client = Garmin(email=email, password="", prompt_mfa=None)
        client.login(tokenstore=str(tokens_dir))
    except Exception as e:
        logger.error("Failed to log in using cached tokens: %s", e)
        logger.error("Please run 'docker compose run --rm coach' once interactively to refresh tokens/MFA.")
        return

    # 3. Retrieve the single latest activity
    try:
        logger.info("Checking latest Garmin activity...")
        activities = client.get_activities(0, 1)
    except Exception as e:
        logger.error("Failed to fetch activities from Garmin Connect: %s", e)
        return

    if not activities:
        logger.info("No activities found on your Garmin Connect account.")
        return

    latest_activity = activities[0]
    activity_id = str(latest_activity.get("activityId"))
    activity_type = latest_activity.get("activityType", {}).get("typeKey", "unknown")
    activity_name = latest_activity.get("activityName", "Activity")
    start_time = latest_activity.get("startTimeLocal", "")

    logger.info("Latest activity on Garmin Connect: ID=%s (%s, type=%s, start=%s)", activity_id, activity_name, activity_type, start_time)

    # 4. Check if we've already processed this activity ID
    last_processed_id = ""
    if last_id_file.exists():
        last_processed_id = last_id_file.read_text(encoding="utf-8").strip()

    if activity_id == last_processed_id:
        logger.info("Latest activity matches last processed ID. No new data. Exiting silently.")
        return

    # 5. New activity detected! Trigger analysis
    logger.info("New activity detected (ID: %s != %s)!", activity_id, last_processed_id)
    logger.info("Triggering Garmin AI Coach analysis workflow...")

    # Run the docker compose command to execute coach
    cmd = ["docker", "compose", "run", "--rm", "coach"]
    try:
        # Running the command
        res = subprocess.run(cmd, cwd=str(project_dir), capture_output=True, text=True, check=False)
        if res.returncode == 0:
            logger.info("Garmin AI Coach analysis finished successfully!")
            # Update the last processed activity ID
            data_dir.mkdir(parents=True, exist_ok=True)
            last_id_file.write_text(activity_id, encoding="utf-8")
            logger.info("Updated last processed ID to %s", activity_id)
        else:
            logger.error("Garmin AI Coach analysis container failed!")
            logger.error(res.stderr)
    except Exception as e:
        logger.error("Failed to run docker compose command: %s", e)

if __name__ == "__main__":
    main()
