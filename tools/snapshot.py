#!/usr/bin/env python3
"""Build a single self-contained HTML file of the site as it stands.

The site normally fetches its JSON at runtime, which browsers refuse to do from
a file:// page, and it loads images from disk. This bakes all of it -- styles,
script, data and pictures -- into one file that works with no network and no
server. For reading on a plane.

    python3 tools/snapshot.py [output.html]
"""

import base64
import json
import mimetypes
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_FILES = ["data/state.json", "data/history.json", "data/status.json",
              "images/manifest.json"]


def read(path):
    with open(os.path.join(ROOT, path), "r", encoding="utf-8") as handle:
        return handle.read()


def data_uri(path):
    full = os.path.join(ROOT, path)
    kind = mimetypes.guess_type(full)[0] or "application/octet-stream"
    with open(full, "rb") as handle:
        return f"data:{kind};base64," + base64.b64encode(handle.read()).decode("ascii")


def build(output, skip_images=()):
    html = read("index.html")

    bundled_data = {}
    for path in DATA_FILES:
        try:
            bundled_data[path] = json.loads(read(path))
        except (OSError, json.JSONDecodeError):
            pass

    images, skipped = {}, []
    manifest = bundled_data.get("images/manifest.json", {})
    for entry in manifest.get("images", []):
        key = "images/" + entry["file"]
        if key in images:
            continue
        if entry["file"] in skip_images:
            skipped.append(entry["file"])
            continue
        try:
            images[key] = data_uri(key)
        except OSError:
            skipped.append(entry["file"])

    # Inline the stylesheet and the script, and drop the favicon reference --
    # a file:// page has nowhere to load it from.
    html = html.replace(
        '<link rel="stylesheet" href="styles.css">',
        "<style>\n" + read("styles.css") + "\n</style>")
    html = html.replace(
        '<link rel="icon" href="images/geelong-crest.png" type="image/png">', "")

    stamp = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    banner = (
        '<div style="margin:1rem 1.15rem 0;padding:.7rem .9rem;border-radius:12px;'
        'border:1px solid #16376e;background:rgba(77,157,255,.1);color:#9db0d4;'
        'font:600 .74rem/1.5 -apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,'
        'sans-serif">Offline snapshot, frozen ' + stamp + '. Everything is baked '
        'in, so it works with no signal — but nothing here will update until you '
        'open the live site again.</div>')
    html = html.replace("<main>", banner + "\n<main>", 1)

    payload = (
        "<script>\n"
        "window.__NINE_LIVES_DATA = " + json.dumps(bundled_data, separators=(",", ":")) + ";\n"
        "window.__NINE_LIVES_IMAGES = " + json.dumps(images, separators=(",", ":")) + ";\n"
        "</script>\n"
    )
    html = html.replace('<script src="app.js"></script>',
                        payload + "<script>\n" + read("app.js") + "\n</script>")

    with open(output, "w", encoding="utf-8") as handle:
        handle.write(html)

    size = os.path.getsize(output)
    print(f"{output}  {size/1024/1024:.2f} MB  "
          f"({len(images)} images inlined, {len(bundled_data)} data files)")
    if skipped:
        print("  left out:", ", ".join(skipped))
    return size


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "nine-lives-offline.html")
