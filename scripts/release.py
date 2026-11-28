#!/usr/bin/env python3
"""The release commands behind `make release-start`, `hotfix-start`, `release-rc` and the finish workflow
(docs/deploy/release.md). V=X.Y.Z names the version; DRY=1 (the default) prints what would happen and changes nothing.

  start          release/X.Y.Z from origin/develop's tip with one commit that sets deploy/release/version and both SDK
                 versions (and folds the changelog fragments into changelog/releases/X.Y.Z.json), pushed, with a pull
                 request into main titled `release: X.Y.Z`. Refuses while another release or hotfix branch exists, when
                 vX.Y.Z exists or is not above the newest tag, or when develop's tip has no green ci.yml run
  hotfix-start   the same from the newest vX.Y.Z tag, as hotfix/<NAME> (NAME=<what the fix changes>), `hotfix: X.Y.Z`
  rc             tags the release (or hotfix) branch's tip vX.Y.Z-rc.N, N the next free number, once the push run's
                 staging deploy and click walk succeeded; prints the staging URL. An rc tag publishes nothing
  finish         what release-finish.yml does after the pull request merged: prints the tag to make for BRANCH at SHA
                 (version from deploy/release/version there), refusing when the file and the branch name disagree
  latest         prints the newest vX.Y.Z tag reachable from origin/main (release candidates are not releases): the
                 release the upgrade proof starts from (ci.yml, job release-proof)
  proof          reads the jobs of a push run (the Actions API's jobs list) on stdin and exits 1 unless its
                 `release-proof` job succeeded; a skipped or missing one fails too (the release pull request's gate)
  check-version  exits 1 when BRANCH (default: the checked-out branch) is release/X.Y.Z and HEAD's
                 deploy/release/version is not X.Y.Z (ci.yml, job release-proof)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

# deploy/fly/stg_deploy.sh prints this line when the walk ran.
WALK = re.compile(r"click walk \((\d+) OK, (\d+) FAIL\)")
VERSION_FILE = "deploy/release/version"
SDK_PY = "sdk/python/pyproject.toml"
SDK_PY_INIT = "sdk/python/src/ops_ai/__init__.py"
SDK_TS = "sdk/typescript/package.json"
UV_LOCK = "uv.lock"
SEMVER = re.compile(r"\d+\.\d+\.\d+")


class Refusal(Exception):
    pass


def run(*cmd: str, stdin: str | None = None, env: dict[str, str] | None = None, cwd: str | Path | None = None) -> str:
    done = subprocess.run(cmd, capture_output=True, text=True, check=False, input=stdin, env=env, cwd=cwd)
    if done.returncode != 0:
        raise Refusal(f"{' '.join(cmd[:3])} failed: {(done.stderr or done.stdout).strip()}")
    return done.stdout


def gh_json(*args: str) -> Any:
    return json.loads(run("gh", *args))


def version() -> str:
    v = os.environ.get("V", "")
    if not SEMVER.fullmatch(v):
        raise Refusal("set V to the version, for example V=1.2.0")
    return v


def key(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def release_tags(tags: list[str]) -> list[str]:
    """The released versions among the tag names, lowest first (release candidates are not released versions)."""
    return sorted((t[1:] for t in tags if re.fullmatch(r"v\d+\.\d+\.\d+", t)), key=key)


def next_rc(tags: list[str], v: str) -> str:
    held = [int(m.group(1)) for t in tags if (m := re.fullmatch(rf"v{re.escape(v)}-rc\.(\d+)", t))]
    return f"v{v}-rc.{max(held, default=0) + 1}"


def start_refusals(v: str, branches: list[str], tags: list[str], tip: str) -> list[str]:
    """Why a release of v cannot start; `tip` is the ci.yml state of the commit it starts from ('success' or why)"""
    out = [f"{b} exists; finish or delete it first" for b in branches]
    released = release_tags(tags)
    if f"v{v}" in tags:
        out.append(f"v{v} exists")
    elif released and key(v) <= key(released[-1]):
        out.append(f"{v} is not above the newest release v{released[-1]}")
    if tip != "success":
        out.append(f"the commit it starts from has no green ci.yml run ({tip})")
    return out


def finish_tag(branch: str, have: str, tags: list[str]) -> str:
    """The tag a merged release or hotfix branch gets, from the version file on main at its merge commit."""
    if not SEMVER.fullmatch(have):
        raise Refusal(f"{VERSION_FILE} on main says '{have}', not X.Y.Z")
    named = re.fullmatch(r"release/(\d+\.\d+\.\d+)", branch)
    if named and named.group(1) != have:
        raise Refusal(f"{branch} merged, but {VERSION_FILE} on main says {have}, not {named.group(1)}")
    if not named and not branch.startswith("hotfix/"):
        raise Refusal(f"{branch} is not a release or hotfix branch")
    if f"v{have}" in tags:
        raise Refusal(f"v{have} exists already")
    return f"v{have}"


def sdk_edits(read: Callable[[str], str | None], v: str) -> dict[str, str]:
    """The files that carry an SDK version, with v put in; `read(path)` gives a file's text at the base commit."""
    subs = {
        SDK_PY: (r'^version = "[^"]*"', f'version = "{v}"'),
        SDK_PY_INIT: (r'^__version__ = "[^"]*"', f'__version__ = "{v}"'),
        SDK_TS: (r'^(\s*)"version": "[^"]*"', rf'\1"version": "{v}"'),
    }
    out: dict[str, str] = {}
    for path, (pattern, repl) in subs.items():
        text = read(path)
        if text is None:
            continue
        new, n = re.subn(pattern, repl, text, count=1, flags=re.M)
        if n:
            out[path] = new
    lock = read(UV_LOCK)
    if lock is not None:
        new = re.sub(r'(\[\[package\]\]\nname = "ops-ai"\nversion = )"[^"]*"', rf'\1"{v}"', lock, count=1)
        if new != lock:
            out[UV_LOCK] = new
    return out


