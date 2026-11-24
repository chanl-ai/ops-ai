"""Amazon S3 objects as a source of files, read through the S3 REST API with path-style addresses.

A source names folders as `bucket/prefix`. Each call reads one ListObjectsV2 page of one folder; the cursor carries the
folders, the index of the one being read and S3's continuation token, and nothing else, so no state lives between
calls. S3 has no change feed, so every listing names every object (`lists_whole`): an object missing from a listing was
removed. An object's id is `bucket/key` and its version tag is its ETag, which changes whenever its bytes do, so an
unchanged object is never fetched again."""

from __future__ import annotations

import base64
import json
import mimetypes
import posixpath
import re
from typing import Any, cast
from urllib.parse import quote
from xml.etree import ElementTree

from ops_plugin_sdk import BadInput, Context, NotFound, PluginError, Response, TooLarge, tool

# tools-service refuses an answer larger than this, so a larger object is listed as skipped instead of failing its fetch.
MAX_BYTES = 25 * 1024 * 1024
PAGE = 1000
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
# A bucket name as S3 allows it; it is written into the path, so nothing else is accepted.
BUCKET = re.compile(r"^[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]$")
TEXT_TYPES = ("application/json", "application/xml", "application/x-yaml", "text/")


def _base(ctx: Context) -> str:
    return str(ctx.settings.endpoint_url).rstrip("/")


def _split(value: str, what: str) -> tuple[str, str]:
    bucket, _, rest = str(value).strip().lstrip("/").partition("/")
    if not BUCKET.match(bucket):
        raise BadInput(f"{what} {value!r} does not start with a bucket name.")
    return bucket, rest


def _url(ctx: Context, bucket: str, key: str = "") -> str:
    return f"{_base(ctx)}/{bucket}/{quote(key, safe='/~')}" if key else f"{_base(ctx)}/{bucket}"


def _fail(r: Response, what: str) -> PluginError:
    code = _text(_xml(r), "Code") if r.content else ""
    if r.status_code == 403 and code in ("SignatureDoesNotMatch", "InvalidAccessKeyId"):
        return PluginError("S3 refused the access key: the key or its secret is wrong.")
    return PluginError(f"{what} answered {r.status_code}{f' ({code})' if code else ''}.")


def _xml(r: Response) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(r.content)
    except ElementTree.ParseError as e:
        raise PluginError("S3 answered something that is not XML.") from e


def _text(node: ElementTree.Element, name: str) -> str:
    found = node.find(f"{NS}{name}")
    if found is None:
        found = node.find(name)
    return (found.text or "") if found is not None else ""


