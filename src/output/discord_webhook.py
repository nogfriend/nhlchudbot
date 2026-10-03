"""
This module provides an interface to Discord via webhooks that can be used to
post messages and media attachments.
"""

import json
import os
import time
import uuid
from typing import Dict, Optional

import requests
from dotenv import load_dotenv

from src.logger import log
from src.output.outputter import Outputter

# Discord message content limit
MAX_LENGTH = 2000

DISCORD_POST_ATTEMPTS = 3
DISCORD_POST_RETRY_DELAY_SECONDS = 2
REQUEST_TIMEOUT = 120

# Discord allows up to 25MB on many servers (boost level dependent)
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


class DiscordWebhook(Outputter):
    """
    Outputter that posts to a Discord channel using an incoming webhook URL.
    Set DISCORD_WEBHOOK_URL in the environment (or .env file).
    """

    def __init__(self) -> None:
        super().__init__()
        load_dotenv()
        self.webhook_url: str = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
        if not self.webhook_url:
            log.error(
                "DISCORD_WEBHOOK_URL is not set. Discord posts will fail until it is configured."
            )
        else:
            redacted = self.webhook_url[:40] + "..." if len(self.webhook_url) > 40 else self.webhook_url
            log.info("Discord webhook configured: " + redacted)

    def name(self) -> str:
        return "discord"

    def post(self, text: str) -> Optional[Dict[str, str]]:
        return self._send(text=text, media=None)

    def reply(self, parent: Optional[Dict[str, str]], text: str) -> Optional[Dict[str, str]]:
        return self._send(text=text, media=None)

    def post_with_media(self, text: str, media: str) -> Optional[Dict[str, str]]:
        return self._send(text=text, media=media)

    def reply_with_media(
        self,
        parent: Optional[Dict[str, str]],
        text: str,
        media: str,
    ) -> Optional[Dict[str, str]]:
        return self._send(text=text, media=media)

    def _send(self, text: str, media: Optional[str]) -> Optional[Dict[str, str]]:
        if not self.webhook_url:
            log.error("Discord webhook URL missing; cannot post.")
            return None

        content = (text or "").strip()
        if len(content) > MAX_LENGTH:
            content = content[: MAX_LENGTH - 3] + "..."

        local_file: Optional[str] = None
        if media and os.path.isfile(media):
            try:
                size = os.path.getsize(media)
            except OSError:
                size = 0
            if size <= 0:
                log.warning("Discord - media file empty or unreadable: " + media)
            elif size > MAX_ATTACHMENT_BYTES:
                log.warning(
                    f"Discord - media too large ({size} bytes > {MAX_ATTACHMENT_BYTES}); "
                    "cannot attach video file."
                )
            else:
                local_file = media
                log.info(f"Discord - will attach video file ({size} bytes): {media}")
        elif media:
            log.warning("Discord - media is not a local file, cannot attach: " + str(media))

        for attempt in range(1, DISCORD_POST_ATTEMPTS + 1):
            try:
                if local_file:
                    post_id = self._post_with_file(content, local_file)
                else:
                    post_id = self._post_text(content)

                if post_id is not None:
                    self.add_post(text)
                    return post_id

            except requests.RequestException as exc:
                log.error(
                    f"Discord - request failed (attempt {attempt}/{DISCORD_POST_ATTEMPTS}): {exc}"
                )

            if attempt < DISCORD_POST_ATTEMPTS:
                time.sleep(DISCORD_POST_RETRY_DELAY_SECONDS)

        log.error("Discord - failed to post after retries.")
        return None

    def _post_text(self, content: str) -> Optional[Dict[str, str]]:
        url = self._webhook_url_with_wait()
        payload = {"content": content}
        log.info("Discord - sending text post (" + str(len(content)) + " chars)")
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        return self._handle_response(response)

    def _post_with_file(self, content: str, media_path: str) -> Optional[Dict[str, str]]:
        """POST multipart form with content + video attachment (inline playable in Discord)."""
        url = self._webhook_url_with_wait()
        filename = os.path.basename(media_path) or "highlight.mp4"
        log.info("Discord - uploading video attachment: " + filename)

        with open(media_path, "rb") as file_handle:
            # Discord webhook multipart: payload_json + files[n]
            files = {
                "files[0]": (filename, file_handle, "video/mp4"),
            }
            data = {
                "payload_json": json.dumps({"content": content}),
            }
            response = requests.post(
                url,
                data=data,
                files=files,
                timeout=REQUEST_TIMEOUT,
            )
        return self._handle_response(response)

    def _webhook_url_with_wait(self) -> str:
        if "wait=" in self.webhook_url:
            return self.webhook_url
        separator = "&" if "?" in self.webhook_url else "?"
        return f"{self.webhook_url}{separator}wait=true"

    def _handle_response(self, response: requests.Response) -> Optional[Dict[str, str]]:
        if response.status_code in (200, 204):
            message_id = None
            try:
                body = response.json()
                message_id = str(body.get("id", "")) if body else None
            except ValueError:
                pass
            if not message_id:
                message_id = str(uuid.uuid4())
            log.info(f"Discord - posted successfully (id={message_id})")
            return {"id": message_id}

        log.error(
            f"Discord - post failed: HTTP {response.status_code} - {response.text[:500]}"
        )
        return None
