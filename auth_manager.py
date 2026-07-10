import requests
import pyotp
import logging

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
    params = {
        "dhanClientId": client_id,
        "pin": pin,
        "totp": current_otp
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)'
    }
    
    logger.info("Requesting fresh access token for Client ID ending in ...%s", client_id[-4:])
    
    response = requests.post(url, params=params, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        token = data.get("accessToken")
        if token:
            logger.info("Successfully generated fresh Access Token.")
            return token
        else:
            raise Exception(f"Token not found in response. Response: {data}")
    else:
        raise Exception(f"Auth API failed with status {response.status_code}. Details: {response.text}")
