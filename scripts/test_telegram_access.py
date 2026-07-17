import asyncio
from datetime import timedelta, timezone
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".secrets" / "telegram.env"
SESSION_PATH = PROJECT_ROOT / ".secrets" / "telegram_session.txt"
CHANNEL_USERNAME = "darthacking"
SEOUL_TIMEZONE = timezone(timedelta(hours=9), "KST")


def load_environment(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def load_credentials():
    if not ENV_PATH.is_file() or not SESSION_PATH.is_file():
        raise FileNotFoundError("Local Telegram secret files are missing")

    values = load_environment(ENV_PATH)
    api_id = int(values["TELEGRAM_API_ID"])
    api_hash = values["TELEGRAM_API_HASH"]
    session_string = SESSION_PATH.read_text(encoding="utf-8").strip()
    if not api_hash or not session_string:
        raise ValueError("Local Telegram secret files are incomplete")
    return api_id, api_hash, session_string


def to_seoul_time(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SEOUL_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z")


async def verify_access():
    client = None
    try:
        api_id, api_hash, session_string = load_credentials()
        client = TelegramClient(StringSession(session_string), api_id, api_hash)
        await client.connect()

        if not await client.is_user_authorized():
            raise PermissionError("The local Telegram session is not authorized")

        channel = await client.get_entity(CHANNEL_USERNAME)
        channel_title = getattr(channel, "title", "N/A")
        message_metadata = []
        async for message in client.iter_messages(channel, limit=5):
            message_metadata.append((message.id, message.date))

        print(f"Channel title: {channel_title}")
        for message_id, posted_at in message_metadata:
            print(f"Message ID: {message_id} | Posted at: {to_seoul_time(posted_at)}")
        print(f"Message ID count: {len(message_metadata)}")
        print("Telegram channel access verified")
    except Exception as error:
        print(f"Channel access failed ({type(error).__name__}).")
    finally:
        if client is not None:
            await client.disconnect()


if __name__ == "__main__":
    asyncio.run(verify_access())
