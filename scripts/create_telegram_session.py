import asyncio
import getpass
import re
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import (
    ApiIdInvalidError,
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    PasswordHashInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECRETS_DIR = PROJECT_ROOT / ".secrets"
ENV_PATH = SECRETS_DIR / "telegram.env"
SESSION_PATH = SECRETS_DIR / "telegram_session.txt"


def read_credentials():
    api_id_text = input("Telegram API ID: ").strip()
    if not api_id_text.isdigit() or int(api_id_text) <= 0:
        raise ValueError("API ID must be a positive integer")

    while True:
        api_hash = getpass.getpass("Telegram API Hash (hidden): ").strip()
        api_hash_confirmation = getpass.getpass(
            "Telegram API Hash again (hidden): "
        ).strip()
        if not re.fullmatch(r"[0-9a-fA-F]{32}", api_hash):
            print("API Hash format is invalid. Enter the 32 hexadecimal characters again.")
            continue
        if api_hash != api_hash_confirmation:
            print("API Hash entries did not match. Enter them again.")
            continue
        break

    phone = input("Telegram phone number (include country code): ").strip()
    if not api_hash or not phone:
        raise ValueError("API Hash and phone number are required")

    return int(api_id_text), api_hash, phone


def save_secrets(api_id, api_hash, session_string):
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    ENV_PATH.write_text(
        f"TELEGRAM_API_ID={api_id}\nTELEGRAM_API_HASH={api_hash}\n",
        encoding="utf-8",
    )
    SESSION_PATH.write_text(session_string, encoding="utf-8")


def print_safe_error(error):
    error_name = type(error).__name__
    guidance = {
        ApiIdInvalidError: "Check the API ID and API Hash in my.telegram.org.",
        PhoneNumberInvalidError: "Check the phone number and country code.",
        PhoneCodeInvalidError: "Run the script again and enter the newest login code.",
        PhoneCodeExpiredError: "Run the script again to request a new login code.",
        PasswordHashInvalidError: "Run the script again and check the two-step password.",
        FloodWaitError: "Wait before trying again because Telegram temporarily limited requests.",
    }
    message = guidance.get(type(error), "Check the inputs and network, then try again.")
    print(f"Login failed ({error_name}). {message}")


async def create_session():
    client = None
    try:
        api_id, api_hash, phone = read_credentials()
        client = TelegramClient(StringSession(), api_id, api_hash)
        await client.connect()

        sent_code = await client.send_code_request(phone)
        login_code = getpass.getpass("Telegram login code (hidden): ").strip()

        try:
            await client.sign_in(
                phone=phone,
                code=login_code,
                phone_code_hash=sent_code.phone_code_hash,
            )
        except SessionPasswordNeededError:
            password = getpass.getpass("Telegram two-step password (hidden): ")
            await client.sign_in(password=password)

        if not await client.is_user_authorized():
            raise RuntimeError("Telegram authorization was not completed")

        save_secrets(api_id, api_hash, client.session.save())
        print("Telegram login succeeded.")
        print("Secret files were saved locally in .secrets.")
    except (KeyboardInterrupt, EOFError):
        print("Login cancelled. No credentials were printed.")
    except Exception as error:
        print_safe_error(error)
    finally:
        if client is not None:
            await client.disconnect()


if __name__ == "__main__":
    asyncio.run(create_session())
