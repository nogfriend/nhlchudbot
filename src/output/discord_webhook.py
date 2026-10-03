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
REQUEST_TIMEOUT = 60

# Discord free-tier webhook attachment limit is often ~8–25 MB depending on server boosts.
# Stay under 8 MB to be safe on most servers.
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024


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
            # Log a redacted form so you can confirm it loaded without leaking the secret
            redacted = self.webhook_url[:40] + "..." if len(self.webhook_url) > 40 else self.webhook_url
            log.info("Discord webhook configured: " + redacted)

    def name(self) -> str:
        """Return the name of this outputter."""
        return "discord"

    def post(self, text: str) -> Optional[Dict[str, str]]:
        """Send a post with the specified text."""
        return self._send(text=text, media=None)

    def reply(self, parent: Optional[Dict[str, str]], text: str) -> Optional[Dict[str, str]]:
        """Send a reply as a normal webhook message (webhooks cannot true-reply without a bot)."""
        return self._send(text=text, media=None)

    def post_with_media(self, text: str, media: str) -> Optional[Dict[str, str]]:
        """Send a post with text and optional media. Falls back to text + link if upload fails."""
        return self._send(text=text, media=media)

    def reply_with_media(
        self,
        parent: Optional[Dict[str, str]],
        text: str,
        media: str,
    ) -> Optional[Dict[str, str]]:
        """Send a reply with media; falls back to text if upload fails."""
        return self._send(text=text, media=media)

    def _send(self, text: str, media: Optional[str]) -> Optional[Dict[str, str]]:
        if not self.webhook_url:
            log.error("Discord webhook URL missing; cannot post.")
            return None

        content = (text or "").strip()
        if len(content) > MAX_LENGTH:
            content = content[: MAX_LENGTH - 3] + "..."

        # Prefer attaching a local file when available and small enough
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
                    "posting text with link instead."
                )
                content = self._append_media_link(content, media)
            else:
                local_file = media
        elif media:
            # Remote URL or missing file — put the link in the message
            if media.startswith("http://") or media.startswith("https://"):
                content = self._append_media_link(content, media)
            else:
                log.warning("Discord - media path not found: " + str(media))

        for attempt in range(1, DISCORD_POST_ATTEMPTS + 1):
            try:
                if local_file:
                    post_id = self._post_with_file(content, local_file)
                    if post_id is None:
                        # Upload failed (size limit, etc.) — fall back to text only
                        log.warning(
                            "Discord - file upload failed; falling back to text-only post."
                        )
                        # Include original media path/url if we have it
                        fallback = self._append_media_link(content, media or local_file)
                        post_id = self._post_text(fallback)
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

    @staticmethod
    def _append_media_link(content: str, media: str) -> str:
        """Append a media URL to the message if it fits and is not already present."""
        if not media:
            return content
        link = media if (media.startswith("http://") or media.startswith("https://")) else ""
        if not link:
            return content
        if link in content:
            return content
        extra = "\n" + link
        if len(content) + len(extra) <= MAX_LENGTH:
            return content + extra
        return content

    def _post_text(self, content: str) -> Optional[Dict[str, str]]:
        """POST JSON content to the webhook."""
        url = self._webhook_url_with_wait()
        payload = {"content": content}
        log.info("Discord - sending text post (" + str(len(content)) + " chars)")
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        return self._handle_response(response)

    def _post_with_file(self, content: str, media_path: str) -> Optional[Dict[str, str]]:
        """POST multipart form with content + file attachment."""
        url = self._webhook_url_with_wait()
        filename = os.path.basename(media_path) or "highlight.mp4"
        log.info("Discord - sending post with file: " + filename)

        with open(media_path, "rb") as file_handle:
            files = {
                "files[0]": (filename, file_handle, self._guess_content_type(filename)),
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
        """Append wait=true so the API returns the created message object."""
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
