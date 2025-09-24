"""Dataclasses representing the local Confluence content structure."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional


@dataclass(slots=True)
class LocalPageMetadata:
    """Metadata persisted in the frontmatter of a local page file."""

    title: str
    space_key: Optional[str] = None
    confluence_id: Optional[str] = None
    parent_id: Optional[str] = None
    version: Optional[int] = None
    representation: str = "storage"


@dataclass(slots=True)
class LocalPage:
    """Representation of a page stored on disk."""

    path: Path
    metadata: LocalPageMetadata
    body: str
    children: list["LocalPage"] = field(default_factory=list)

    @property
    def title(self) -> str:
        return self.metadata.title

    @property
    def confluence_id(self) -> Optional[str]:
        return self.metadata.confluence_id

    @property
    def directory(self) -> Path:
        return self.path.parent

    def iter_subtree(self) -> Iterable["LocalPage"]:
        """Yield the page and all descendants in depth-first order."""

        yield self
        for child in self.children:
            yield from child.iter_subtree()
