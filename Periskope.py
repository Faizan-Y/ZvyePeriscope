import logging
import os

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class Periskope:

    def __init__(self):
        self.api_key = os.getenv("PERISKOPE_API_KEY")
        self.phone = os.getenv("PERISKOPE_PHONE")

        # A request without a timeout can hang the whole single-threaded
        # scheduler, so every call is bounded. Invalid values fall back to 30s.
        try:
            self.timeout = max(1, int(os.getenv("PERISKOPE_TIMEOUT_SECONDS", "30")))
        except ValueError:
            logger.warning("Invalid PERISKOPE_TIMEOUT_SECONDS; using the default 30s timeout")
            self.timeout = 30

        self.base_url = "https://api.periskope.app/v1"

        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "x-phone": self.phone,
        }

        logger.info("Periskope initialized")
        logger.debug("Phone: %s", self.phone)

    def send_text(self, chat_id, message):
        logger.debug("Sending text message...")
        logger.debug("Chat ID: %s", chat_id)
        logger.debug("Message: %s", message)

        data = {
            "chat_id": chat_id,
            "message": message,
        }

        response = requests.post(
            f"{self.base_url}/message/send",
            headers=self.headers,
            json=data,
            timeout=self.timeout,
        )

        logger.debug("Status: %s", response.status_code)
        logger.debug("Response: %s", response.text)

        return response

    def send_media(self, chat_id, media_url, media_type, caption=None, filename=None):
        logger.debug("Sending media...")
        logger.debug("Chat ID: %s", chat_id)
        logger.debug("Media URL: %s", media_url)
        logger.debug("Media Type: %s", media_type)
        logger.debug("Caption: %s", caption)

        data = {
            "chat_id": chat_id,
            "message": caption or "",
            "media": {
                "url": media_url,
                "type": media_type,
            }
        }

        if filename:
            data["media"]["filename"] = filename

        response = requests.post(
            f"{self.base_url}/message/send",
            headers=self.headers,
            json=data,
            timeout=self.timeout,
        )

        logger.debug("Status: %s", response.status_code)
        logger.debug("Response: %s", response.text)

        return response