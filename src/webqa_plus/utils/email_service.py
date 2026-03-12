"""Dynamic email inbox service for verification-flow testing."""

import random
import re
import string
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiohttp


@dataclass
class InboxDetails:
    """Provisioned inbox details."""

    address: str
    login: str
    domain: str


class DynamicEmailService:
    """Public temp-inbox client with polling and verification extraction."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        self.provider = str(config.get("provider", "1secmail")).lower()
        self.base_url = str(config.get("base_url", "https://www.1secmail.com/api/v1/"))
        self.request_timeout = float(config.get("request_timeout_seconds", 12.0))

    async def provision_inbox(self) -> Optional[InboxDetails]:
        """Create a dynamic inbox address."""
        if self.provider != "1secmail":
            return None

        params = {"action": "genRandomMailbox", "count": 1}
        payload = await self._request_json(params)
        if not isinstance(payload, list) or not payload:
            return None

        address = str(payload[0]).strip()
        if "@" not in address:
            return None

        login, domain = address.split("@", 1)
        return InboxDetails(address=address, login=login, domain=domain)

    async def poll_for_verification(
        self,
        inbox: InboxDetails,
        timeout_seconds: int = 120,
        interval_seconds: int = 5,
    ) -> Optional[Dict[str, str]]:
        """Poll inbox and extract verification link/code from newest message."""
        elapsed = 0
        checked_ids: set[int] = set()

        while elapsed <= max(0, timeout_seconds):
            messages = await self._list_messages(inbox)
            for message in messages:
                msg_id = int(message.get("id", 0) or 0)
                if msg_id <= 0 or msg_id in checked_ids:
                    continue
                checked_ids.add(msg_id)

                full_message = await self._read_message(inbox, msg_id)
                if not full_message:
                    continue

                parsed = self._extract_verification_data(full_message)
                if parsed:
                    return parsed

            if elapsed >= timeout_seconds:
                break

            await asyncio_sleep(interval_seconds)
            elapsed += interval_seconds

        return None

    async def _list_messages(self, inbox: InboxDetails) -> List[Dict[str, Any]]:
        params = {
            "action": "getMessages",
            "login": inbox.login,
            "domain": inbox.domain,
        }
        payload = await self._request_json(params)
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    async def _read_message(self, inbox: InboxDetails, message_id: int) -> Optional[Dict[str, Any]]:
        params = {
            "action": "readMessage",
            "login": inbox.login,
            "domain": inbox.domain,
            "id": str(message_id),
        }
        payload = await self._request_json(params)
        if isinstance(payload, dict):
            return payload
        return None

    async def _request_json(self, params: Dict[str, str]) -> Any:
        timeout = aiohttp.ClientTimeout(total=self.request_timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(self.base_url, params=params) as response:
                if response.status >= 400:
                    return None
                return await response.json(content_type=None)

    def _extract_verification_data(self, message: Dict[str, Any]) -> Optional[Dict[str, str]]:
        body_text = " ".join(
            [
                str(message.get("subject", "")),
                str(message.get("textBody", "")),
                str(message.get("htmlBody", "")),
                str(message.get("body", "")),
            ]
        )
        if not body_text.strip():
            return None

        url_match = re.search(r"https?://[^\s'\"<>]+", body_text)
        code_match = re.search(r"\b(\d{4,8})\b", body_text)

        if not url_match and not code_match:
            return None

        return {
            "subject": str(message.get("subject", "")).strip(),
            "from": str(message.get("from", "")).strip(),
            "link": url_match.group(0).strip() if url_match else "",
            "code": code_match.group(1).strip() if code_match else "",
        }


def generate_fallback_identity() -> Dict[str, str]:
    """Generate fallback deterministic test identity."""
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return {
        "email": f"webqa+{suffix}@example.test",
        "password": f"WebQA!{suffix}A1",
        "first_name": "WebQA",
        "last_name": "Tester",
        "full_name": "WebQA Tester",
        "phone": "5551234567",
    }


async def asyncio_sleep(seconds: int) -> None:
    """Isolated sleep helper for async polling."""
    import asyncio

    await asyncio.sleep(max(0, seconds))
