#!/usr/bin/env python3
"""Force WOTD (Workout of the Day) generation and push to Garmin Connect immediately.

Bypasses last_processed_sleep_date.txt checks and forces an immediate AI workout
generation and push to Garmin Connect calendar.

Usage:
  python force_wotd.py
"""
import os
import sys
import logging
from datetime import date
from pathlib import Path
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("force_wotd")

def mfa_callback() -> str:
    mfa_code = os.getenv("GARMIN_MFA_CODE", "").strip()
    if mfa_code:
        return mfa_code
    print("\n" + "="*50)
    print("Garmin MFA verification required for new IP/device.")
    print("Check your email (arnabbiswas@yahoo.com) for the 6-digit code.")
    print("="*50)
    return input("Enter 6-digit Garmin MFA code: ").strip()

def main():
    config_path = Path("coach_config.yaml")
    if not config_path.exists():
        logger.error("coach_config.yaml not found in current directory.")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    email = os.getenv("GARMIN_EMAIL") or (config.get("athlete") or {}).get("email")
    password = os.getenv("GARMIN_PASSWORD")

    if not email or not password:
        logger.error("GARMIN_EMAIL and GARMIN_PASSWORD must be set in environment variables or .env")
        sys.exit(1)

    # Determine user data dir
    user_data_dir = Path(os.getenv("OUTPUT_DIR", "./data"))
    user_data_dir.mkdir(parents=True, exist_ok=True)

    # Force remove last_processed_sleep_date.txt if present
    last_sleep_file = user_data_dir / "last_processed_sleep_date.txt"
    if last_sleep_file.exists():
        last_sleep_file.unlink()
        logger.info("Removed cached %s", last_sleep_file)

    # Connect to Garmin
    from services.garmin.client import GarminConnectClient
    from services.garmin.wotd_generator import generate_workout_of_the_day

    logger.info("Authenticating with Garmin Connect (%s)...", email)
    garmin_wrapper = GarminConnectClient(token_dir="./tokens")
    garmin_wrapper.connect(email, password, mfa_callback=mfa_callback)
    client = garmin_wrapper.client

    today_iso = date.today().isoformat()
    logger.info("Fetching sleep data for today (%s)...", today_iso)
    sleep_data = client.get_sleep_data(today_iso) or {}

    logger.info("Generating and pushing WOTD for %s...", today_iso)
    generate_workout_of_the_day(
        client=client,
        config=config,
        user_data_dir=user_data_dir,
        sleep_data=sleep_data,
    )
    logger.info("Done! Check your Garmin Connect app / watch for today's workout.")

if __name__ == "__main__":
    main()
