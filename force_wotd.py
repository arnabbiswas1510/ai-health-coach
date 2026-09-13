#!/usr/bin/env python3
import argparse
import os
import sys
import logging
from datetime import date, timedelta
from pathlib import Path
import yaml

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('force_wotd')

def mfa_callback() -> str:
    mfa_code = os.getenv('GARMIN_MFA_CODE', '').strip()
    if mfa_code:
        return mfa_code
    print('='*50)
    print('Garmin MFA verification required for new IP/device.')
    print('Check your email (arnabbiswas@yahoo.com) for the 6-digit code.')
    print('='*50)
    return input('Enter 6-digit Garmin MFA code: ').strip()

def main():
    parser = argparse.ArgumentParser(description='Force WOTD generation and push to Garmin Connect.')
    parser.add_argument('--yesterday', action='store_true', help='Generate and push WOTD for yesterday')
    parser.add_argument('--date', type=str, default=None, help='Target date YYYY-MM-DD')
    args = parser.parse_args()

    if args.yesterday:
        target_date = (date.today() - timedelta(days=1)).isoformat()
    elif args.date:
        target_date = args.date
    else:
        target_date = date.today().isoformat()

    config_path = Path('coach_config.yaml')
    if not config_path.exists():
        logger.error('coach_config.yaml not found in current directory.')
        sys.exit(1)

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    email = os.getenv('GARMIN_EMAIL') or (config.get('athlete') or {}).get('email')
    password = os.getenv('GARMIN_PASSWORD')

    if not email:
        logger.error('GARMIN_EMAIL must be set in environment variables or .env')
        sys.exit(1)
    if not password:
        password = ""

    user_data_dir = Path(os.getenv('OUTPUT_DIR', './data'))
    user_data_dir.mkdir(parents=True, exist_ok=True)

    last_sleep_file = user_data_dir / 'last_processed_sleep_date.txt'
    if last_sleep_file.exists():
        last_sleep_file.unlink()
        logger.info('Removed cached %s', last_sleep_file)

    last_wotd_file = user_data_dir / 'last_pushed_wotd_date.txt'
    if last_wotd_file.exists():
        last_wotd_file.unlink()
        logger.info('Removed cached %s', last_wotd_file)

    from services.garmin.client import GarminConnectClient
    from services.garmin.wotd_generator import generate_workout_of_the_day

    logger.info('Authenticating with Garmin Connect (%s)...', email)
    garmin_wrapper = GarminConnectClient(token_dir='./tokens')
    garmin_wrapper.connect(email, password, mfa_callback=mfa_callback)
    client = garmin_wrapper.client

    logger.info('Fetching sleep data for target date (%s)...', target_date)
    sleep_data = client.get_sleep_data(target_date) or {}

    logger.info('Generating and pushing WOTD for %s...', target_date)
    generate_workout_of_the_day(
        client=client,
        config=config,
        user_data_dir=user_data_dir,
        sleep_data=sleep_data,
        target_date=target_date,
    )
    logger.info('Done! Check your Garmin Connect app / watch for WOTD (%s).', target_date)

if __name__ == '__main__':
    main()
