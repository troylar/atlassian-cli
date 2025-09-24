"""Local filesystem repository of Confluence pages."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Optional

import frontmatter

from .models import LocalPage, LocalPageMetadata
from .naming import slugify

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from atlassian_cli.confluence.models import PageContent
    from atlassian_cli.sync.converters import ContentConverter


PAGE_FILENAME = "page.md"


class LocalRepository:
    """Persist Confluence content as Markdown files with YAML frontmatter."""

    def __init__(self, root: Path, *, converter: "ContentConverter") -> None:
        self.root = root
        self.converter = converter
        self._slug_usage: dict[Path, set[str]] = defaultdict(set)
        if self.root.exists():
            self._register_existing_slugs(self.root)

    # ------------------------------------------------------------------
    # Download helpers (remote -> disk)
    # ------------------------------------------------------------------
    def write_tree(
        self,
        root_page: "PageContent",
        descendants: Iterable["PageContent"],
    ) -> None:
        """Persist a full Confluence page tree to the local repository."""

        self.root.mkdir(parents=True, exist_ok=True)

        id_to_directory: dict[str, Path] = {}
        existing_directories = self._collect_existing_directories()

        id_to_directory[root_page.id] = self.root
        self._dump_page(self.root / PAGE_FILENAME, root_page)

        for page in descendants:
            parent_dir = id_to_directory.get(page.parent_id)
            if not parent_dir:
                parent_dir = existing_directories.get(page.parent_id)
            if parent_dir is None:
                raise RuntimeError(
                    f"Cannot locate local directory for parent page id {page.parent_id!r}"
                )

            directory = existing_directories.get(page.id)
            if directory is None:
                directory = self._allocate_child_directory(parent_dir, page.title)
            id_to_directory[page.id] = directory
            self._dump_page(directory / PAGE_FILENAME, page)

    def _dump_page(self, file_path: Path, page: "PageContent") -> None:
        metadata = {
            "title": page.title,
            "space_key": page.space_key,
            "confluence_id": page.id,
            "parent_id": page.parent_id,
            "version": page.version,
            "representation": page.body.representation,
        }
        body = self.converter.storage_to_markdown(page.body.storage)
        post = frontmatter.Post(body)
        post.metadata.update(metadata)
        with file_path.open("w", encoding="utf-8") as handle:
            frontmatter.dump(post, handle)

    def _allocate_child_directory(self, parent_directory: Path, title: str) -> Path:
        slug = self._unique_slug(title, parent_directory)
        directory = parent_directory / slug
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    # ------------------------------------------------------------------
    # Upload helpers (disk -> models)
    # ------------------------------------------------------------------
    def read_tree(self) -> LocalPage:
        """Load all local pages from disk into memory."""

        page_file = self.root / PAGE_FILENAME
        if not page_file.exists():
            raise FileNotFoundError(f"Missing {PAGE_FILENAME!r} in repository root {self.root}")
        return self._read_directory(self.root)

    def _read_directory(self, directory: Path) -> LocalPage:
        page_file = directory / PAGE_FILENAME
        post = frontmatter.load(page_file)
        metadata = LocalPageMetadata(
            title=post.metadata.get("title", directory.name),
            space_key=post.metadata.get("space_key"),
            confluence_id=_as_optional_str(post.metadata.get("confluence_id")),
            parent_id=_as_optional_str(post.metadata.get("parent_id")),
            version=_as_optional_int(post.metadata.get("version")),
            representation=post.metadata.get("representation", "storage"),
        )
        page = LocalPage(path=page_file, metadata=metadata, body=post.content)
        for child in self.iter_page_directories(directory):
            page.children.append(self._read_directory(child))
        return page

    def save_page(self, page: LocalPage) -> None:
        """Persist modifications made to a local page."""

        post = frontmatter.Post(page.body)
        post.metadata.update(
            {
                "title": page.metadata.title,
                "space_key": page.metadata.space_key,
                "confluence_id": page.metadata.confluence_id,
                "parent_id": page.metadata.parent_id,
                "version": page.metadata.version,
                "representation": page.metadata.representation,
            }
        )
        with page.path.open("w", encoding="utf-8") as handle:
            frontmatter.dump(post, handle)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def iter_page_directories(self, parent: Path) -> Iterable[Path]:
        for candidate in sorted(parent.iterdir()):
            if candidate.is_dir():
                yield candidate

    def _register_existing_slugs(self, directory: Path) -> None:
        for child in directory.iterdir():
            if child.is_dir():
                self._slug_usage[directory].add(child.name)
                self._register_existing_slugs(child)

    def _unique_slug(self, title: str, parent: Path) -> str:
        base = slugify(title)
        slug = base
        counter = 2
        used = self._slug_usage[parent]
        while slug in used:
            slug = f"{base}-{counter}"
            counter += 1
        used.add(slug)
        return slug

    def resolve_page_directory(self, raw_path: Path) -> Path:
        base = self.root.resolve()
        candidate = raw_path if raw_path.is_absolute() else base / raw_path
        candidate = candidate.resolve()
        if not str(candidate).startswith(str(base)):
            raise ValueError(f"Path {raw_path} is outside of repository root {self.root}")
        if not candidate.exists():
            raise FileNotFoundError(f"Path {candidate} does not exist")
        directory = candidate if candidate.is_dir() else candidate.parent
        page_file = directory / PAGE_FILENAME
        if not page_file.exists():
            raise FileNotFoundError(f"No {PAGE_FILENAME} found in {directory}")
        return directory

    def build_directory_index(
        self, root: LocalPage
    ) -> tuple[dict[Path, LocalPage], dict[Path, Optional[Path]]]:
        mapping: dict[Path, LocalPage] = {}
        parents: dict[Path, Optional[Path]] = {}

        def _walk(page: LocalPage, parent_dir: Optional[Path]) -> None:
            directory = page.directory.resolve()
            mapping[directory] = page
            parents[directory] = parent_dir
            for child in page.children:
                _walk(child, directory)

        _walk(root, None)
        return mapping, parents

    def _collect_existing_directories(self) -> dict[str, Path]:
        if not (self.root / PAGE_FILENAME).exists():
            return {}

        mapping: dict[str, Path] = {}

        def _walk(directory: Path) -> None:
            page_file = directory / PAGE_FILENAME
            if not page_file.exists():
                return
            post = frontmatter.load(page_file)
            page_id = post.metadata.get("confluence_id")
            if page_id:
                mapping[str(page_id)] = directory
            for child in directory.iterdir():
                if child.is_dir():
                    _walk(child)

        _walk(self.root)
        return mapping


def _as_optional_str(value: object) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _as_optional_int(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

