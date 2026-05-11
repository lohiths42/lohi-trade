#!/usr/bin/env python3
"""Interactive script to set up Nubra TOTP for automated login.

Run this ONCE interactively. It will:
1. Log in with your phone + OTP + MPIN
2. Generate a TOTP secret
3. Print the secret so you can add it to .env

After this, the backend can auto-login using TOTP without needing OTP each time.

Usage:
    source lohi_trade_venv/bin/activate
    cd backend-gateway
    python scripts/nubra_setup_totp.py
"""

import os
import sys

# Load .env
from dotenv import load_dotenv
load_dotenv()

phone = os.getenv("NUBRA_PHONE_NO", "")
mpin = os.getenv("NUBRA_MPIN", "")

if not phone or not mpin:
    print("ERROR: Set NUBRA_PHONE_NO and NUBRA_MPIN in .env first")
    sys.exit(1)

# Set env vars the SDK expects
os.environ["PHONE_NO"] = phone
os.environ["MPIN"] = mpin

print(f"Phone: {phone}")
print(f"MPIN: {'*' * len(mpin)}")
print()

from nubra_python_sdk.start_sdk import InitNubraSdk, NubraEnv

env_str = os.getenv("NUBRA_ENV", "PROD").upper()
nubra_env = NubraEnv.UAT if env_str == "UAT" else NubraEnv.PROD

print(f"Step 1: Logging in to Nubra ({env_str})...")
print("You will receive an OTP on your phone. Enter it when prompted.")
print()

try:
    nubra = InitNubraSdk(nubra_env, env_creds=True)
    print("\nLogin successful!")
except Exception as e:
    print(f"\nLogin failed: {e}")
    sys.exit(1)

print()
print("Step 2: Generating TOTP secret...")
try:
    secret = nubra.totp_generate_secret()
    print(f"\nTOTP Secret: {secret}")
    print()
    print("Step 3: Add this secret to an authenticator app (Google Authenticator, Authy, etc.)")
    print("Then enter the 6-digit code from the app to enable TOTP:")
    print()

    nubra.totp_enable()
    print("\nTOTP enabled successfully!")
    print()
    print("=" * 60)
    print(f"Add this to your backend-gateway/.env:")
    print(f"NUBRA_TOTP_SECRET={secret}")
    print("=" * 60)

except Exception as e:
    print(f"\nTOTP setup failed: {e}")
    print("You can still use OTP login, but it requires manual interaction.")
    sys.exit(1)
