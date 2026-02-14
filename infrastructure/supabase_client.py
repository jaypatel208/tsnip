"""Thin HTTP wrapper around the Supabase REST API.

Uses requests.Session for connection pooling (TCP reuse) and
pre-configures auth headers so callers don't repeat boilerplate.
"""

from __future__ import annotations

from typing import Any, Optional

import requests
from loguru import logger

from infrastructure.config import Settings


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
        logger.debug("SupabaseClient initialized (base_url={})", self._base_url)

    # -- helpers -------------------------------------------------------------

    def get(
        self, table: str, query: str = "", timeout: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """GET rows from *table* with an optional PostgREST query string."""
        url = f"{self._base_url}/{table}"
        if query:
            url = f"{url}?{query}"

        logger.debug("Supabase GET {}", url)
        try:
            resp = self._session.get(url, timeout=timeout or self._timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.Timeout:
            logger.error(
                "Supabase GET timeout — table={}, timeout={}s",
                table,
                timeout or self._timeout,
            )
            raise
        except requests.HTTPError as exc:
            logger.error(
                "Supabase GET failed — table={}, status={}, body={}",
                table,
                exc.response.status_code if exc.response is not None else "?",
                exc.response.text[:200] if exc.response is not None else "?",
            )
            raise
        except requests.ConnectionError:
            logger.error("Supabase connection error — table={}", table)
            raise

    def post(
        self, table: str, data: Any, timeout: Optional[int] = None
    ) -> requests.Response:
        """POST (insert) *data* into *table*."""
        url = f"{self._base_url}/{table}"
        headers = {
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        logger.debug(
            "Supabase POST {} ({} record(s))",
            table,
            len(data) if isinstance(data, list) else 1,
        )
        try:
            resp = self._session.post(
                url, json=data, headers=headers, timeout=timeout or self._timeout
            )
            return resp
        except requests.Timeout:
            logger.error("Supabase POST timeout — table={}", table)
            raise
        except requests.ConnectionError:
            logger.error("Supabase POST connection error — table={}", table)
            raise

    def patch(
        self, table: str, query: str, data: Any, timeout: Optional[int] = None
    ) -> requests.Response:
        """PATCH (update) rows in *table* matching *query*."""
        url = f"{self._base_url}/{table}?{query}"
        headers = {"Content-Type": "application/json"}
        logger.debug("Supabase PATCH {} where {}", table, query)
        try:
            resp = self._session.patch(
                url, json=data, headers=headers, timeout=timeout or self._timeout
            )
            return resp
        except requests.Timeout:
            logger.error("Supabase PATCH timeout — table={}, query={}", table, query)
            raise
        except requests.ConnectionError:
            logger.error("Supabase PATCH connection error — table={}", table)
            raise
