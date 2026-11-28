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
  intake         takes every open feature PR into the train in one run (make release-intake): retargets them, merges
                 develop and each branch with its own merge commit in a worktree, resolves the mechanical conflicts,
                 runs make ci-local, pushes the train only when green, updates the release PR body and writes one JSON
                 report. Exit 0 green, 1 red or push refused, 2 a conflict a person has to resolve
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
import time
from pathlib import Path
from typing import Any

import check_migration_heads

# deploy/fly/stg_deploy.sh prints this line when the walk ran.
WALK = re.compile(r"click walk \((\d+) OK, (\d+) FAIL\)")
# The version install.sh installs from a checkout without a tag, and the image tag the release proof expects.
VERSION_FILE = "deploy/release/version"
TRAIN = os.environ.get("TRAIN") or "release/current"


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


def changelog_fold(sha: str, v: str) -> dict[str, Any]:
    """The plan folding the changelog fragments at sha into changelog/releases/<v>.json (changelog-fold.mjs)."""
    out = run("node", str(Path(__file__).with_name("changelog-fold.mjs")), "--release", v, "--ref", sha)
    return json.loads(out)


def with_version(sha: str, v: str) -> str:
    """sha itself when its version file says v and no changelog fragment is left, else a new commit on sha that sets the
    version and folds the fragments into the release's changelog file, made without a checkout."""
    fold = changelog_fold(sha, v)
    if file_version(sha) == v and not fold["remove"]:
        return sha
    if subprocess.run(["git", "var", "GIT_COMMITTER_IDENT"], capture_output=True, check=False).returncode != 0:
        raise Refusal("no git identity; set git user.name and user.email")
    blob = run("git", "hash-object", "-w", "--stdin", stdin=f"{v}\n").strip()
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(tmp, "index")}
        run("git", "read-tree", sha, env=env)
        run("git", "update-index", "--add", "--cacheinfo", f"100644,{blob},{VERSION_FILE}", env=env)
        for path, text in fold["files"].items():
            folded = run("git", "hash-object", "-w", "--stdin", stdin=text).strip()
            run("git", "update-index", "--add", "--cacheinfo", f"100644,{folded},{path}", env=env)
        for path in fold["remove"]:
            run("git", "update-index", "--force-remove", path, env=env)
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
    commit = with_version(sha, v)
    if commit == sha:
        print(f"release: {VERSION_FILE} on {branch} already says {v} and no changelog fragment is left")
        return 0
    print(
        f"release: {VERSION_FILE} on {branch} says {file_version(sha)}; one commit on {sha[:8]} sets it to {v}"
        f" and folds the changelog fragments into changelog/releases/{v}.json"
    )
    if dry:
        print("release: dry run, nothing pushed (DRY=0 does it)")
        return 0
    push(commit, branch)
    print("release: pushed; update the checkout with git pull --ff-only before make release-pr")
    return 0


# --- intake: every open feature PR into the train, one run ------------------------------------------------------------

DEFAULT_TRAIN = "release/1.1.0"  # until the rename to release/current
# What GitHub says when a retarget cannot happen, and what it means for the run: the PR is left alone, not failed.
RETARGET_REFUSALS = (
    ("no new commits between", "already in the train"),
    ("merge queue", "queued to develop; merge develop into the train after it lands"),
)
GENERATED = re.compile(r"(^|/)openapi\.json$|^sdk/.*/_?generated/")
GOLDEN = "deploy/database/golden/mssql/"
SETUP = "uv sync && CI=true pnpm install --frozen-lockfile"


def attempt(*cmd: str, cwd: str | Path | None = None) -> tuple[int, str]:
    done = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=cwd)
    return done.returncode, (done.stdout + done.stderr).strip()


def intake_train() -> str:
    return os.environ.get("TRAIN") or ("release/current" if remote_has("release/current") else DEFAULT_TRAIN)