def latest_release(tags: list[str], on_main: Callable[[str], bool]) -> str | None:
    """The newest vX.Y.Z among the tags `on_main` accepts; a tag made off main (a develop commit) does not count."""
    for v in reversed(release_tags(tags)):
        if on_main(f"v{v}"):
            return f"v{v}"
    return None


def proof_problem(jobs: list[dict[str, Any]]) -> str | None:
    """Why the push run of a release branch is no proof, or None when its `release-proof` job succeeded."""
    found = [j for j in jobs if j.get("name") == "release-proof"]
    if not found:
        return "the push run has no release-proof job"
    state = found[0].get("conclusion") or found[0].get("status")
    return None if state == "success" else f"release-proof of the push run is {state}, not success"


def remote_branches() -> list[str]:
    out = run("git", "ls-remote", "--heads", "origin", "refs/heads/release/[0-9]*", "refs/heads/hotfix/*")
    return [ln.split("refs/heads/", 1)[1] for ln in out.splitlines() if "refs/heads/" in ln]


def tag_names() -> list[str]:
    run("git", "fetch", "--quiet", "--tags", "origin")
    return run("git", "tag", "--list", "v[0-9]*").split()


def show(sha: str, path: str) -> str | None:
    done = subprocess.run(["git", "show", f"{sha}:{path}"], capture_output=True, text=True, check=False)
    return done.stdout if done.returncode == 0 else None


def file_version(ref: str) -> str:
    text = show(ref, VERSION_FILE)
    return text.strip() if text is not None else "missing"


def version_problem(branch: str, ref: str) -> str | None:
    named = re.fullmatch(r"release/(\d+\.\d+\.\d+)", branch)
    if not named:
        return None
    have = file_version(ref)
    if have != named.group(1):
        return f"{VERSION_FILE} on {branch} says {have}, not {named.group(1)}"
    return None


def changelog_fold(sha: str, v: str) -> dict[str, Any]:
    """The plan folding the changelog fragments at sha into changelog/releases/<v>.json (changelog-fold.mjs)."""
    out = run("node", str(Path(__file__).with_name("changelog-fold.mjs")), "--release", v, "--ref", sha)
    return json.loads(out)