def _all(node: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return node.findall(f"{NS}{name}") or node.findall(name)


def _folders(source: dict[str, Any] | None) -> list[str]:
    picked: Any = (source or {}).get("folders") or []
    if not isinstance(picked, list) or not picked:
        raise BadInput("Pick at least one bucket or folder.")
    out: list[str] = []
    for f in cast(list[Any], picked):
        bucket, prefix = _split(str(f), "The folder")
        out.append(f"{bucket}/{prefix}")
    return out


def _row(bucket: str, obj: ElementTree.Element) -> dict[str, Any] | None:
    key = _text(obj, "Key")
    if not key or key.endswith("/"):
        return None
    size = int(_text(obj, "Size") or 0)
    row: dict[str, Any] = {
        "id": f"{bucket}/{key}",
        "title": posixpath.basename(key),
        "updated_at": _text(obj, "LastModified"),
        "folder": posixpath.dirname(f"{bucket}/{key}"),
        "size": size,
        "marker": _text(obj, "ETag").strip('"'),
    }
    if size > MAX_BYTES:
        row["skipped"], row["skipped_code"] = "Larger than 25 MB", "TOO_LARGE"
    return row


def _state(source: dict[str, Any] | None, cursor: str | None) -> dict[str, Any]:
    if cursor is None:
        return {"folders": _folders(source), "i": 0, "token": None}
    try:
        st = cast(dict[str, Any], json.loads(cursor))
        st["i"], st["folders"] = int(st["i"]), [str(f) for f in st["folders"]]
    except (ValueError, KeyError, TypeError) as e:
        raise BadInput("The cursor is not one this plugin issued.") from e
    return st


@tool(access="read")
def list_files(
    ctx: Context, source: dict[str, Any], since: str | None = None, cursor: str | None = None
) -> dict[str, Any]:
    """Every object of the picked folders, one ListObjectsV2 page a call. `since` is not used: S3 lists whole."""
    del since
    st = _state(source, cursor)
    bucket, prefix = _split(st["folders"][st["i"]], "The folder")
    params: dict[str, Any] = {"list-type": "2", "max-keys": str(PAGE)}
    if prefix:
        params["prefix"] = prefix
    if st.get("token"):
        params["continuation-token"] = st["token"]
    r = ctx.http.get(_url(ctx, bucket), params=params)
    if r.status_code == 404:
        raise NotFound(f"Bucket {bucket} answered 404.")
    if r.status_code >= 400:
        raise _fail(r, f"The listing of {bucket}")
    page = _xml(r)
    rows = [row for obj in _all(page, "Contents") if (row := _row(bucket, obj))]
    token = _text(page, "NextContinuationToken") if _text(page, "IsTruncated") == "true" else ""
    st = {**st, "token": token} if token else {**st, "i": int(st["i"]) + 1, "token": None}
    out: dict[str, Any] = {"items": rows}
    if int(cast(int, st["i"])) < len(cast(list[str], st["folders"])):
        out["next_cursor"] = json.dumps(st, separators=(",", ":"))
    return out


def _mime(key: str, said: str | None) -> str:
    """The type the name says, then the type the store was told: stores fill in a guess of their own for an upload
    that named none (S3 says binary/octet-stream, others sniff the bytes)."""
    return mimetypes.guess_type(key)[0] or (said or "").split(";")[0] or "application/octet-stream"


@tool(access="read")
def get_file(ctx: Context, source: dict[str, Any], id: str, tag: str | None = None) -> dict[str, Any]:
    """One object, or `{"unchanged": true}` when `tag` (its ETag) is still the object's. A gone object is NOT_FOUND."""
    del source
    bucket, key = _split(id, "The file")
    head = ctx.http.request("HEAD", _url(ctx, bucket, key))
    if head.status_code in (404, 410):
        raise NotFound(f"{id} answered {head.status_code}.")
    if head.status_code >= 400:
        raise _fail(head, f"File {id}")
    headers = {k.lower(): v for k, v in head.headers.items()}
    etag = headers.get("etag", "").strip('"')
    if tag and etag and tag == etag:
        return {"unchanged": True}
    if int(headers.get("content-length") or 0) > MAX_BYTES:
        raise TooLarge(f"{posixpath.basename(key)} is larger than 25 MB.")
    r = ctx.http.get(_url(ctx, bucket, key))
    if r.status_code in (404, 410):
        raise NotFound(f"{id} answered {r.status_code}.")
    if r.status_code >= 400:
        raise _fail(r, f"File {id}")
    mime = _mime(key, headers.get("content-type"))
    out: dict[str, Any] = {
        "id": id,
        "title": posixpath.basename(key),
        "mime": mime,
        "folder": posixpath.dirname(id),
        "metadata": {"modified": headers.get("last-modified"), "bucket": bucket},
    }
    if mime.startswith(TEXT_TYPES):
        out |= {"encoding": "text", "content": r.content.decode("utf-8-sig", errors="replace")}
    else:
        out |= {"encoding": "base64", "content": base64.b64encode(r.content).decode()}
    if etag:
        out["marker"] = etag
    return out


@tool(access="read")
def list_scopes(
    ctx: Context,
    source: dict[str, Any] | None = None,
    query: str | None = None,
    parent: str | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """What a person picks: the buckets whose name holds `query`, or, with `bucket/prefix` as `parent`, the folders
    directly under it. Each is a folder id `bucket/prefix/`."""
    del source
    if not parent:
        r = ctx.http.get(f"{_base(ctx)}/")
        if r.status_code >= 400:
            raise _fail(r, "The bucket list")
        words = (query or "").strip().lower()
        names = [_text(b, "Name") for b in _all(_all(_xml(r), "Buckets")[0], "Bucket")] if _all(_xml(r), "Buckets") else []
        rows = [{"id": f"{n}/", "title": n, "kind": "folder"} for n in names if not words or words in n.lower()]
        return {"scopes": rows}
    bucket, prefix = _split(parent, "The folder")
    params: dict[str, Any] = {"list-type": "2", "delimiter": "/", "max-keys": str(PAGE)}
    if prefix:
        params["prefix"] = prefix if prefix.endswith("/") else prefix + "/"
    if cursor:
        params["continuation-token"] = cursor
    r = ctx.http.get(_url(ctx, bucket), params=params)
    if r.status_code >= 400:
        raise _fail(r, f"The folders of {bucket}")
    page = _xml(r)
    rows: list[dict[str, Any]] = []
    for p in _all(page, "CommonPrefixes"):
        sub = _text(p, "Prefix")
        rows.append({"id": f"{bucket}/{sub}", "title": posixpath.basename(sub.rstrip("/")), "kind": "folder",
                     "parent": f"{bucket}/{prefix}"})  # fmt: skip
    out: dict[str, Any] = {"scopes": rows}
    if _text(page, "IsTruncated") == "true" and (nxt := _text(page, "NextContinuationToken")):
        out["next_cursor"] = nxt
    return out


PREVIEW_FILES = 50


@tool(access="read")
def preview_files(ctx: Context, source: dict[str, Any]) -> dict[str, Any]:
    """The first files the source would take in, each with its outcome, from the first listing page of each folder.
    Nothing is fetched or stored."""
    files: list[dict[str, Any]] = []
    capped = False
    for i in range(len(_folders(source))):
        page = list_files(ctx, source, cursor=json.dumps({"folders": _folders(source), "i": i, "token": None}))
        capped = capped or bool(page.get("next_cursor") and int(json.loads(page["next_cursor"])["i"]) == i)
        for r in page["items"]:
            files.append({"id": r["id"], "outcome": r.get("skipped") or "Will fetch", "will_fetch": "skipped" not in r})
    return {
        "found": len(files),
        "will_fetch": sum(1 for f in files if f["will_fetch"]),
        "pages": files[:PREVIEW_FILES],
        "capped": capped or len(files) > PREVIEW_FILES,
    }
