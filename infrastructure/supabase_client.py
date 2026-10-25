"""Thin HTTP wrapper around the Supabase REST API.

Uses requests.Session for connection pooling (TCP reuse) and
pre-configures auth headers so callers don't repeat boilerplate.
Filters always go through `params`, so requests URL-encodes them and a
value can never add filters of its own.
"""

from __future__ import annotations

from typing import Any

import requests
from loguru import logger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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
        # Retry transient gateway errors. Not PATCH: a retried claim that
        # already went through would look lost and strand the stream.
        retry = Retry(
            total=2,
            backoff_factor=0.3,
            status_forcelist=[502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retry))
        self._timeout = 10
        logger.debug("SupabaseClient initialized (base_url={})", self._base_url)

    def get(self, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        """GET rows from *table* filtered by PostgREST *params*."""
        return self._call("GET", table, params=params).json()

    def patch(
        self, table: str, params: dict[str, str], data: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """PATCH rows of *table* matching *params*; returns the updated rows."""
        return self._call(
            "PATCH",
            table,
            params=params,
            json=data,
            headers={"Prefer": "return=representation"},
        ).json()

    def rpc(self, function: str, body: dict[str, Any]) -> Any:
        """Call a Postgres function."""
        return self._call("POST", f"rpc/{function}", json=body).json()

    def _call(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        logger.debug("Supabase {} {} {}", method, path, kwargs.get("params", ""))
        try:
            resp = self._session.request(
                method, f"{self._base_url}/{path}", timeout=self._timeout, **kwargs
            )
        except requests.RequestException as exc:
            logger.error("Supabase {} {} — {}", method, path, type(exc).__name__)
            raise
        if not resp.ok:
            logger.error(
                "Supabase {} {} failed — status={}, body={}",
                method,
                path,
                resp.status_code,
                resp.text[:200],
            )
        resp.raise_for_status()
        return resp
