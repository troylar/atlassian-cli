"""Typed models for Confluence content interactions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional


@dataclass(slots=True)
class PageBody:
    """Representation of page content in different formats."""

    storage: str
    representation: str = "storage"


@dataclass(slots=True)
class PageSummary:
    """Minimal Confluence page description used for traversal."""

    id: str
    title: str
    space_key: str
    parent_id: Optional[str]
    version: int


@dataclass(slots=True)
class PageTreeNode(PageSummary):
    """Page summary with nested children."""

    children: list[PageSummary] = field(default_factory=list)


@dataclass(slots=True)
class PageContent(PageSummary):
    """Full Confluence page payload."""

    body: PageBody
    ancestors: list[PageSummary] = field(default_factory=list)

    @property
    def path_titles(self) -> list[str]:
        """Return titles from root ancestor (exclusive) to the page."""

        return [ancestor.title for ancestor in self.ancestors] + [self.title]

    def with_children(self, children: Iterable[PageSummary]) -> "PageTreeNode":
        return PageTreeNode(
            id=self.id,
            title=self.title,
            space_key=self.space_key,
            parent_id=self.parent_id,
            version=self.version,
            children=list(children),
        )