def with_version(sha: str, v: str) -> str:
    """A new commit on sha that sets the version file and both SDK versions to v and folds the changelog fragments into
    the release's changelog file, made without a checkout."""
    fold = changelog_fold(sha, v)
    if subprocess.run(["git", "var", "GIT_COMMITTER_IDENT"], capture_output=True, check=False).returncode != 0:
        raise Refusal("no git identity; set git user.name and user.email")
    files = {VERSION_FILE: f"{v}\n", **sdk_edits(lambda p: show(sha, p), v), **fold["files"]}
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(tmp, "index")}
        run("git", "read-tree", sha, env=env)
        for path, text in files.items():
            blob = run("git", "hash-object", "-w", "--stdin", stdin=text).strip()
            run("git", "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
        for path in fold["remove"]:
            run("git", "update-index", "--force-remove", path, env=env)
        tree = run("git", "write-tree", env=env).strip()
    return run("git", "commit-tree", tree, "-p", sha, "-m", f"chore(release): set the version to {v}").strip()


def runs_for(workflow: str, sha: str) -> list[dict[str, Any]]:
    fields = "databaseId,conclusion,status"
    try:
        return gh_json("run", "list", "--workflow", workflow, "--commit", sha, "--json", fields, "--limit", "10")
    except Refusal as e:
        if "HTTP 404" in str(e):  # a workflow file GitHub has never run
            return []
        raise


def ci_status(sha: str) -> str:
    runs = runs_for("ci.yml", sha)
    if not runs:
        return "no ci.yml run"
    if any(r.get("conclusion") == "success" for r in runs):
        return "success"
    return runs[0].get("conclusion") or runs[0].get("status") or "unknown"


def staging_problem(sha: str) -> str | None:
    """Why the staging deploy of sha does not count, or None when it succeeded with a clean click walk. The deploy is
    the `staging / deploy` job of the ci.yml run the push to the branch started."""
    deploys: list[dict[str, Any]] = []
    for found in runs_for("ci.yml", sha):
        jobs = gh_json("run", "view", str(found["databaseId"]), "--json", "jobs")["jobs"]
        deploys += [j for j in jobs if j.get("name") == "staging / deploy"]
    if not deploys:
        return f"no staging deploy of {sha[:8]} yet (job 'staging / deploy' of the push run)"
    done = [j for j in deploys if j.get("conclusion") == "success"]
    if not done:
        return f"the staging deploy of {sha[:8]} is {deploys[0].get('conclusion') or 'not finished'}, not success"
    log = run("gh", "api", f"repos/{{owner}}/{{repo}}/actions/jobs/{done[0]['databaseId']}/logs")
    walk = WALK.search(log)
    if "click walk skipped" in log or not walk:
        return f"the staging deploy of {sha[:8]} did not run the click walk"
    if walk.group(2) != "0" or walk.group(1) == "0":
        return f"the click walk on staging for {sha[:8]} was {walk.group(1)} OK, {walk.group(2)} FAIL"
    return None


def release_body(v: str, kind: str, base: str, commit: str) -> str:
    """The pull request text: the changelog entries of the release, or the commits a hotfix holds."""
    lines = [f"{kind.capitalize()} {v} from {base[:8]}.", ""]
    folded = show(commit, f"changelog/releases/{v}.json")
    entries = json.loads(folded)["entries"] if folded else []
    if entries:
        lines += ["What's new:"] + [f"- {e['tag']}: {e['title']}" for e in entries]
    else:
        lines += ["No changelog entries; the version commit is the only change."]
    lines += [
        "",
        "Merging tags the merge commit, publishes the SDKs and images, and opens the merge-back into develop.",
    ]
    return "\n".join(lines)


def start(dry: bool, hotfix: bool) -> int:
    v = version()
    tags = tag_names()
    if hotfix:
        name = os.environ.get("NAME", "")
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name):
            raise Refusal("set NAME to what the hotfix changes, lowercase words joined by '-', e.g. NAME=login-loop")
        released = release_tags(tags)
        if not released:
            raise Refusal("no vX.Y.Z tag to cut the hotfix from")
        branch, kind = f"hotfix/{name}", "hotfix"
        base = run("git", "rev-list", "-n", "1", f"refs/tags/v{released[-1]}").strip()
        tip = "success"  # a tag was released from a green main
    else:
        run("git", "fetch", "--quiet", "--no-tags", "origin", "develop")
        branch, kind = f"release/{v}", "release"
        base = run("git", "rev-parse", "origin/develop").strip()
        tip = ci_status(base)
    problems = start_refusals(v, remote_branches(), tags, tip)
    if problems:
        raise Refusal("; ".join(problems))
    commit = with_version(base, v)
    title, text = f"{kind}: {v}", release_body(v, kind, base, commit)
    print(f"release: {branch} from {base[:8]} with one commit that sets {VERSION_FILE} and both SDK versions to {v}")
    if dry:
        print(f"\n{title}\n\n{text}\n\nrelease: dry run, nothing pushed or opened (DRY=0 does it)")
        return 0
    run("git", "push", "origin", f"{commit}:refs/heads/{branch}")
    print(run("gh", "pr", "create", "--base", "main", "--head", branch, "--title", title, "--body", text).strip())
    print(f"release: pushed {branch}; its push run tests the candidate. Next: make release-rc")
    return 0


