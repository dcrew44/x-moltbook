import asyncio
import logging
from typing import Optional

import httpx

from app.config import get_settings
from app.core.exceptions import AuthenticationError, MoltbookError
from app.schemas.auth import MoltbookAgent

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_RETRIES = 2
RETRY_BACKOFF = [0.5, 1.0]


class MoltbookClient:
    """HTTP client for Moltbook API verification."""

    def __init__(self):
        self.base_url = settings.moltbook_api_url.rstrip("/")
        self.app_key = settings.moltbook_app_key

    async def verify_identity_token(self, identity_token: str) -> tuple[MoltbookAgent, dict]:
        """
        Verify a Moltbook identity token.

        Returns:
            Tuple of (MoltbookAgent, raw_response_data)

        Raises:
            AuthenticationError: If the token is invalid
            MoltbookError: If Moltbook API is unavailable
        """
        url = f"{self.base_url}/agents/verify-identity"
        headers = {
            "X-Moltbook-App-Key": self.app_key,
            "X-Moltbook-Identity": identity_token,
            "Content-Type": "application/json",
        }

        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(10.0, connect=5.0),
                    follow_redirects=False,
                ) as client:
                    response = await client.post(url, headers=headers, json={})

                    if response.status_code == 200:
                        data = response.json()
                        agent_data = data.get("agent", data)
                        agent = MoltbookAgent(
                            id=agent_data["id"],
                            name=agent_data["name"],
                            karma=agent_data.get("karma", 0),
                            verified=agent_data.get("verified", False),
                        )
                        return agent, data

                    if response.status_code == 401:
                        raise AuthenticationError(
                            message="Invalid or expired Moltbook identity token",
                            code="INVALID_MOLTBOOK_TOKEN",
                            hint="Generate a new identity token from Moltbook",
                        )

                    if response.status_code == 403:
                        raise AuthenticationError(
                            message="Moltbook app key is invalid",
                            code="INVALID_APP_KEY",
                        )

                    # Retry on 5xx errors
                    if response.status_code >= 500:
                        last_error = MoltbookError(
                            message=f"Moltbook API returned {response.status_code}",
                            code="MOLTBOOK_SERVER_ERROR",
                        )
                        if attempt < MAX_RETRIES:
                            await asyncio.sleep(RETRY_BACKOFF[attempt])
                            continue
                        raise last_error

                    # Other client errors
                    raise MoltbookError(
                        message=f"Moltbook API error: {response.status_code}",
                        code="MOLTBOOK_CLIENT_ERROR",
                    )

            except httpx.TimeoutException:
                last_error = MoltbookError(
                    message="Moltbook API request timed out",
                    code="MOLTBOOK_TIMEOUT",
                    hint="Try again later",
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF[attempt])
                    continue

            except httpx.RequestError as e:
                last_error = MoltbookError(
                    message=f"Failed to connect to Moltbook API: {e}",
                    code="MOLTBOOK_CONNECTION_ERROR",
                    hint="Check network connectivity",
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF[attempt])
                    continue

        if last_error:
            raise last_error

        raise MoltbookError(
            message="Unknown error verifying Moltbook token",
            code="MOLTBOOK_UNKNOWN_ERROR",
        )


moltbook_client = MoltbookClient()
