import time
from dataclasses import dataclass


@dataclass
class Session:
    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: float = 0
    user: dict | None = None

    def update(self, data):
        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        self.expires_at = time.monotonic() + float(data["expires_in"])
        self.user = data.get("user")

    @property
    def needs_refresh(self):
        return self.access_token is not None and time.monotonic() >= self.expires_at - 30

    def clear(self):
        self.access_token = self.refresh_token = self.user = None
        self.expires_at = 0
