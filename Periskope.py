import os
import requests
from dotenv import load_dotenv

load_dotenv()


class Periskope:

    def __init__(self):
        self.api_key = os.getenv("PERISKOPE_API_KEY")
        self.phone = os.getenv("PERISKOPE_PHONE")

        self.base_url = "https://api.periskope.app/v1"

        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "x-phone": self.phone,
        }

        print("Periskope initialized")
        print("Phone:", self.phone)

    def send_text(self, chat_id, message):
        print("\nSending text message...")
        print("Chat ID:", chat_id)
        print("Message:", message)

        data = {
            "chat_id": chat_id,
            "message": message,
        }

        response = requests.post(
            f"{self.base_url}/message/send",
            headers=self.headers,
            json=data,
        )

        print("Status:", response.status_code)
        print("Response:", response.text)

        return response

    def send_media(self, chat_id, media_url, media_type, caption=None, filename=None):
        print("\nSending media...")
        print("Chat ID:", chat_id)
        print("Media URL:", media_url)
        print("Media Type:", media_type)
        print("Caption:", caption)

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
        )

        print("Status:", response.status_code)
        print("Response:", response.text)

        return response