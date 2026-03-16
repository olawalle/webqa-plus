"""Dynamic email inbox service for verification-flow testing."""

import random
import re
import ssl
import string
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiohttp
import certifi


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
        self.provider = str(config.get("provider", "guerrillamail")).lower()
        self.base_url = str(config.get("base_url", ""))
        self.request_timeout = float(config.get("request_timeout_seconds", 12.0))
        # Guerrilla Mail session state
        self._gm_sid: Optional[str] = None
        self._gm_seq: int = 0

    def _ssl_ctx(self) -> ssl.SSLContext:
        return ssl.create_default_context(cafile=certifi.where())

    def _connector(self) -> aiohttp.TCPConnector:
        return aiohttp.TCPConnector(ssl=self._ssl_ctx())

    async def provision_inbox(self) -> Optional[InboxDetails]:
        """Create a dynamic inbox address."""
        if self.provider == "guerrillamail":
            return await self._gm_provision()
        if self.provider == "1secmail":
            result = await self._1sec_provision()
            if result:
                return result
        # Fallback to guerrillamail if 1secmail fails
        self.provider = "guerrillamail"
        return await self._gm_provision()

    # ── Guerrilla Mail ──────────────────────────────────────────

    async def _gm_provision(self) -> Optional[InboxDetails]:
        data = await self._gm_request({"f": "get_email_address"})
        if not data or "email_addr" not in data:
            return None
        self._gm_sid = data.get("sid_token")
        address = data["email_addr"]
        login, domain = address.split("@", 1) if "@" in address else (address, "")
        return InboxDetails(address=address, login=login, domain=domain)

    async def _gm_list_messages(self) -> List[Dict[str, Any]]:
        data = await self._gm_request({
            "f": "check_email",
            "sid_token": self._gm_sid or "",
            "seq": str(self._gm_seq),
        })
        if not data or "list" not in data:
            return []
        msgs = data["list"]
        return [m for m in msgs if isinstance(m, dict)]

    async def _gm_read_message(self, mail_id: int) -> Optional[Dict[str, Any]]:
        data = await self._gm_request({
            "f": "fetch_email",
            "sid_token": self._gm_sid or "",
            "email_id": str(mail_id),
        })
        if not data:
            return None
        # Normalize to common format
        return {
            "id": mail_id,
            "subject": data.get("mail_subject", ""),
            "from": data.get("mail_from", ""),
            "textBody": data.get("mail_body", ""),
            "htmlBody": data.get("mail_body", ""),
            "body": data.get("mail_body", ""),
        }

    async def _gm_request(self, params: Dict[str, str]) -> Any:
        timeout = aiohttp.ClientTimeout(total=self.request_timeout)
        async with aiohttp.ClientSession(timeout=timeout, connector=self._connector()) as session:
            async with session.get(
                "https://api.guerrillamail.com/ajax.php",
                params=params,
            ) as response:
                if response.status >= 400:
                    return None
                return await response.json(content_type=None)

    # ── 1secmail ────────────────────────────────────────────────

    async def _1sec_provision(self) -> Optional[InboxDetails]:
        base = self.base_url or "https://www.1secmail.com/api/v1/"
        params = {"action": "genRandomMailbox", "count": 1}
        payload = await self._1sec_request(base, params)
        if not isinstance(payload, list) or not payload:
            return None
        address = str(payload[0]).strip()
        if "@" not in address:
            return None
        login, domain = address.split("@", 1)
        return InboxDetails(address=address, login=login, domain=domain)

    async def _1sec_request(self, base_url: str, params: Dict[str, str]) -> Any:
        timeout = aiohttp.ClientTimeout(total=self.request_timeout)
        async with aiohttp.ClientSession(timeout=timeout, connector=self._connector()) as session:
            async with session.get(base_url, params=params) as response:
                if response.status >= 400:
                    return None
                return await response.json(content_type=None)

    # ── Shared polling ──────────────────────────────────────────

    async def poll_for_verification(
        self,
        inbox: InboxDetails,
        timeout_seconds: int = 120,
        interval_seconds: int = 5,
    ) -> Optional[Dict[str, str]]:
        """Poll inbox and extract verification link/code from newest message."""
        elapsed = 0
        checked_ids: set[int] = set()
        # Skip the welcome message from guerrillamail
        if self.provider == "guerrillamail":
            first_msgs = await self._gm_list_messages()
            for m in first_msgs:
                checked_ids.add(int(m.get("mail_id", 0) or 0))

        while elapsed <= max(0, timeout_seconds):
            messages = await self._list_messages(inbox)
            for message in messages:
                id_key = "mail_id" if self.provider == "guerrillamail" else "id"
                msg_id = int(message.get(id_key, 0) or 0)
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
        if self.provider == "guerrillamail":
            return await self._gm_list_messages()
        base = self.base_url or "https://www.1secmail.com/api/v1/"
        params = {
            "action": "getMessages",
            "login": inbox.login,
            "domain": inbox.domain,
        }
        payload = await self._1sec_request(base, params)
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    async def _read_message(self, inbox: InboxDetails, message_id: int) -> Optional[Dict[str, Any]]:
        if self.provider == "guerrillamail":
            return await self._gm_read_message(message_id)
        base = self.base_url or "https://www.1secmail.com/api/v1/"
        params = {
            "action": "readMessage",
            "login": inbox.login,
            "domain": inbox.domain,
            "id": str(message_id),
        }
        payload = await self._1sec_request(base, params)
        if isinstance(payload, dict):
            return payload
        return None

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
        "email": f"webqa.{suffix}@mailinator.com",
        "password": f"WebQA!{suffix}A1",
        "first_name": "WebQA",
        "last_name": "Tester",
        "full_name": "WebQA Tester",
        "phone": "3478901234",
        "company_name": f"WebQA Labs {suffix[:4].upper()}",
    }


async def asyncio_sleep(seconds: int) -> None:
    """Isolated sleep helper for async polling."""
    import asyncio

    await asyncio.sleep(max(0, seconds))
