"""Thin HTTP wrapper around the Supabase REST API.

Uses requests.Session for connection pooling (TCP reuse) and
pre-configures auth headers so callers don't repeat boilerplate.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import requests

from infrastructure.config import Settings

logger = logging.getLogger(__name__)


class SupabaseClient:
    """Low-level Supabase HTTP client with session reuse."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = f"{settings.supabase_url}/rest/v1"
        self._session = requests.Session()
        self._session.headers.update(
            {
                "apikey": settings.supabase_api_key,
                "Authorization": f"Bearer {settings.supabase_api_key}",
            }
        )
        self._timeout = 30

    # -- helpers -------------------------------------------------------------

    def get(
        self, table: str, query: str = "", timeout: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """GET rows from *table* with an optional PostgREST query string."""
        url = f"{self._base_url}/{table}"
        if query:
            url = f"{url}?{query}"

        resp = self._session.get(url, timeout=timeout or self._timeout)
        resp.raise_for_status()
        return resp.json()

    def post(
        self, table: str, data: Any, timeout: Optional[int] = None
    ) -> requests.Response:
        """POST (insert) *data* into *table*."""
        url = f"{self._base_url}/{table}"
        headers = {
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        resp = self._session.post(
            url, json=data, headers=headers, timeout=timeout or self._timeout
        )
        return resp

    def patch(
        self, table: str, query: str, data: Any, timeout: Optional[int] = None
    ) -> requests.Response:
        """PATCH (update) rows in *table* matching *query*."""
        url = f"{self._base_url}/{table}?{query}"
        headers = {"Content-Type": "application/json"}
        resp = self._session.patch(
            url, json=data, headers=headers, timeout=timeout or self._timeout
        )
        return resp
