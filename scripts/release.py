#!/usr/bin/env python3
"""The release-train commands behind `make release-cut`, `release-pr`, `release-version` and `hotfix-cut`
(docs/deploy/release.md). V=X.Y.Z names the version; DRY=1 (the default) prints what would happen and changes nothing.

  cut            fast-forwards release/current to origin/develop after a release landed, and creates the branch when
                 it is missing; refuses when the train holds commits develop lacks
  hotfix-cut     hotfix/<what> from the tag vFROM (default: the newest vX.Y.Z tag), pushed, with one commit on top that
                 sets deploy/release/version to V
  pr             release/current (or hotfix/<what> with HOTFIX=) into develop, titled `release: V into develop`
                 (`hotfix: V into develop`). A train needs: develop merged in, a clean checkout at the train's head,
                 deploy/release/version equal to V, and `make ci-local` green on it. A hotfix, cut from a tag, needs
                 ci.yml and the staging deploy with its click walk green on its head, because a push to a hotfix
                 branch still runs both
  set-version    one commit on the train (or hotfix) that sets deploy/release/version to V, pushed without force
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
from typing import Any

# deploy/fly/stg_deploy.sh prints this line when the walk ran.
WALK = re.compile(r"click walk \((\d+) OK, (\d+) FAIL\)")
# The version install.sh installs from a checkout without a tag, and the image tag the release proof expects.
VERSION_FILE = "deploy/release/version"
TRAIN = os.environ.get("TRAIN") or "release/current"


class Refusal(Exception):
    pass


def run(*cmd: str, stdin: str | None = None, env: dict[str, str] | None = None) -> str:
    done = subprocess.run(cmd, capture_output=True, text=True, check=False, input=stdin, env=env)
    if done.returncode != 0:
        raise Refusal(f"{' '.join(cmd[:3])} failed: {(done.stderr or done.stdout).strip()}")
    return done.stdout


def gh_json(*args: str) -> Any:
    return json.loads(run("gh", *args))


def version() -> str:
    v = os.environ.get("V", "")
    if not re.fullmatch(r"\d+\.\d+\.\d+", v):
        raise Refusal("set V to the version, for example V=1.2.0")
    return v


def hotfix_name() -> str:
    name = os.environ.get("HOTFIX", "")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name):
        raise Refusal(
            "set HOTFIX to what the hotfix changes, lowercase words joined by '-', for example HOTFIX=login-loop"
        )
    return name


def remote_has(ref: str) -> bool:
    return bool(run("git", "ls-remote", "--heads", "origin", ref).strip())


def is_ancestor(older: str, newer: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", older, newer], check=False).returncode == 0


def file_version(ref: str) -> str:
    try:
        return run("git", "show", f"{ref}:{VERSION_FILE}").strip()
    except Refusal:
        return "missing"


def version_problem(branch: str, ref: str, want: str | None = None) -> str | None:
    """Why ref's version file does not match, or None. `want` is the release's version; with none, only a branch named
    release/X.Y.Z (the old scheme, which a release-proof push still sees) has a version to match."""
    if want is None:
        named = re.fullmatch(r"release/(\d+\.\d+\.\d+)", branch)
        if not named:
            return None
        want = named.group(1)
    have = file_version(ref)
    if have != want:
        return f"{VERSION_FILE} on {branch} says {have}, not {want}; make release-version V={want} DRY=0 sets it"
    return None


def with_version(sha: str, v: str) -> str:
    """sha itself when its version file says v, else a new commit on sha that sets it, made without a checkout."""
    if file_version(sha) == v:
        return sha
    if subprocess.run(["git", "var", "GIT_COMMITTER_IDENT"], capture_output=True, check=False).returncode != 0:
        raise Refusal("no git identity; set git user.name and user.email")
    blob = run("git", "hash-object", "-w", "--stdin", stdin=f"{v}\n").strip()
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(tmp, "index")}
        run("git", "read-tree", sha, env=env)
        run("git", "update-index", "--add", "--cacheinfo", f"100644,{blob},{VERSION_FILE}", env=env)
        tree = run("git", "write-tree", env=env).strip()
    return run("git", "commit-tree", tree, "-p", sha, "-m", f"chore(release): set the version to {v}").strip()


def runs_for(workflow: str, sha: str) -> list[dict[str, Any]]:
    fields = "databaseId,conclusion,status"
    try:
        return gh_json("run", "list", "--workflow", workflow, "--commit", sha, "--json", fields, "--limit", "10")
    except Refusal as e:
        # GitHub answers 404 for a workflow file it has never run (deploy-staging.yml until someone runs it by hand).
        if "HTTP 404" in str(e):
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
    """Why the staging deploy of sha does not count, or None when it succeeded with a clean click walk.

    The deploy is the `staging / deploy` job of the ci.yml run a push to the branch started, or the `deploy` job of a
    deploy-staging.yml run started by hand (make stg-deploy-ci).
    """
    deploys: list[dict[str, Any]] = []
    for workflow, job_name in (("ci.yml", "staging / deploy"), ("deploy-staging.yml", "deploy")):
        for found in runs_for(workflow, sha):
            jobs = gh_json("run", "view", str(found["databaseId"]), "--json", "jobs")["jobs"]
            deploys += [j for j in jobs if j.get("name") == job_name]
    if not deploys:
        return (
            f"no staging deploy of {sha[:8]} (job 'staging / deploy' of ci.yml, or deploy-staging.yml): "
            "push the branch or run make stg-deploy-ci REF=<branch>"
        )
    done = [j for j in deploys if j.get("conclusion") == "success"]
    if not done:
        return f"the staging deploy of {sha[:8]} is {deploys[0].get('conclusion') or 'not finished'}, not success"
    # The jobs API, because `gh run view --job --log` prints nothing for a job in a called workflow (staging / deploy).
    log = run("gh", "api", f"repos/{{owner}}/{{repo}}/actions/jobs/{done[0]['databaseId']}/logs")
    walk = WALK.search(log)
    if "click walk skipped" in log or not walk:
        return f"the staging deploy of {sha[:8]} did not run the click walk"
    if walk.group(2) != "0" or walk.group(1) == "0":
        return f"the click walk on staging for {sha[:8]} was {walk.group(1)} OK, {walk.group(2)} FAIL"
    return None


def merged_since_develop(head: str) -> list[str]:
    out = run("git", "log", "--first-parent", "--format=%s%x1f%b%x1e", f"origin/develop..{head}")
    lines: list[str] = []
    for entry in filter(None, (e.strip() for e in out.split("\x1e"))):
        subject, _, body = entry.partition("\x1f")
        number = re.match(r"Merge pull request #(\d+)", subject)
        title = body.strip().splitlines()[0] if body.strip() else subject
        lines.append(f"#{number.group(1)} {title}" if number else subject)
    return lines


def breaking_changes(head: str) -> list[str]:
    out = run("git", "log", "--format=%s%x1f%B%x1e", f"origin/develop..{head}")
    found: list[str] = []
    for entry in filter(None, (e.strip() for e in out.split("\x1e"))):
        subject, _, body = entry.partition("\x1f")
        if re.match(r"^\w+(\([^)]*\))?!:", subject) or "BREAKING CHANGE" in body:
            found.append(subject)
    return found


def sdk_versions(ref: str) -> dict[str, tuple[str, str]]:
    py = run("git", "show", f"{ref}:sdk/python/pyproject.toml")
    ts = json.loads(run("git", "show", f"{ref}:sdk/typescript/package.json"))
    name = re.search(r'^name = "(.*)"', py, re.M)
    ver = re.search(r'^version = "(.*)"', py, re.M)
    return {
        "python": (name.group(1) if name else "ops-ai", ver.group(1) if ver else "?"),
        "typescript": (ts["name"], ts["version"]),
    }


def release_body(v: str, branch: str, sha: str, kind: str, check: str) -> str:
    head = f"origin/{branch}"
    merged = merged_since_develop(head)
    if not merged:
        raise Refusal(f"{branch} has nothing that origin/develop lacks")
    breaking = breaking_changes(head)
    # The merge base, because a hotfix is cut from a tag and develop may hold SDK changes it does not.
    base = run("git", "merge-base", "origin/develop", head).strip()
    sdk_changed = bool(run("git", "diff", "--name-only", base, head, "--", "sdk").strip())
    before, after = sdk_versions(base), sdk_versions(head)
    lines = [f"Releases {branch} at {sha[:8]} into develop.", "", f"Checked: {check}", "", "Merged since develop:"]
    lines += [f"- {m}" for m in merged]
    breaking_text = "; ".join(breaking) if breaking else "none marked in commit messages (check the PRs above)"
    lines += ["", f"Breaking changes: {breaking_text}"]
    lines += ["", f"sdk/**: {'changed' if sdk_changed else 'unchanged'}"]
    lines[-1] += f" (sdk-publish.yml {'runs' if sdk_changed else 'does not run'})"
    for sdk in ("python", "typescript"):
        name, old = before[sdk]
        new = after[sdk][1]
        verdict = "new version, sdk-publish.yml publishes it" if old != new else "same version, nothing is published"
        lines.append(f"- {sdk} {name} {old} -> {new}: {verdict}")
    lines += [
        "",
        f"Queue it with a merge commit. release-tag.yml then tags the develop merge v{v} and fast-forwards main to it; "
        f"the {kind} needs no pull request to main and no back-merge.",
    ]
    return "\n".join(lines)


def open_pr(head: str, base: str) -> dict[str, Any] | None:
    prs = gh_json("pr", "list", "--base", base, "--head", head, "--state", "open", "--json", "number,url,title")
    return prs[0] if prs else None


def create_pr(dry: bool, head: str, base: str, title: str, text: str) -> int:
    existing = open_pr(head, base)
    if existing:
        print(
            f"release: a PR from {head} is already open: #{existing['number']} {existing['title']}\n{existing['url']}"
        )
        return 0
    if dry:
        print(f"{title}\n\n{text}\n\nrelease: dry run, nothing opened (DRY=0 opens it)")
        return 0
    print(run("gh", "pr", "create", "--base", base, "--head", head, "--title", title, "--body", text).strip())
    return 0


def push(sha: str, branch: str) -> None:
    """A plain push: git itself refuses anything that is not a fast-forward."""
    run("git", "push", "origin", f"{sha}:refs/heads/{branch}")


def cut(dry: bool) -> int:
    develop = run("git", "rev-parse", "origin/develop").strip()
    if not remote_has(TRAIN):
        print(f"release: {TRAIN} is missing; it is created at origin/develop {develop[:8]}")
    else:
        run("git", "fetch", "--quiet", "--no-tags", "origin", TRAIN)
        train = run("git", "rev-parse", f"origin/{TRAIN}").strip()
        if train == develop:
            print(f"release: {TRAIN} is already at origin/develop {develop[:8]}")
            return 0
        if not is_ancestor(train, develop):
            raise Refusal(
                f"{TRAIN} at {train[:8]} holds commits origin/develop lacks, so the release has not landed in develop; "
                "a fast-forward would drop them"
            )
        print(f"release: {TRAIN} {train[:8]} -> origin/develop {develop[:8]} (fast-forward)")
    if dry:
        print("release: dry run, nothing pushed (DRY=0 does it)")
        return 0
    push(develop, TRAIN)
    print(f"release: {TRAIN} is at {develop[:8]}; pull requests into it need no retarget")
    return 0


def hotfix_cut(dry: bool) -> int:
    v = version()
    branch = f"hotfix/{hotfix_name()}"
    if remote_has(branch):
        raise Refusal(f"{branch} is already on origin")
    run("git", "fetch", "--quiet", "--tags", "origin")
    tags = run("git", "tag", "--list", "v[0-9]*.[0-9]*.[0-9]*", "--sort=-v:refname").split()
    start = os.environ.get("FROM") or (tags[0] if tags else "")
    if not start:
        raise Refusal("no vX.Y.Z tag to cut from; set FROM=<tag>")
    sha = run("git", "rev-list", "-n", "1", f"refs/tags/{start}").strip()
    print(f"release: {branch} from tag {start} at {sha[:8]}, version file set to {v}")
    if dry:
        print("release: dry run, nothing created (DRY=0 does it)")
        return 0
    push(with_version(sha, v), branch)
    print(f"release: pushed {branch}; fix it, then make release-pr V={v} HOTFIX={branch.split('/', 1)[1]}")
    return 0


def local_check(branch: str, sha: str, dry: bool) -> str:
    """`make ci-local` on the train head, the one real check left once pushes to release/* run no CI. It beats a staging
    deploy by hand: it needs no owner OK, no shared staging and no wait for the freeze, and it runs the same jobs the
    merge queue will, so a red result is found before the queue spends a run."""
    here = run("git", "rev-parse", "HEAD").strip()
    if here != sha:
        raise Refusal(
            f"this checkout is at {here[:8]}, not at origin/{branch} {sha[:8]}; check out the train head first"
        )
    if run("git", "status", "--porcelain").strip():
        raise Refusal("the checkout has uncommitted changes; ci-local reads committed changes")
    if dry:
        return "make ci-local not run (dry run)"
    print(f"release: make ci-local on {branch} at {sha[:8]} against origin/develop")
    root = run("git", "rev-parse", "--show-toplevel").strip()
    if subprocess.run(["make", "-C", root, "ci-local", "BASE=origin/develop"], check=False).returncode != 0:
        raise Refusal(f"make ci-local is red on {branch} at {sha[:8]}; fix it on the branch")
    return f"make ci-local green on {branch} at {sha[:8]}"


def pr(dry: bool) -> int:
    v = version()
    hotfix = bool(os.environ.get("HOTFIX"))
    branch = f"hotfix/{hotfix_name()}" if hotfix else TRAIN
    if not remote_has(branch):
        raise Refusal(f"{branch} is not on origin")
    run("git", "fetch", "--quiet", "--no-tags", "origin", branch)
    kind = "hotfix" if hotfix else "release"
    title = f"{kind}: {v} into develop"
    if open_pr(branch, "develop"):
        return create_pr(dry, branch, "develop", "", "")
    sha = run("git", "rev-parse", f"origin/{branch}").strip()
    wrong = version_problem(branch, sha, v)
    if wrong:
        raise Refusal(wrong)
    if not hotfix and not is_ancestor("origin/develop", sha):
        raise Refusal(f"{branch} lacks commits of origin/develop; merge develop into it first")
    if hotfix:
        status = ci_status(sha)
        if status != "success":
            raise Refusal(f"ci.yml on {branch} at {sha[:8]} is {status}, not success")
        problem = staging_problem(sha)
        if problem:
            raise Refusal(problem)
        check = f"ci.yml and the staging deploy with its click walk green at {sha[:8]}"
    else:
        check = local_check(branch, sha, dry)
    return create_pr(dry, branch, "develop", title, release_body(v, branch, sha, kind, check))


def set_version(dry: bool) -> int:
    v = version()
    hotfix = bool(os.environ.get("HOTFIX"))
    branch = f"hotfix/{hotfix_name()}" if hotfix else TRAIN
    if not remote_has(branch):
        raise Refusal(f"{branch} is not on origin")
    run("git", "fetch", "--quiet", "--no-tags", "origin", branch)
    sha = run("git", "rev-parse", f"origin/{branch}").strip()
    if file_version(sha) == v:
        print(f"release: {VERSION_FILE} on {branch} already says {v}")
        return 0
    print(f"release: {VERSION_FILE} on {branch} says {file_version(sha)}; one commit on {sha[:8]} sets it to {v}")
    if dry:
        print("release: dry run, nothing pushed (DRY=0 does it)")
        return 0
    push(with_version(sha, v), branch)
    print("release: pushed; update the checkout with git pull --ff-only before make release-pr")
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
        run("git", "fetch", "--quiet", "origin", "develop")
        commands = {"cut": cut, "hotfix-cut": hotfix_cut, "pr": pr, "set-version": set_version}
        if command in commands:
            return commands[command](dry)
        raise Refusal("usage: release.py cut | hotfix-cut | pr | set-version | check-version (V=X.Y.Z)")
    except Refusal as why:
        print(f"release: refused: {why}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
