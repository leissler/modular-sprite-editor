# Modular Sprite Editor website

The product site and user guide, built with MkDocs Material.

- Site: https://modularsprites.bionic-productions.com/
- Readers: pixel artists, animators and other graphic content creators. Programmer-facing details stay in the
  repository (`README.md`, `AGENTS.md`, `docs/`, `examples/sgdk/README.md`); the site links to them from
  [For your programmer](docs/reference/programmers.md).

## Preview locally

```bash
website/serve.sh
```

Open http://127.0.0.1:8000/. The script creates `website/.venv` and installs the pinned dependencies on the first
run. Set `MODULARSPRITES_DOCS_ADDR` to choose another address.

## Build and check

```bash
cd website
.venv/bin/mkdocs build --strict
.venv/bin/python scripts/check_site.py
```

The checker verifies local links and anchors, image alt text, that every page is in the search index, and the
editorial punctuation rules below. The `Website` GitHub workflow runs the same build and checks.

## Update and publish

1. Edit Markdown in `docs/`; new pages go into `nav` in `mkdocs.yml`. The landing page is `overrides/home.html`.
2. Build strictly and run the checker. Look at desktop and phone layouts after theme changes.
3. Commit and push `main`.
4. Run `website/scripts/deploy.sh` (`--dry-run` checks the prerequisites without uploading).

The deployment uploads a versioned release, verifies every uploaded file and atomically switches `current`; if the
public check fails it switches back. See [deployment/README.md](deployment/README.md).

## Pictures

Every picture comes from the editor and the example projects; regenerate them when the editor or the examples change.

| Pictures | Made by |
| --- | --- |
| `docs/assets/images/screens/*.png`: editor screenshots | `python3 website/scripts/capture_screenshots.py [NAME ...]` (macOS, needs the screen; quantized to 256 colours) |
| `docs/assets/images/art/*`: the Swordfight loop and the step pictures | `python3 website/scripts/make_site_art.py` (the editor's renderer) |
| `docs/assets/images/logo.svg`, `favicon.png` | `python3 tools/make_app_icon.py` (also writes the app icons) |
| `docs/assets/images/logo-title.png`: the logo on the landing page | `python3 tools/make_logo.py` (the app icon's mannequin over a pixel wordmark) |
| `docs/reference/shortcuts.md` | `python3 website/scripts/make_shortcuts_page.py` (from `ui/shortcuts_dialog.py`) |
| The product card on bionic-productions.com (`public/assets/modular-sprite-editor-logo.png` in the bionic-site repository) | `python3 tools/make_logo.py --card OUT.png` |

Pixel art is scaled by whole numbers only and shown with `image-rendering: pixelated` (`.ms-pixel`). The example art
belongs to its owners; [Credits](docs/reference/credits.md) says so. The logo uses none of it: only our own pixel art.

## Writing

Start with what the reader wants to make. Name UI labels exactly as the editor shows them, in bold, and check them in
the code. Short steps, concrete examples, no marketing filler. Use ordinary punctuation: no em or en dashes, curly
quotes or ellipsis characters (write `...` for menu items such as **Grid slice...**); the checker enforces this.
