import os
import json
import requests
import logging
import pyotp
from datetime import datetime

logger = logging.getLogger(__name__)

def get_fresh_dhan_token(client_id: str, pin: str, totp_secret: str) -> str:
    """
    Dynamically generates a fresh Dhan access token using a TOTP secret.
    """
    if not all([client_id, pin, totp_secret]):
        raise ValueError("Missing credentials (DHAN_CLIENT_ID, DHAN_PIN, or DHAN_TOTP_SECRET)")

    # 1. Generate TOTP code
    totp = pyotp.TOTP(totp_secret.replace(" ", ""))
    current_otp = totp.now()

    # 2. Call Dhan Auth API
    url = "https://auth.dhan.co/app/generateAccessToken"
    # Try to load cached token
    cache_file = ".dhan_token_cache.json"
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                cache = json.load(f)
            # Check if token was generated today
            token_date = cache.get("date", "")
            today_str = datetime.now().strftime("%Y-%m-%d")
            if token_date == today_str and cache.get("token"):
                return cache["token"]
        except Exception as e:
            logger.warning(f"Failed to read token cache: {e}")

    logger.info(f"Requesting fresh access token for Client ID ending in ...{client_id[-4:]}")
    
    url = "https://auth.dhan.co/app/generateAccessToken"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    import time
    for attempt in range(12):
        totp = pyotp.TOTP(totp_secret).now()
        params = {
            "dhanClientId": client_id,
            "pin": pin,
            "totp": totp
        }
        
        response = requests.post(url, params=params, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            if "accessToken" in data:
                token = data["accessToken"]
                # Save to cache
                try:
                    with open(cache_file, 'w') as f:
                        json.dump({
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "token": token
                        }, f)
                except Exception as e:
                    logger.warning(f"Failed to write token cache: {e}")
                logger.info("Successfully generated and cached fresh Access Token.")
                return token
            else:
                msg = data.get('message', '')
                if 'Invalid TOTP' in msg or '2 minutes' in msg:
                    logger.warning(f"TOTP issue ({msg}), retrying in 10s (attempt {attempt+1}/12)...")
                    time.sleep(10)
                    continue
                raise Exception(f"Token not found in response. Response: {data}")
        else:
            logger.warning(f"Auth failed with HTTP {response.status_code}, retrying...")
            time.sleep(5)
            
    raise Exception("Failed to generate Dhan Access Token after multiple retries.")
