"""Content conversion helpers between Confluence storage format and local Markdown."""

from __future__ import annotations

from markdownify import markdownify as to_markdown
from markdown_it import MarkdownIt


class ContentConverter:
    """Translate between Confluence storage representation and Markdown."""

    def __init__(self) -> None:
        self._markdown = MarkdownIt("commonmark", {"html": True})

    def storage_to_markdown(self, storage: str) -> str:
        return to_markdown(storage, heading_style="ATX", strong_em_symbol="**")

    def markdown_to_storage(self, markdown: str) -> str:
        return self._markdown.render(markdown)
