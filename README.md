# Atlassian CLI

Synchronize Confluence documentation trees with a local Markdown workspace so you can edit pages in VS Code and push the updates back to Confluence.

## Features

- Download an existing Confluence page tree (root page plus descendants) into a local folder.
- Edit Markdown locally with metadata stored as YAML frontmatter alongside each page.
- Upload local changes back to Confluence, creating new pages if necessary and updating existing ones with correct versioning.
- Initialize a brand-new workspace that you can later upload to a selected space and parent page.
- Authenticate using Atlassian API tokens (email + token pairing).

## Installation

You need Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

This installs the `atlassian-cli` console script.

## Configuration

The CLI reads credentials and default parameters from (in order):

1. CLI flags (`--base-url`, `--email`, `--api-token`, `--space`, `--parent-id`).
2. A TOML configuration file provided with `--config`.
3. Default locations:
   - `./atlassian-cli.toml`
   - `~/.config/atlassian-cli/config.toml`
4. Environment variables prefixed with `ATLASSIAN_`.

Example `atlassian-cli.toml`:

```toml
[credentials]
base_url = "https://your-domain.atlassian.net"
email = "you@example.com"
api_token = "your-api-token"

[defaults]
space_key = "DOCS"
parent_page_id = "123456"
```

Environment variable mapping:

- `ATLASSIAN_BASE_URL`
- `ATLASSIAN_EMAIL`
- `ATLASSIAN_API_TOKEN`
- `ATLASSIAN_SPACE_KEY`
- `ATLASSIAN_PARENT_PAGE_ID`

## Usage

### Initialize a workspace

```bash
atlassian-cli init --directory docs --title "Engineering Handbook" --space DOCS
```

This creates `docs/page.md` with frontmatter and starter content.

### Download a Confluence tree

Download the tree rooted at a specific page ID into `docs/`:

```bash
atlassian-cli download --output docs --root-id 123456 --config atlassian-cli.toml
```

Or resolve by title (requires space key):

```bash
atlassian-cli download \
  --output docs \
  --root-title "Engineering Handbook" \
  --space DOCS \
  --parent-id 654321
```

### Upload local changes

```bash
atlassian-cli upload --workspace docs --config atlassian-cli.toml
```

You can override credentials or defaults per invocation:

```bash
atlassian-cli upload \
  --workspace docs \
  --space DOCS \
  --parent-id 654321 \
  --email you@example.com \
  --api-token $ATLASSIAN_API_TOKEN \
  --base-url https://your-domain.atlassian.net
```

## Local workspace structure

Each page lives inside its own directory containing a `page.md` file with YAML frontmatter:

```
root/
  page.md
  child-page/
    page.md
    nested-page/
      page.md
```

Frontmatter fields include `title`, `space_key`, `confluence_id`, `parent_id`, `version`, and `representation`. Do not delete them—they allow the CLI to reconcile local edits with Confluence.

## Development

Install dependencies and run the CLI locally:

```bash
pip install -e .[dev]
```

(Adjust extras as needed.)

## Verification

After changing code run:

```bash
ruff check .
pytest
```

For manual smoke tests against Confluence:

1. Create `atlassian-cli.toml` with real credentials.
2. Run `atlassian-cli init --directory tmp-docs --title "Test Root"`.
3. Upload the workspace: `atlassian-cli upload --workspace tmp-docs --config atlassian-cli.toml`.
4. Make edits locally and push again.
5. Confirm documents update in Confluence.
