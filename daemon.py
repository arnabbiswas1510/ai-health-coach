#!/usr/bin/env python3
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml
from garminconnect import Garmin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("daemon")

def check_and_run():  # noqa: C901
    project_dir = Path(__file__).parent.resolve()
    config_path = project_dir / "coach_config.yaml"
    tokens_dir = project_dir / "tokens"
    data_dir = project_dir / "data"

    # 1. Parse athlete email from environment variable or config
    email = os.getenv("GARMIN_EMAIL")
    config: dict[str, Any] = {}
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("Could not load config at %s: %s", config_path, e)

    if not email:
        email = config.get("athlete", {}).get("email")

    if not email:
        logger.error("Athlete email is missing. Please set GARMIN_EMAIL env var or provide coach_config.yaml")
        return

    # 2. Login to Garmin Connect (utilizing cached tokens)
    logger.info("Checking Garmin Connect for updates...")
    sanitized_email = email.replace("@", "_").replace(".", "_")
    user_tokens_dir = tokens_dir / sanitized_email
    user_tokens_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Login via tokenstore without password (requires one initial login with password)
        client = Garmin(email=email, password="", prompt_mfa=None)
        client.login(tokenstore=str(user_tokens_dir))
    except Exception as e:
        logger.error("Failed to log in using cached tokens: %s", e)
        logger.error("Please run the coach container once interactively to log in/refresh tokens.")
        return

    # Retrieve latest athlete name dynamically from Garmin Connect profile
    display_name = None
    try:
        display_name = client.get_full_name() or client.display_name
    except Exception as e:
        logger.warning("Could not retrieve profile name from Garmin Connect: %s", e)
        try:
            display_name = client.display_name
        except Exception:
            pass

    if display_name and isinstance(display_name, str):
        display_name = "".join(c if c.isalnum() or c in ("-", "_", " ") else "_" for c in display_name).strip()
        display_name = display_name.replace(" ", "_")
    else:
        display_name = None

    if not display_name:
        display_name = os.getenv("ATHLETE_NAME") or config.get("athlete", {}).get("name", "Athlete")

    user_data_dir = data_dir / display_name
    user_data_dir.mkdir(parents=True, exist_ok=True)
    last_id_file = user_data_dir / "last_processed_id.txt"

    # 3. Retrieve latest activity
    try:
        activities = client.get_activities(0, 1)
    except Exception as e:
        logger.error("Failed to fetch activities: %s", e)
        return

    if not activities:
        logger.info("No activities found on your account.")
        return

    latest_activity = activities[0]
    activity_id = str(latest_activity.get("activityId"))
    activity_name = latest_activity.get("activityName", "Activity")
    start_time = latest_activity.get("startTimeLocal", "")

    logger.info("Latest activity: ID=%s (%s, start=%s)", activity_id, activity_name, start_time)

    # 4. Compare with last processed ID
    last_processed_id = ""
    if last_id_file.exists():
        last_processed_id = last_id_file.read_text(encoding="utf-8").strip()

    if activity_id == last_processed_id:
        logger.info("No new runs detected for %s. Plan is up to date.", display_name)
        return

    # 5. New activity! Run the CLI analysis
    logger.info("New activity detected for %s! (ID: %s != %s)", display_name, activity_id, last_processed_id)
    logger.info("Running coach analysis workflow...")

    # Run the python CLI script directly inside the container
    cmd = ["python", "cli/garmin_ai_coach_cli.py"]
    if config_path.exists():
        cmd.extend(["--config", str(config_path)])

    try:
        res = subprocess.run(cmd, cwd=str(project_dir), capture_output=True, text=True, check=False)
        if res.returncode == 0:
            logger.info("Coach analysis completed successfully!")
            # Update local id record
            last_id_file.write_text(activity_id, encoding="utf-8")
            logger.info("Updated last processed ID to %s", activity_id)
        else:
            logger.error("Coach analysis execution failed:")
            logger.error(res.stderr)
    except Exception as e:
        logger.error("Failed to run coach command: %s", e)

def main():
    poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "3600"))
    logger.info("Garmin AI Coach daemon started. Polling interval: %s seconds.", poll_interval)

    # Run once immediately on start
    try:
        check_and_run()
    except Exception as e:
        logger.exception("Unhandled error in check_and_run: %s", e)

    # Enter loop
    while True:
        try:
            time.sleep(poll_interval)
            check_and_run()
        except KeyboardInterrupt:
            logger.info("Daemon stopped by user.")
            break
        except Exception as e:
            logger.exception("Unhandled error in daemon loop: %s", e)

if __name__ == "__main__":
    main()