def rc(dry: bool) -> int:
    branches = remote_branches()
    if len(branches) != 1:
        raise Refusal(f"expected one release or hotfix branch on origin, found {len(branches)}: {' '.join(branches)}")
    branch = branches[0]
    run("git", "fetch", "--quiet", "--no-tags", "origin", branch)
    sha = run("git", "rev-parse", f"origin/{branch}").strip()
    problem = version_problem(branch, sha) or staging_problem(sha)
    if problem:
        raise Refusal(problem)
    name = next_rc(tag_names(), file_version(sha))
    print(f"release: {name} on {branch} at {sha[:8]}")
    if dry:
        print("release: dry run, nothing tagged (DRY=0 does it)")
        return 0
    run("git", "tag", name, sha)
    run("git", "push", "origin", f"refs/tags/{name}")
    app = os.environ.get("STG_APP")
    print(
        f"release: pushed {name}; it publishes nothing. Staging runs it: "
        f"{f'https://{app}.fly.dev' if app else 'make stg-health'}"
    )
    return 0


def main() -> int:
    dry = os.environ.get("DRY", "1") != "0"
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if command == "check-version":
            branch = os.environ.get("BRANCH") or run("git", "rev-parse", "--abbrev-ref", "HEAD").strip()
            wrong = version_problem(branch, "HEAD")
            if wrong:
                raise Refusal(wrong)
            print(f"release: {branch}: {VERSION_FILE} says {file_version('HEAD')}")
            return 0
        if command == "latest":
            run("git", "fetch", "--quiet", "--tags", "origin", "main")
            tags = run("git", "tag", "--list", "v[0-9]*").split()

            def ok(t: str) -> bool:
                return (
                    subprocess.run(["git", "merge-base", "--is-ancestor", t, "origin/main"], check=False).returncode
                    == 0
                )

            found = latest_release(tags, ok)
            if not found:
                raise Refusal("no vX.Y.Z tag is reachable from origin/main")
            print(found)
            return 0
        if command == "proof":
            data = json.load(sys.stdin)
            problem = proof_problem(data["jobs"] if isinstance(data, dict) else data)
            if problem:
                raise Refusal(problem)
            print("release: release-proof of the push run succeeded")
            return 0
        if command == "finish":
            print(finish_tag(os.environ.get("BRANCH", ""), file_version(os.environ.get("SHA", "HEAD")), tag_names()))
            return 0
        if command in ("start", "hotfix-start"):
            return start(dry, hotfix=command == "hotfix-start")
        if command == "rc":
            return rc(dry)
        raise Refusal("usage: release.py start | hotfix-start | rc | finish | latest | proof | check-version")
    except Refusal as why:
        print(f"release: refused: {why}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
