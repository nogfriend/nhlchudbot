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

# Webhook endpoints accept multipart uploads; keep retries modest
DISCORD_POST_ATTEMPTS = 3
DISCORD_POST_RETRY_DELAY_SECONDS = 2
REQUEST_TIMEOUT = 30


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

    def name(self) -> str:
        """Return the name of this outputter."""
        return "discord"

    def post(self, text: str) -> Optional[Dict[str, str]]:
        """Send a post with the specified text."""
        return self._send(text=text, media=None, parent=None)

    def reply(self, parent: Optional[Dict[str, str]], text: str) -> Optional[Dict[str, str]]:
        """
        Send a reply. Discord webhooks do not support true reply threading the same way
        as Twitter/Bluesky, so we post a normal message (optionally noting the parent).
        """
        return self._send(text=text, media=None, parent=parent)

    def post_with_media(self, text: str, media: str) -> Optional[Dict[str, str]]:
        """Send a post with the specified text and media attachment."""
        return self._send(text=text, media=media, parent=None)

    def reply_with_media(
        self,
        parent: Optional[Dict[str, str]],
        text: str,
        media: str,
    ) -> Optional[Dict[str, str]]:
        """Send a reply with media (posted as a normal webhook message with attachment)."""
        return self._send(text=text, media=media, parent=parent)

    def _send(
        self,
        text: str,
        media: Optional[str],
        parent: Optional[Dict[str, str]],
    ) -> Optional[Dict[str, str]]:
        if not self.webhook_url:
            log.error("Discord webhook URL missing; cannot post.")
            return None

        content = text.strip()
        if len(content) > MAX_LENGTH:
            content = content[: MAX_LENGTH - 3] + "..."

        # Optional context when this would have been a reply
        if parent is not None and parent.get("id"):
            # Keep it lightweight; Discord webhooks can't natively "reply" without a bot token
            pass

        for attempt in range(1, DISCORD_POST_ATTEMPTS + 1):
            try:
                if media and os.path.isfile(media):
                    post_id = self._post_with_file(content, media)
                else:
                    if media:
                        log.warning(
                            "Discord - media path not found or not a file, posting text only: "
                            + str(media)
                        )
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
        """POST JSON content to the webhook."""
        # wait=true so Discord returns the created message (includes id)
        url = self._webhook_url_with_wait()
        payload = {"content": content}
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        return self._handle_response(response)

    def _post_with_file(self, content: str, media_path: str) -> Optional[Dict[str, str]]:
        """POST multipart form with content + file attachment."""
        url = self._webhook_url_with_wait()
        filename = os.path.basename(media_path) or "highlight.mp4"

        with open(media_path, "rb") as file_handle:
            files = {
                "file": (filename, file_handle, self._guess_content_type(filename)),
            }
            # Discord expects payload_json for the message body when attaching files
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
        """Append wait=true so the API returns the created message object."""
        if "wait=" in self.webhook_url:
            return self.webhook_url
        separator = "&" if "?" in self.webhook_url else "?"
        return f"{self.webhook_url}{separator}wait=true"

    def _handle_response(self, response: requests.Response) -> Optional[Dict[str, str]]:
        if response.status_code in (200, 204):
            # 204 when wait=false; with wait=true we get 200 + JSON body
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

    @staticmethod
    def _guess_content_type(filename: str) -> str:
        lower = filename.lower()
        if lower.endswith(".mp4"):
            return "video/mp4"
        if lower.endswith(".webm"):
            return "video/webm"
        if lower.endswith(".gif"):
            return "image/gif"
        if lower.endswith(".png"):
            return "image/png"
        if lower.endswith((".jpg", ".jpeg")):
            return "image/jpeg"
        return "application/octet-stream"
