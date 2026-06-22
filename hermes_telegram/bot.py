"""
Hermes Telegram userbot — connects your Telegram account to a local Nous-Hermes model via Ollama.

Usage:
    python bot.py

On first run, Telethon will ask for your phone number and the OTP code sent by Telegram.
The session is then saved so subsequent runs don't require re-authentication.
"""

import asyncio
import logging
import os
from collections import defaultdict

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.types import User

from hermes_client import HermesClient

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Conversation history per chat_id (keeps last N turns in memory)
MAX_HISTORY_TURNS = 10
_histories: dict[int, list[dict]] = defaultdict(list)


def _get_allowed_usernames() -> set[str]:
    raw = os.environ.get("ALLOWED_USERNAMES", "")
    return {u.strip().lstrip("@").lower() for u in raw.split(",") if u.strip()}


def _is_allowed(sender: User, own_id: int) -> bool:
    if sender.id == own_id:
        return True
    allowed = _get_allowed_usernames()
    if not allowed:
        return False
    username = (sender.username or "").lower()
    return username in allowed


def _trim_history(chat_id: int) -> None:
    history = _histories[chat_id]
    # Each turn = 2 entries (user + assistant); keep last MAX_HISTORY_TURNS
    max_entries = MAX_HISTORY_TURNS * 2
    if len(history) > max_entries:
        _histories[chat_id] = history[-max_entries:]


async def main() -> None:
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]
    session_path = os.environ.get("SESSION_PATH", "hermes_session")

    hermes = HermesClient()

    log.info("Checking Ollama connectivity at %s …", os.environ["OLLAMA_HOST"])
    if not await hermes.health_check():
        log.warning("Ollama does not seem reachable — messages will return errors until it's up.")
    else:
        log.info("Ollama OK, model: %s", os.environ["HERMES_MODEL"])

    client = TelegramClient(session_path, api_id, api_hash)

    @client.on(events.NewMessage(incoming=True, pattern=r"(?i)^/start$"))
    async def handle_start(event: events.NewMessage.Event) -> None:
        me = await client.get_me()
        sender = await event.get_sender()
        if not isinstance(sender, User) or not _is_allowed(sender, me.id):
            return
        await event.reply(
            f"Hermes agent ready — model: `{os.environ['HERMES_MODEL']}`\n"
            "Send any message to chat. Use /reset to clear conversation history."
        )

    @client.on(events.NewMessage(incoming=True, pattern=r"(?i)^/reset$"))
    async def handle_reset(event: events.NewMessage.Event) -> None:
        me = await client.get_me()
        sender = await event.get_sender()
        if not isinstance(sender, User) or not _is_allowed(sender, me.id):
            return
        _histories[event.chat_id].clear()
        await event.reply("Conversation history cleared.")

    @client.on(events.NewMessage(incoming=True))
    async def handle_message(event: events.NewMessage.Event) -> None:
        # Ignore commands (handled above) and empty messages
        text = (event.raw_text or "").strip()
        if not text or text.startswith("/"):
            return

        me = await client.get_me()
        sender = await event.get_sender()
        if not isinstance(sender, User) or not _is_allowed(sender, me.id):
            return

        log.info("Message from %s (id=%d): %s", sender.username or sender.id, sender.id, text[:80])

        async with client.action(event.chat_id, "typing"):
            try:
                reply = await hermes.chat(text, history=_histories[event.chat_id])
            except Exception as exc:
                log.error("Hermes error: %s", exc)
                await event.reply(f"Error contacting Hermes: {exc}")
                return

        # Update history
        _histories[event.chat_id].append({"role": "user", "content": text})
        _histories[event.chat_id].append({"role": "assistant", "content": reply})
        _trim_history(event.chat_id)

        await event.reply(reply)

    await client.start(phone=os.environ["TELEGRAM_PHONE"])
    me = await client.get_me()
    log.info("Logged in as @%s (id=%d)", me.username, me.id)
    log.info("Hermes agent listening… (Ctrl+C to stop)")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
