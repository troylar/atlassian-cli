"""HTTP client wrapper for interacting with the Confluence REST API."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable, Iterator, Optional
from urllib.parse import urljoin

import httpx

from .models import PageBody, PageContent, PageSummary


DEFAULT_EXPAND_FIELDS = ("body.storage", "version", "ancestors", "space")


@dataclass(slots=True)
class ConfluenceAuth:
    """Authentication payload used by the Confluence client."""

    email: str
    api_token: str


class ConfluenceClient:
    """Thin wrapper above the Confluence REST API."""

    def __init__(
        self,
        *,
        base_url: str,
        auth: ConfluenceAuth,
        timeout: float = 30.0,
    ) -> None:
        api_root = urljoin(base_url.rstrip("/") + "/", "wiki/rest/api/")
        self._client = httpx.Client(base_url=api_root, timeout=timeout, auth=(auth.email, auth.api_token))

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ConfluenceClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: D401 - standard context manager signature
        self.close()

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------
    def _request(self, method: str, url: str, **kwargs) -> dict:
        response = self._client.request(method, url, **kwargs)
        response.raise_for_status()
        return response.json()

    def _iter_paginated(self, url: str, *, params: Optional[dict] = None) -> Iterator[dict]:
        next_url = url
        next_params = params
        while next_url:
            data = self._request("GET", next_url, params=next_params)
            for result in data.get("results", []):
                yield result
            next_link = data.get("_links", {}).get("next")
            if not next_link:
                break
            next_url = next_link
            next_params = None

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------
    @staticmethod
    def _to_page_summary(data: dict, *, parent_id: Optional[str] = None) -> PageSummary:
        space_key = data.get("space", {}).get("key")
        version_number = data.get("version", {}).get("number", 0)
        return PageSummary(
            id=str(data["id"]),
            title=data["title"],
            space_key=space_key or "",
            parent_id=parent_id,
            version=version_number,
        )

    @staticmethod
    def _to_page_content(data: dict) -> PageContent:
        ancestors_raw = data.get("ancestors", [])
        ancestors = [
            ConfluenceClient._to_page_summary(ancestor)
            for ancestor in ancestors_raw
        ]
        parent_id = ancestors[-1].id if ancestors else None
        body = data.get("body", {}).get("storage", {})
        space_key = data.get("space", {}).get("key", "")
        version_number = data.get("version", {}).get("number", 0)
        return PageContent(
            id=str(data["id"]),
            title=data["title"],
            space_key=space_key,
            parent_id=parent_id,
            version=version_number,
            body=PageBody(
                storage=body.get("value", ""),
                representation=body.get("representation", "storage"),
            ),
            ancestors=ancestors,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_page(self, page_id: str, *, expand: Iterable[str] = DEFAULT_EXPAND_FIELDS) -> PageContent:
        params = {"expand": ",".join(expand)} if expand else None
        data = self._request("GET", f"content/{page_id}", params=params)
        return self._to_page_content(data)

    def get_page_by_title(
        self,
        *,
        space_key: str,
        title: str,
        parent_id: Optional[str] = None,
        expand: Iterable[str] = DEFAULT_EXPAND_FIELDS,
    ) -> Optional[PageContent]:
        params: dict[str, object] = {
            "spaceKey": space_key,
            "title": title,
            "expand": ",".join(expand),
            "limit": 10,
        }
        if parent_id:
            params["ancestors"] = parent_id
        data = self._request("GET", "content", params=params)
        for result in data.get("results", []):
            # Ensure parent match if provided
            if parent_id:
                result_ancestors = result.get("ancestors", [])
                if not result_ancestors or str(result_ancestors[-1]["id"]) != str(parent_id):
                    continue
            return self._to_page_content(result)
        return None

    def get_child_pages(self, page_id: str) -> list[PageSummary]:
        children: list[PageSummary] = []
        for child in self._iter_paginated(
            f"content/{page_id}/child/page",
            params={"limit": 200, "expand": "version,space"},
        ):
            children.append(self._to_page_summary(child, parent_id=page_id))
        return children

    def iter_page_tree(self, root_page_id: str) -> Iterator[PageContent]:
        queue: deque[str] = deque([root_page_id])
        while queue:
            current = queue.popleft()
            page = self.get_page(current)
            yield page
            for child in self.get_child_pages(page.id):
                queue.append(child.id)

    def create_page(
        self,
        *,
        space_key: str,
        title: str,
        storage: str,
        parent_id: Optional[str] = None,
        representation: str = "storage",
    ) -> PageContent:
        payload: dict[str, object] = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {"storage": {"value": storage, "representation": representation}},
        }
        if parent_id:
            payload["ancestors"] = [{"id": str(parent_id)}]
        data = self._request("POST", "content", json=payload)
        return self._to_page_content(data)

    def update_page(
        self,
        *,
        page_id: str,
        title: str,
        space_key: str,
        storage: str,
        current_version: int,
        parent_id: Optional[str] = None,
        representation: str = "storage",
    ) -> PageContent:
        payload: dict[str, object] = {
            "id": str(page_id),
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {"storage": {"value": storage, "representation": representation}},
            "version": {"number": current_version + 1},
        }
        if parent_id:
            payload["ancestors"] = [{"id": str(parent_id)}]
        data = self._request("PUT", f"content/{page_id}", json=payload)
        return self._to_page_content(data)

    def ensure_page(
        self,
        *,
        space_key: str,
        title: str,
        storage: str,
        parent_id: Optional[str],
        representation: str = "storage",
    ) -> PageContent:
        existing = self.get_page_by_title(space_key=space_key, title=title, parent_id=parent_id)
        if existing:
            return self.update_page(
                page_id=existing.id,
                title=title,
                space_key=space_key,
                storage=storage,
                current_version=existing.version,
                parent_id=parent_id or existing.parent_id,
                representation=representation,
            )
        return self.create_page(
            space_key=space_key,
            title=title,
            storage=storage,
            parent_id=parent_id,
            representation=representation,
        )

*** End of File
