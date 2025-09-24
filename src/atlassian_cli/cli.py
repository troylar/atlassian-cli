"""Command-line interface for the Atlassian Confluence synchronization tool."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import frontmatter
import typer
from rich.console import Console
from rich.table import Table

from .config import AtlassianConfig, ensure_config
from .local.repository import LocalRepository
from .sync.converters import ContentConverter
from .sync.service import SyncResult, SyncService, create_client

app = typer.Typer(help="Synchronize Confluence spaces with local folders for Markdown editing.")
console = Console()


def _build_service(
    config: AtlassianConfig,
    *,
    workspace: Path,
) -> tuple[SyncService, callable]:
    workspace = workspace.resolve()
    converter = ContentConverter()
    repository = LocalRepository(workspace, converter=converter)
    client = create_client(
        base_url=str(config.credentials.base_url),
        email=config.credentials.email,
        api_token=config.credentials.api_token,
    )
    service = SyncService(client, repository)

    def _cleanup() -> None:
        client.close()

    return service, _cleanup


def _format_result(result: SyncResult, *, action: str) -> None:
    table = Table(title=f"Confluence {action.title()} Summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Processed pages", str(result.processed_pages))
    table.add_row("Created pages", str(result.created_pages))
    table.add_row("Updated pages", str(result.updated_pages))
    console.print(table)


@app.callback()
def main(
    ctx: typer.Context,
    config_path: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to a configuration TOML file",
    ),
) -> None:
    ctx.obj = {"config_path": config_path}


def _resolve_config(
    ctx: typer.Context,
    *,
    base_url: Optional[str],
    email: Optional[str],
    api_token: Optional[str],
    space_key: Optional[str],
    parent_page_id: Optional[str],
) -> tuple[AtlassianConfig, Optional[str], Optional[str]]:
    config_path: Optional[Path] = ctx.obj.get("config_path")
    config = ensure_config(
        base_url=base_url,
        email=email,
        api_token=api_token,
        space_key=space_key,
        parent_page_id=parent_page_id,
        config_path=config_path,
    )
    defaults = config.defaults
    resolved_space = space_key or defaults.space_key
    resolved_parent = parent_page_id or defaults.parent_page_id
    return config, resolved_space, resolved_parent


@app.command()
def download(
    ctx: typer.Context,
    output: Path = typer.Option(
        Path.cwd(),
        "--output",
        "-o",
        help="Directory to store the downloaded documentation tree",
    ),
    root_page_id: Optional[str] = typer.Option(
        None,
        "--root-id",
        help="Root Confluence page ID to download",
    ),
    root_title: Optional[str] = typer.Option(
        None,
        "--root-title",
        help="Title of the root Confluence page (requires --space)",
    ),
    parent_page_id: Optional[str] = typer.Option(
        None,
        "--parent-id",
        help="Parent page ID used to disambiguate when resolving by title",
    ),
    space_key: Optional[str] = typer.Option(
        None,
        "--space",
        "-s",
        help="Confluence space key containing the root page",
    ),
    base_url: Optional[str] = typer.Option(None, help="Base URL of the Confluence instance"),
    email: Optional[str] = typer.Option(None, help="Account email used for authentication"),
    api_token: Optional[str] = typer.Option(None, help="Confluence API token"),
) -> None:
    """Download a Confluence page tree into a local workspace."""

    if not root_page_id and not root_title:
        raise typer.BadParameter("Provide either --root-id or --root-title to identify the root page")

    config, resolved_space, resolved_parent = _resolve_config(
        ctx,
        base_url=base_url,
        email=email,
        api_token=api_token,
        space_key=space_key,
        parent_page_id=parent_page_id,
    )

    if root_title and not resolved_space:
        raise typer.BadParameter("--root-title requires a space key (via --space or configuration defaults)")

    service, cleanup = _build_service(config, workspace=output)
    try:
        result = service.download_tree(
            root_page_id=root_page_id,
            space_key=resolved_space,
            root_title=root_title,
            parent_page_id=resolved_parent,
        )
    finally:
        cleanup()

    console.print(f"Downloaded pages into [bold]{output}[/bold].")
    _format_result(result, action="download")


@app.command()
def upload(
    ctx: typer.Context,
    workspace: Path = typer.Option(
        Path.cwd(),
        "--workspace",
        "-w",
        help="Local workspace directory containing the documentation tree",
    ),
    space_key: Optional[str] = typer.Option(
        None,
        "--space",
        "-s",
        help="Destination Confluence space key",
    ),
    parent_page_id: Optional[str] = typer.Option(
        None,
        "--parent-id",
        help="Parent Confluence page ID to attach the root to",
    ),
    base_url: Optional[str] = typer.Option(None, help="Base URL of the Confluence instance"),
    email: Optional[str] = typer.Option(None, help="Account email used for authentication"),
    api_token: Optional[str] = typer.Option(None, help="Confluence API token"),
) -> None:
    """Upload a local documentation tree to Confluence."""

    config, resolved_space, resolved_parent = _resolve_config(
        ctx,
        base_url=base_url,
        email=email,
        api_token=api_token,
        space_key=space_key,
        parent_page_id=parent_page_id,
    )

    if not resolved_space:
        raise typer.BadParameter("A space key is required to upload pages")

    workspace = workspace.resolve()
    if not workspace.exists():
        raise typer.BadParameter(f"Workspace directory {workspace} does not exist")

    service, cleanup = _build_service(config, workspace=workspace)
    try:
        result = service.upload_tree(space_key=resolved_space, parent_page_id=resolved_parent)
    finally:
        cleanup()

    console.print("Upload completed successfully.")
    _format_result(result, action="upload")


@app.command()
def init(
    directory: Path = typer.Option(
        Path.cwd(),
        "--directory",
        "-d",
        help="Directory that will hold the documentation tree",
    ),
    title: str = typer.Option(..., "--title", "-t", help="Title of the root document"),
    space_key: Optional[str] = typer.Option(
        None,
        "--space",
        "-s",
        help="Default space key to include in the metadata",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite an existing page.md file if it already exists",
    ),
) -> None:
    """Create a new local documentation workspace with a root page."""

    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    page_file = directory / "page.md"
    if page_file.exists() and not force:
        raise typer.BadParameter(f"{page_file} already exists. Use --force to overwrite it.")

    post = frontmatter.Post(
        "# " + title + "\n\nStart editing your content here."
    )
    post.metadata.update(
        {
            "title": title,
            "space_key": space_key,
            "representation": "storage",
        }
    )

    with page_file.open("w", encoding="utf-8") as handle:
        frontmatter.dump(post, handle)

    console.print(f"Initialized documentation workspace at [bold]{directory}[/bold].")


def run() -> None:
    """Entry point for console scripts."""

    app()


if __name__ == "__main__":  # pragma: no cover
    run()
