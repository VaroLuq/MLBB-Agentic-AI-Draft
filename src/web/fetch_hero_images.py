"""Download hero portraits into src/web/static/heroes/.

    python -m src.web.fetch_hero_images [--force]

Images come from the Rone Arena API's own `head` field (a 128x128 square face
crop), which arrives attached to the hero record, so the name -> image mapping
is the API's own. That matters: a scraped `scrapped-images.json` was tried
first and its mapping was wrong for every hero checked — Gloo (a slime blob)
carried a portrait of a winged woman, Belerick (a walking tree) an elf,
Popol and Kupa (a boy with a wolf) a swordsman. Pairing two separately-ordered
lists is exactly how that happens; reading the field off the record cannot.

Downloaded here rather than hotlinked because this app self-hosts everything
and loads nothing from a CDN at runtime — and because the URLs carry a
versioned path segment (`homepage_2_2_16_1232_1`) that will rotate.

The art is Moonton's. `data`-style gitignore applies: the files are NOT
committed, so the repo never redistributes them; anyone cloning runs this
command. Heroes without an image keep the generated initials badge.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import requests

from src.api_client.rone_arena_client import list_heroes

OUT_DIR = Path("src/web/static/heroes")
MANIFEST = OUT_DIR / "manifest.json"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def slug(name: str) -> str:
    """Match heroes.js's `norm()` exactly, so the frontend can look images up."""
    return re.sub(r"[^\w]", "", name.lower(), flags=re.UNICODE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download images already on disk")
    args = parser.parse_args()

    try:
        heroes = list_heroes(size=200)
    except Exception as exc:
        print(f"Could not reach the hero list: {exc}", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest, saved, skipped, failed = {}, 0, 0, 0

    for hero in heroes:
        name, url = hero.get("name"), hero.get("head")
        if not name:
            continue
        if not url:
            print(f"  no image for {name}")
            failed += 1
            continue

        key = slug(name)
        path = OUT_DIR / f"{key}.png"
        if path.exists() and not args.force:
            manifest[key] = path.name
            skipped += 1
            continue

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            body = response.content
            # Verify it is really a PNG: a 200 carrying an error page would
            # otherwise be written out and render as a broken portrait.
            if not body.startswith(PNG_MAGIC):
                raise ValueError(f"not a PNG (first bytes {body[:8]!r})")
            path.write_bytes(body)
            manifest[key] = path.name
            saved += 1
        except Exception as exc:
            print(f"  {name}: {exc}")
            failed += 1

    MANIFEST.write_text(json.dumps(manifest, indent=0, sort_keys=True), encoding="utf-8")
    total = sum(p.stat().st_size for p in OUT_DIR.glob("*.png"))
    print(f"\n{saved} downloaded, {skipped} already present, {failed} failed")
    print(f"{len(manifest)} of {len(heroes)} heroes have a portrait "
          f"({total / 1024 / 1024:.1f} MB in {OUT_DIR})")
    print("Heroes without one keep the initials badge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
