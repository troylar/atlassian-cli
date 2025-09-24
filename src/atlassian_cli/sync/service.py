"""High-level synchronization workflows between Confluence and the local filesystem."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from atlassian_cli.confluence.client import ConfluenceAuth, ConfluenceClient
from atlassian_cli.confluence.models import PageContent
from atlassian_cli.local.models import LocalPage
from atlassian_cli.local.repository import LocalRepository


@dataclass(slots=True)
class SyncResult:
    """Report produced after a synchronization operation."""

    processed_pages: int
    created_pages: int = 0
    updated_pages: int = 0


class SyncService:
    """Coordinate synchronization flows between Confluence and the local filesystem."""

    def __init__(self, client: ConfluenceClient, repository: LocalRepository) -> None:
        self.client = client
        self.repository = repository

    # ------------------------------------------------------------------
    # Download (Confluence -> local)
    # ------------------------------------------------------------------
    def download_tree(
        self,
        *,
        root_page_id: Optional[str] = None,
        space_key: Optional[str] = None,
        root_title: Optional[str] = None,
        parent_page_id: Optional[str] = None,
    ) -> SyncResult:
        """Fetch a Confluence page tree and store it locally."""

        root_page = self._resolve_root_page(
            root_page_id=root_page_id,
            space_key=space_key,
            root_title=root_title,
            parent_page_id=parent_page_id,
        )
        if root_page is None:
            raise RuntimeError("Unable to locate root page from the provided parameters")

        iterator = self.client.iter_page_tree(root_page.id)
        root = next(iterator)
        descendants = list(iterator)
        self.repository.write_tree(root, descendants)
        return SyncResult(processed_pages=1 + len(descendants))

    # ------------------------------------------------------------------
    # Upload (local -> Confluence)
    # ------------------------------------------------------------------
    def upload_tree(
        self,
        *,
        space_key: str,
        parent_page_id: Optional[str] = None,
    ) -> SyncResult:
        """Push the local page tree to Confluence, creating or updating as needed."""

        local_root = self.repository.read_tree()
        # Prefer CLI-provided parent id, otherwise use metadata recorded on disk.
        resolved_parent = parent_page_id or local_root.metadata.parent_id

        created = 0
        updated = 0

        remote_root = self._ensure_remote_page(local_root, space_key, resolved_parent)
        if local_root.metadata.confluence_id == remote_root.id:
            if local_root.metadata.version and remote_root.version > local_root.metadata.version:
                updated += 1
        else:
            created += 1

        for child in local_root.children:
            res = self._upload_subtree(child, space_key, remote_root.id)
            created += res.created_pages
            updated += res.updated_pages

        processed = sum(1 for _ in local_root.iter_subtree())
        return SyncResult(processed_pages=processed, created_pages=created, updated_pages=updated)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _upload_subtree(
        self,
        page: LocalPage,
        space_key: str,
        parent_id: Optional[str],
    ) -> SyncResult:
        remote = self._ensure_remote_page(page, space_key, parent_id)
        created = 0
        updated = 0
        if page.metadata.version and remote.version > page.metadata.version:
            updated += 1
        elif not page.metadata.confluence_id:
            created += 1

        for child in page.children:
            child_result = self._upload_subtree(child, space_key, remote.id)
            created += child_result.created_pages
            updated += child_result.updated_pages

        return SyncResult(processed_pages=1, created_pages=created, updated_pages=updated)

    def _ensure_remote_page(
        self,
        local_page: LocalPage,
        space_key: str,
        parent_id: Optional[str],
    ) -> PageContent:
        converter = self.repository.converter
        storage = converter.markdown_to_storage(local_page.body)

        metadata = local_page.metadata
        parent_for_update = parent_id or metadata.parent_id

        if metadata.confluence_id:
            current_version = metadata.version
            if current_version is None:
                current_version = self.client.get_page(metadata.confluence_id).version
            remote = self.client.update_page(
                page_id=metadata.confluence_id,
                title=metadata.title,
                space_key=space_key,
                storage=storage,
                current_version=current_version,
                parent_id=parent_for_update,
                representation=metadata.representation,
            )
        else:
            remote = self.client.ensure_page(
                space_key=space_key,
                title=metadata.title,
                storage=storage,
                parent_id=parent_for_update,
                representation=metadata.representation,
            )

        metadata.confluence_id = remote.id
        metadata.version = remote.version
        metadata.space_key = remote.space_key or space_key
        metadata.parent_id = parent_for_update
        local_page.body = converter.storage_to_markdown(remote.body.storage)
        self.repository.save_page(local_page)
        return remote

    def _resolve_root_page(
        self,
        *,
        root_page_id: Optional[str],
        space_key: Optional[str],
        root_title: Optional[str],
        parent_page_id: Optional[str],
    ) -> Optional[PageContent]:
        if root_page_id:
            return self.client.get_page(root_page_id)

        if root_title and space_key:
            return self.client.get_page_by_title(
                space_key=space_key,
                title=root_title,
                parent_id=parent_page_id,
            )
        return None


def create_client(*, base_url: str, email: str, api_token: str) -> ConfluenceClient:
    auth = ConfluenceAuth(email=email, api_token=api_token)
    return ConfluenceClient(base_url=base_url, auth=auth)
