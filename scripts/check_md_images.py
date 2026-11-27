"""Refuse a markdown image that does not load from the docs site.

Every image under docs/ is published by the docs site at https://opsai.chanl.ai/docs/<its path under docs/>
(apps/docs/scripts/copy-images.mjs). A relative path only works where the reader has the repository, and a
raw.githubusercontent.com link breaks when a branch or file moves, so every image in a tracked markdown file names the
site URL. This check fails on a relative image, a raw.githubusercontent.com image, and a site URL whose file is not
under docs/. It reads markdown images, plain links to image files, reference definitions of either, and HTML src
and srcset attributes. Code spans and fenced code are skipped, since they show the syntax rather than use it.

  python3 scripts/check_md_images.py              check every tracked .md file
  python3 scripts/check_md_images.py --fix        rewrite relative images under docs/ to the site URL
  python3 scripts/check_md_images.py --self-test  plants each kind of bad image and sees it refused

The accepted hosts are IMAGE_HOSTS in apps/docs/src/lib/repo.mjs, and --fix writes the first. The live site builds from
main, so a new image's URL resolves there once its commit is released; the branch's docs preview serves it before.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
REPO_MJS = ROOT / "apps/docs/src/lib/repo.mjs"

FENCE = re.compile(r"^ {0,3}(```+|~~~+).*?^ {0,3}\1[ \t]*$", re.M | re.S)
CODE_SPAN = re.compile(r"(`+)(?!`).+?(?<!`)\1(?!`)", re.S)
COMMENT = re.compile(r"<!--.*?-->", re.S)
MD_IMAGE = re.compile(r"!\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*<?([^)\s>]+)")
REF_IMAGE = re.compile(r"!\[[^\]]*\]\[([^\]]*)\]")
REF_DEF = re.compile(r"^ {0,3}\[([^\]]+)\]:\s*<?(\S+?)>?(?:\s|$)", re.M)
LINK = re.compile(r"(?<!!)\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*<?([^)\s>]+)")
IMG_FILE = re.compile(r"\.(png|jpe?g|gif|svg|webp)(?:[?#].*)?$", re.I)
HTML_SRC = re.compile(r"<(?:img|source)\b[^>]*?\s(?:src|srcset)\s*=\s*[\"']([^\"']+)[\"']", re.I)


def hosts() -> list[str]:
    m = re.search(r"IMAGE_HOSTS\s*=\s*\[([^\]]*)\]", REPO_MJS.read_text())
    if not m:
        raise SystemExit(f"check_md_images: IMAGE_HOSTS not found in {REPO_MJS}")
    return re.findall(r"'([^']+)'", m.group(1))


def _blank(m: re.Match[str]) -> str:
    """Code replaced by spaces of the same length, so offsets in the rest of the text stay put."""
    return re.sub(r"[^\n]", " ", m.group(0))


def prose(text: str) -> str:
    return CODE_SPAN.sub(_blank, FENCE.sub(_blank, COMMENT.sub(_blank, text)))


def image_urls(text: str) -> list[tuple[int, int, str]]:
    """(start, end, url) of each image URL outside code, as offsets into text."""
    clean = prose(text)
    found: list[tuple[int, int, str]] = []
    for pat in (MD_IMAGE, HTML_SRC):
        for m in pat.finditer(clean):
            if pat is HTML_SRC:
                # srcset holds "url 2x, url 1x": each candidate's first word is a URL.
                for c in re.finditer(r"(?:^|,)\s*(\S+)", m.group(1)):
                    found.append((m.start(1) + c.start(1), m.start(1) + c.end(1), c.group(1)))
            else:
                found.append((m.start(1), m.end(1), m.group(1)))
    # A plain link to an image file opens the image, so it is held to the same rule.
    found += [(m.start(1), m.end(1), m.group(1)) for m in LINK.finditer(clean) if IMG_FILE.search(m.group(1))]
    refs = {r.lower() for r in REF_IMAGE.findall(clean)}
    for m in REF_DEF.finditer(clean):
        if m.group(1).lower() in refs or IMG_FILE.search(m.group(2)):
            found.append((m.start(2), m.end(2), m.group(2)))
    return sorted(found)


def problem(md: str, url: str, allowed: list[str]) -> str | None:
    if urlsplit(url).hostname == "raw.githubusercontent.com":
        return "raw.githubusercontent.com image; name it by its docs site URL"
    m = re.match(r"https://([^/]+)/docs/([^?#]+)$", url)
    if m and m.group(1) in allowed:
        return None if (ROOT / "docs" / m.group(2)).is_file() else "no such image under docs/"
    if re.match(r"^[a-z][a-z0-9+.-]*:|^//", url, re.I):
        return None
    return "relative image; name it by its docs site URL (scripts/check_md_images.py --fix)"


def site_url(md: str, url: str, host: str) -> str | None:
    """The site URL for a relative image under docs/, or None when it is elsewhere or missing."""
    target = (ROOT / md).parent / url.split("#", maxsplit=1)[0].split("?", maxsplit=1)[0]
    try:
        rel = target.resolve().relative_to(ROOT / "docs")
    except ValueError:
        return None
    return f"https://{host}/docs/{rel.as_posix()}" if target.is_file() else None


def tracked_markdown() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True)
    return [p for p in out.stdout.split("\0") if p and (ROOT / p).is_file()]


def check(files: list[str], allowed: list[str]) -> list[str]:
    errors = []
    for md in files:
        text = (ROOT / md).read_text(encoding="utf-8")
        for start, _, url in image_urls(text):
            why = problem(md, url, allowed)
            if why:
                errors.append(f"{md}:{text.count(chr(10), 0, start) + 1}: {url}: {why}")
    return errors


def fix(files: list[str], host: str) -> int:
    changed = 0
    for md in files:
        path = ROOT / md
        text = path.read_text(encoding="utf-8")
        new = text
        for start, end, url in reversed(image_urls(text)):
            if problem(md, url, [host]) and (to := site_url(md, url, host)):
                new = new[:start] + to + new[end:]
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed += 1
    return changed


def self_test(allowed: list[str]) -> int:
    host = allowed[0]
    planted = {
        "relative": "![a](media/hero.gif)\n",
        "html": '<picture><source srcset="media/run-dark.png"><img src="media/run-light.png"></picture>\n',
        "raw": "![a](https://raw.githubusercontent.com/chanl-ai/ops-ai/main/docs/media/hero.gif)\n",
        "missing": f"![a](https://{host}/docs/media/no-such-image.png)\n",
        "reference": "![a][pic]\n\n[pic]: media/hero.gif\n",
        "link": "[the clip](media/hero.gif)\n",
    }
    passing = f"![a](https://{host}/docs/media/hero.gif)\n\n`![shown](media/hero.gif)`\n\n```\n![shown](x.png)\n```\n"
    ok = True
    with tempfile.TemporaryDirectory(dir=ROOT / "docs") as tmp:
        rel = Path(tmp).relative_to(ROOT).as_posix()
        for name, body in {**planted, "passing": passing}.items():
            (Path(tmp) / f"{name}.md").write_text(
                body.replace("media/", "../media/" if "://" not in body else "media/")
            )
        for name in planted:
            if not check([f"{rel}/{name}.md"], allowed):
                print(f"check_md_images self-test: the {name} image was accepted")
                ok = False
        if errs := check([f"{rel}/passing.md"], allowed):
            print(f"check_md_images self-test: a good page was refused: {errs}")
            ok = False
        fix([f"{rel}/relative.md"], host)
        if check([f"{rel}/relative.md"], allowed):
            print("check_md_images self-test: --fix left a relative image")
            ok = False
    print("check_md_images self-test: " + ("ok, every planted image refused" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    allowed = hosts()
    if "--self-test" in argv:
        return self_test(allowed)
    files = tracked_markdown()
    if "--fix" in argv:
        print(f"check_md_images: rewrote {fix(files, allowed[0])} files")
    errors = check(files, allowed)
    for e in errors:
        print(e)
    if errors:
        print(f"check_md_images: {len(errors)} image(s) that do not load from the docs site")
        return 1
    print(f"check_md_images: ok, {len(files)} markdown files")
    return 0


if __name__ == "__main__":
    os.chdir(ROOT)
    sys.exit(main(sys.argv[1:]))
