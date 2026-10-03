"""
This module defines the Post Highlight command.
"""

from typing import Optional

from src.command.command import Command, Priority
from src.config.teams import is_team_filtered
from src.data.highlight import Highlight
from src.logger import log
from src.output import output

# pylint: disable=too-few-public-methods
class PostHighlight(Command):
    """
    This class defines the Post Highlight command.
    """

    def __init__(self, highlight : Highlight):
        self.highlight : Highlight = highlight
        super().__init__("Post Highlight", Priority.NORMAL)


    def execute(self) -> None:
        """
        Execute the command.
        """
        self.highlight.is_pending = True

        try:
            scoring_abbrev = getattr(self.highlight, "team_abbrev", None)
            if scoring_abbrev is None and self.highlight.event is not None:
                scoring_abbrev = getattr(self.highlight.event, "team_abbrev", None)

            if not is_team_filtered(scoring_abbrev):
                log.info(
                    "Skipping highlight "
                    + str(self.highlight.id)
                    + " — scoring team "
                    + str(scoring_abbrev)
                    + " is not in FILTER_TEAMS"
                )
                self.highlight.post_id = {"_filtered": None}
                return

            text    : Optional[str] = self.highlight.get_post()
            footer  : Optional[str] = self.highlight.get_footer()

            if text is None:
                log.error(
                    "Could not post highlight "
                    + str(self.highlight.id)
                    + " - no post text."
                )
                self.highlight.post_id = {}
                return

            if footer is None:
                log.error(
                    "Could not post highlight "
                    + str(self.highlight.id)
                    + " - no footer text"
                )
                self.highlight.post_id = {}
                return

            # Prefer a shareable NHL video link in the message. This avoids slow/fragile
            # mp4 downloads that were causing missed posts.
            video_link = self.highlight.video
            if video_link and video_link not in text:
                text = text.rstrip() + "\n" + video_link

            log.info(
                "Posting highlight "
                + str(self.highlight.id)
                + " team="
                + str(scoring_abbrev)
                + " text_chars="
                + str(len(text))
            )

            duplicate_status = output.has_posted_today(text)
            all_outputs_duplicate = len(duplicate_status) > 0 and all(duplicate_status.values())
            any_output_duplicate = any(duplicate_status.values())

            # Text-only post (link included). Fast and reliable for Discord webhooks.
            result = output.post(text)

            if any(post_id is not None for post_id in result.values()):
                log.info(
                    "Highlight "
                    + str(self.highlight.id)
                    + " posted: "
                    + str(result)
                )
                self.highlight.post_id = result
                return

            if all_outputs_duplicate or any_output_duplicate:
                log.info(
                    "Highlight "
                    + str(self.highlight.id)
                    + " treated as duplicate for today."
                )
                terminal_duplicate_result = dict(result)
                terminal_duplicate_result["_duplicate"] = None
                self.highlight.post_id = terminal_duplicate_result
                return

            log.error(
                "Highlight "
                + str(self.highlight.id)
                + " failed to post (no successful outputs)."
            )
            self.highlight.post_id = {}
        finally:
            self.highlight.is_pending = False