def retarget(number: int, train: str) -> str | None:
    """None when the PR now targets the train, else why it was left where it is (REST: `gh pr edit` fails)."""
    try:
        run(
            "gh",
            "api",
            "-X",
            "PATCH",
            f"repos/{{owner}}/{{repo}}/pulls/{number}",
            "-f",
            f"base={train}",
            "--jq",
            ".base.ref",
        )
    except Refusal as e:
        for needle, why in RETARGET_REFUSALS:
            if needle in str(e):
                return why
        return f"retarget refused: {str(e)[:160]}"
    return None


def stock(train: str, picks: list[int]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(the PRs to take in, in order; the ones left out with why). Oldest first, or the order PRS names."""
    fields = "number,headRefName,baseRefName,isDraft,title,createdAt"
    open_prs = gh_json("pr", "list", "--state", "open", "--json", fields, "--limit", "100")
    take: list[dict[str, Any]] = []
    left: list[dict[str, Any]] = []
    for pr in open_prs:
        if picks and pr["number"] not in picks:
            continue
        head, base = pr["headRefName"], pr["baseRefName"]
        why = None
        if head == train:
            why = "the release pull request itself"
        elif head.startswith("dependabot/"):
            why = "dependabot is not part of a release"
        elif pr["isDraft"]:
            why = "draft"
        elif base not in (train, "develop"):
            why = f"targets {base}, not develop or the train"
        if why:
            left.append({"pr": pr["number"], "branch": head, "reason": why})
        else:
            take.append(pr)
    take.sort(key=lambda p: picks.index(p["number"]) if picks else p["createdAt"])
    return take, left


def cancel_old_runs(branches: set[str]) -> list[int]:
    """Cancel the CI runs the old base started for these branches; a merge queue run (gh-readonly-queue/) never."""
    cancelled: list[int] = []
    for status in ("in_progress", "queued"):
        for found in gh_json("run", "list", "--status", status, "--json", "databaseId,headBranch", "--limit", "100"):
            queued = found["headBranch"].startswith("gh-readonly-queue/")
            if (
                found["headBranch"] in branches
                and not queued
                and attempt("gh", "run", "cancel", str(found["databaseId"]))[0] == 0
            ):
                cancelled.append(found["databaseId"])
    return cancelled


def chain_files(wt: Path) -> dict[Path, dict[str, tuple[Path, list[str]]]]:
    out: dict[Path, dict[str, tuple[Path, list[str]]]] = {}
    for versions in check_migration_heads.chains(wt):
        found = {}
        for f in sorted(versions.glob("*.py")):
            m = check_migration_heads.read(f)
            if m:
                found[m[0]] = (f, m[1])
        out[versions] = found
    return out


def fix_heads(wt: Path, before: dict[Path, set[str]]) -> list[str]:
    """Re-point the merged-in chain's first revision at the train's head wherever the merge left two heads. Returns what
    it did; raises Refusal when a chain has two heads it cannot join without judgement."""
    done: list[str] = []
    for versions, revs in chain_files(wt).items():
        heads = check_migration_heads.heads(versions)
        if len(heads) < 2:
            continue
        old = before.get(versions, set())
        new = set(revs) - old
        roots = [r for r in new if any(d not in new for d in revs[r][1])]
        ours = [h for h in heads if h in old]
        if len(roots) != 1 or len(ours) != 1:
            raise Refusal(
                f"{versions.relative_to(wt)} has heads {', '.join(heads)} that are not one merged chain on top of one"
            )
        path = revs[roots[0]][0]
        text = path.read_text()
        text = re.sub(r"^(down_revision\b[^=\n]*=\s*).*$", rf'\g<1>"{ours[0]}"', text, count=1, flags=re.M)
        text = re.sub(r"^(Revises:\s*).*$", rf"\g<1>{ours[0]}", text, count=1, flags=re.M)
        path.write_text(text)
        run("git", "add", str(path), cwd=wt)
        if len(check_migration_heads.heads(versions)) != 1:
            raise Refusal(f"{versions.relative_to(wt)} still has two heads after re-pointing {roots[0]}")
        done.append(f"{path.relative_to(wt)}: down_revision -> {ours[0]}")
    return done


def stage(wt: Path, n: int, path: str) -> str:
    code, out = attempt("git", "show", f":{n}:{path}", cwd=wt)
    return out if code == 0 else ""


def union_json_list(wt: Path, path: str) -> bool:
    try:
        ours, theirs = json.loads(stage(wt, 2, path)), json.loads(stage(wt, 3, path))
    except json.JSONDecodeError:
        return False
    if not isinstance(ours, list) or not isinstance(theirs, list):
        return False
    (wt / path).write_text(json.dumps(ours + [t for t in theirs if t not in ours], indent=2, ensure_ascii=False) + "\n")
    return True


def union_text(wt: Path, path: str) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        files = []
        for n in (2, 1, 3):  # ours, base, theirs
            f = Path(tmp) / f"s{n}"
            f.write_text(stage(wt, n, path))
            files.append(str(f))
        code, merged = attempt("git", "merge-file", "--union", "-p", *files)
        if code < 0 or code > 127:
            return False
    (wt / path).write_text(merged + "\n" if merged and not merged.endswith("\n") else merged)
    return True


def regenerate(wt: Path, kind: str) -> tuple[bool, str]:
    steps = {
        "openapi": [("make", "-C", str(wt), "openapi")],
        "golden": [("make", "-C", str(wt), "db-ddl-golden")],
        "uvlock": [("uv", "lock"), ("make", "-C", str(wt), "sbom")],
        "pnpm": [("pnpm", "install", "--lockfile-only")],
    }[kind]
    for cmd in steps:
        code, out = attempt(*cmd, cwd=wt)
        if code != 0:
            return False, f"{' '.join(cmd[:3])} failed: {out[-300:]}"
    adds = {
        "openapi": ["services", "sdk"],
        "golden": ["deploy/database/golden"],
        "uvlock": ["uv.lock", "docs/architecture/dependencies.md"],
        "pnpm": ["pnpm-lock.yaml"],
    }[kind]
    run("git", "add", "-A", *[a for a in adds if (wt / a).exists()], cwd=wt)
    return True, ""


def kind_of(path: str) -> str | None:
    if GENERATED.search(path):
        return "openapi"
    if path.startswith(GOLDEN):
        return "golden"
    if path in ("uv.lock", "docs/architecture/dependencies.md"):
        return "uvlock"
    if path == "pnpm-lock.yaml":
        return "pnpm"
    if path == "roadmap.json" or (path.startswith("changelog/") and path.endswith(".json")):
        return "json-list"
    if path.endswith("api-changes.md"):
        return "union"
    return None


def resolve(wt: Path, conflicted: list[str]) -> tuple[list[str], list[str]]:
    """(the files left for a person, what was resolved and how). Generated files take our side and are regenerated."""
    left: list[str] = []
    done: list[str] = []
    regen: set[str] = set()
    for path in conflicted:
        kind = kind_of(path)
        ok = False
        if kind in ("openapi", "golden", "uvlock", "pnpm"):
            ok = attempt("git", "checkout", "--ours", "--", path, cwd=wt)[0] == 0
            if ok:
                regen.add(kind)
        elif kind == "json-list":
            ok = union_json_list(wt, path)
        elif kind == "union":
            ok = union_text(wt, path)
        if ok:
            if kind in ("json-list", "union"):
                run("git", "add", path, cwd=wt)
            done.append(f"{path}: {'regenerated' if kind in ('openapi', 'golden', 'uvlock', 'pnpm') else 'kept both'}")
        else:
            left.append(path)
    for kind in sorted(regen, key=["openapi", "golden", "uvlock", "pnpm"].index):
        ok, why = regenerate(wt, kind)
        if not ok:
            left += [p for p in conflicted if kind_of(p) == kind]
            done = [d for d in done if kind_of(d.split(":")[0]) != kind]
            print(f"release: {why}", file=sys.stderr)
    return left, done


def merge_in(wt: Path, ref: str, subject: str, body: str) -> dict[str, Any]:
    """One `--no-ff` merge commit of ref, mechanical conflicts resolved; a merge that needs a person is aborted."""
    before = {v: set(r) for v, r in chain_files(wt).items()}
    code, out = attempt("git", "merge", "--no-ff", "--no-commit", ref, cwd=wt)
    if attempt("git", "rev-parse", "-q", "--verify", "MERGE_HEAD", cwd=wt)[0] != 0:
        if code == 0:
            return {"status": "merged", "sha": None, "resolved": [], "note": "nothing new"}
        return {"status": "conflict", "files": [], "reason": out[-300:]}
    conflicted = run("git", "diff", "--name-only", "--diff-filter=U", cwd=wt).split()
    resolved: list[str] = []
    try:
        if conflicted:
            left, resolved = resolve(wt, conflicted)
            if left:
                attempt("git", "merge", "--abort", cwd=wt)
                return {
                    "status": "conflict",
                    "files": left,
                    "reason": "not a mechanical conflict",
                    "resolved": resolved,
                }
        resolved += fix_heads(wt, before)
    except Refusal as why:
        attempt("git", "merge", "--abort", cwd=wt)
        return {"status": "conflict", "files": conflicted, "reason": str(why)}
    message = (
        subject
        + "\n\n"
        + body
        + ("\n\nResolved by make release-intake:\n" + "\n".join(f"- {r}" for r in resolved) if resolved else "")
        + "\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".msg", delete=False) as f:
        f.write(message)
    # The repo's own hooks, as install-hooks.sh links them: a core.hooksPath that adds a trailer to every message would
    # make the public-view check refuse a merge commit this script has no way to reword.
    hooks = Path(run("git", "rev-parse", "--path-format=absolute", "--git-common-dir", cwd=wt).strip()) / "hooks"
    try:
        run("git", "-c", f"core.hooksPath={hooks}", "commit", "-q", "-F", f.name, cwd=wt)
    except Refusal as why:
        attempt("git", "merge", "--abort", cwd=wt)
        return {"status": "conflict", "files": [], "reason": f"the commit was refused: {str(why)[-300:]}"}
    finally:
        os.unlink(f.name)
    return {"status": "merged", "sha": run("git", "rev-parse", "HEAD", cwd=wt).strip(), "resolved": resolved}


def intake_report_dir(root: str) -> Path:
    given = os.environ.get("REPORT")
    path = Path(given) if given else Path(root) / ".run/release-intake" / time.strftime("%Y%m%d-%H%M%S") / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def update_release_pr(train: str, sha: str, check: str) -> str:
    prs = gh_json("pr", "list", "--base", "develop", "--head", train, "--state", "open", "--json", "number,title")
    if not prs:
        return "no release pull request is open"
    found = re.match(r"release: (\d+\.\d+\.\d+) into develop", prs[0]["title"])
    v = found.group(1) if found else file_version(sha).strip()
    run("git", "fetch", "--quiet", "--no-tags", "origin", train)
    body = release_body(v, train, sha, "release", check)
    run("gh", "api", "-X", "PATCH", f"repos/{{owner}}/{{repo}}/pulls/{prs[0]['number']}", "-f", f"body={body}")
    return f"release pull request #{prs[0]['number']} body updated"


def ci_report(path: Path, rerun: str | None, wt: Path) -> tuple[int, dict[str, Any] | None]:
    cmd = ["make", "-C", str(wt), "ci-local", "BASE=origin/develop", f"OUT={path}"] + (
        [f"RERUN={rerun}"] if rerun else []
    )
    code = subprocess.run(cmd, check=False).returncode
    try:
        return code, json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return code, None


def reds_of(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    if data is None:
        return [{"job": "ci-local", "tests": [], "log": "", "tail": "ci-local wrote no report"}]
    return [
        {"job": j["label"], "tests": j["failing_tests"], "log": j["log"], "tail": j["tail"]}
        for j in data["jobs"]
        if j["status"] == "failed"
    ]


def rerun_source(given: str | None) -> str | None:
    """RERUN names an intake report or a ci-local one; ci-local wants its own."""
    if not given:
        return None
    data = json.loads(Path(given).read_text())
    return data.get("ci_local", {}).get("report", given) if "ci_local" in data else given


def summary(rep: dict[str, Any]) -> str:
    lines = [f"release-intake {rep['train']}: {rep['result']}"]
    lines.append(f"  merged {len(rep['merged'])}: " + ", ".join(f"#{m['pr']}" for m in rep["merged"]))
    for s in rep["skipped"]:
        lines.append(f"  skipped #{s['pr']}: {s['reason']}")
    for c in rep["conflicts"]:
        lines.append(f"  conflict #{c['pr']} ({c['branch']}): {', '.join(c['files']) or c['reason']}")
    for r in rep["red"]:
        lines.append(f"  red {r['job']}: {', '.join(r['tests'][:5]) or 'see ' + r['log']}")
    lines.append(f"  push: {rep['push']}")
    lines.append(f"  worktree: {rep['worktree'] or 'removed'}")
    return "\n".join(lines)


def fetch_heads(prs: list[dict[str, Any]]) -> None:
    refs = [f"+refs/heads/{p['headRefName']}:refs/remotes/origin/{p['headRefName']}" for p in prs]
    run("git", "fetch", "--quiet", "--no-tags", "origin", *refs)


def plan(take: list[dict[str, Any]], left: list[dict[str, Any]], train: str) -> None:
    """DRY=1: what a run would do. Fetching branches reads the remote; nothing is written to it."""
    fetch_heads(take)
    for p in take:
        if is_ancestor(f"origin/{p['headRefName']}", f"origin/{train}"):
            note = "already in the train"
        else:
            note = "merge" if p["baseRefName"] == train else f"retarget from {p['baseRefName']}, then merge"
        print(f"release-intake: #{p['number']} {p['headRefName']}: {note}")
    for s in left:
        print(f"release-intake: #{s['pr']} {s['branch']}: skipped, {s['reason']}")
    print(f"release-intake: dry run on {train}; nothing retargeted, cancelled, merged or pushed (DRY=0 does it)")


def take_in(rep: dict[str, Any], wt: Path, take: list[dict[str, Any]], train: str) -> None:
    """Retarget, cancel the old base's runs, then merge develop and each branch into the worktree, oldest first."""
    ready = []
    for p in take:
        why = retarget(p["number"], train) if p["baseRefName"] != train else None
        if why:
            rep["skipped"].append({"pr": p["number"], "branch": p["headRefName"], "reason": why})
            continue
        ready.append(p)
        if p["baseRefName"] != train:
            rep["retargeted"].append(p["number"])
    rep["cancelled_runs"] = cancel_old_runs({p["headRefName"] for p in ready})
    fetch_heads(ready)
    run("git", "worktree", "add", "--detach", str(wt), f"origin/{train}")
    subprocess.run(os.environ.get("INTAKE_SETUP", SETUP), shell=True, cwd=wt, check=False)
    rep["start"] = run("git", "rev-parse", "HEAD", cwd=wt).strip()
    if is_ancestor("origin/develop", f"origin/{train}"):
        rep["develop"] = "already in the train"
    else:
        got = merge_in(wt, "origin/develop", f"Merge branch 'develop' into {train}", "Bring develop into the train.")
        rep["develop"] = got["status"]
        if got["status"] == "conflict":
            # Every branch merges on top of develop; with it unresolved there is no base to merge them onto.
            rep["conflicts"].append({"pr": 0, "branch": "develop", "files": got["files"], "reason": got["reason"]})
            return
    for p in ready:
        ref = f"origin/{p['headRefName']}"
        if attempt("git", "merge-base", "--is-ancestor", ref, "HEAD", cwd=wt)[0] == 0:
            rep["skipped"].append({"pr": p["number"], "branch": p["headRefName"], "reason": "already in the train"})
            continue
        got = merge_in(wt, ref, f"Merge pull request #{p['number']} from origin/{p['headRefName']}", p["title"])
        if got["status"] == "conflict":
            rep["conflicts"].append(
                {"pr": p["number"], "branch": p["headRefName"], "files": got["files"], "reason": got["reason"]}
            )
        else:
            rep["merged"].append(
                {"pr": p["number"], "branch": p["headRefName"], "sha": got["sha"], "resolved": got.get("resolved", [])}
            )


def prove_and_push(rep: dict[str, Any], wt: Path, train: str, report_path: Path) -> None:
    subprocess.run(os.environ.get("INTAKE_SETUP", SETUP), shell=True, cwd=wt, check=False)
    head = run("git", "rev-parse", "HEAD", cwd=wt).strip()
    ci_out = report_path.with_name("ci-local.json")
    ci_code, data = ci_report(ci_out, rerun_source(os.environ.get("RERUN")), wt)
    rep["ci_local"] = {"report": str(ci_out), "exit": ci_code, "summary": data["summary"] if data else None}
    rep["red"] = reds_of(data) if ci_code != 0 or data is None else []
    if rep["red"]:
        rep["push"] = "not pushed: ci-local is red"
        return
    sent, why = attempt("git", "push", "origin", f"{head}:refs/heads/{train}", cwd=wt)
    rep["push"] = "pushed" if sent == 0 else f"not pushed: {why[-200:]}"
    if sent == 0:
        rep["pr"] = update_release_pr(train, head, f"make ci-local green at {head[:8]} ({rep['ci_local']['summary']})")


def intake(dry: bool) -> int:
    root = run("git", "rev-parse", "--show-toplevel").strip()
    train = intake_train()
    picks = [int(n) for n in re.findall(r"\d+", os.environ.get("PRS", ""))]
    slug = re.sub(r"[^a-z0-9]+", "-", train.lower()).strip("-")
    wt = Path(os.environ.get("INTAKE_DIR") or Path(root).parent / "ops-ai-worktrees" / f"intake-{slug}")
    resume = bool(os.environ.get("RESUME") or os.environ.get("RERUN"))
    if wt.exists() and not resume:
        raise Refusal(
            f"{wt} is left from an earlier run: finish it with RESUME=1 (or RERUN=<report>), "
            "or remove it with git worktree remove"
        )
    if resume and not wt.exists():
        raise Refusal(f"RESUME and RERUN need the intake worktree {wt}, which is not there; run without them first")
    if not remote_has(train):
        raise Refusal(f"{train} is not on origin")
    run("git", "fetch", "--quiet", "--no-tags", "origin", train)
    report_path = intake_report_dir(root)
    rep: dict[str, Any] = {
        "train": train, "dry": dry, "merged": [], "skipped": [], "conflicts": [], "red": [], "retargeted": [],
        "cancelled_runs": [], "develop": "", "ci_local": {}, "push": "not pushed", "pr": "", "worktree": str(wt),
    }  # fmt: skip
    if not resume:
        take, rep["skipped"] = stock(train, picks)
        if dry:
            plan(take, rep["skipped"], train)
            return 0
        take_in(rep, wt, take, train)
    develop_blocked = any(c["branch"] == "develop" for c in rep["conflicts"])
    nothing_new = not resume and not rep["conflicts"] and not rep["merged"] and rep["develop"] != "merged"
    if nothing_new:
        rep["push"] = "not pushed: nothing new"
    elif not develop_blocked:
        prove_and_push(rep, wt, train, report_path)
    rep["head"] = run("git", "rev-parse", "HEAD", cwd=wt).strip()
    if rep["conflicts"]:
        code = 2
    elif rep["red"] or not (nothing_new or rep["push"] == "pushed"):
        code = 1
    else:
        code = 0
    if code == 0 and attempt("git", "worktree", "remove", str(wt))[0] == 0:
        rep["worktree"] = ""
    rep["result"] = {0: "green", 1: "red", 2: "conflicts need a model"}[code]
    rep["exit"] = code
    report_path.write_text(json.dumps(rep, indent=2) + "\n")
    print(summary(rep))
    print(f"release-intake: report {report_path}")
    return code


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
        commands = {"intake": intake, "cut": cut, "hotfix-cut": hotfix_cut, "pr": pr, "set-version": set_version}
        if command in commands:
            return commands[command](dry)
        raise Refusal("usage: release.py intake | cut | hotfix-cut | pr | set-version | check-version (V=X.Y.Z)")
    except Refusal as why:
        print(f"release: refused: {why}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
