#!/usr/bin/env python3
"""The gitflow release commands behind `make release-cut`, `release-pr`, `release-back-merge` and `hotfix-cut`
(docs/deploy/release.md). V=X.Y.Z names the version; DRY=1 (the default) prints what would happen and changes nothing.

  cut            release/V from origin/develop, pushed; the push deploys it to staging (ci.yml, job staging). When
                 deploy/release/version is not V, the branch gets one commit on top that sets it
  hotfix-cut     hotfix/V from origin/main, pushed, with the same version commit; the push deploys it to staging
  pr             release/V (or hotfix/V) into main; refuses unless its deploy/release/version is V and ci.yml and the
                 staging deploy with its click walk succeeded on the branch head; an open PR from that branch is
                 printed instead of a second one
  back-merge     main into develop, after the tag vV exists on main
  check-version  exits 1 when BRANCH (default: the checked-out branch) is release/X.Y.Z or hotfix/X.Y.Z and HEAD's
                 deploy/release/version is not X.Y.Z (ci.yml, job release-proof)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

# deploy/fly/stg_deploy.sh prints this line when the walk ran.
WALK = re.compile(r"click walk \((\d+) OK, (\d+) FAIL\)")
# The version install.sh installs from a checkout without a tag, and the image tag the release proof expects.
VERSION_FILE = "deploy/release/version"


class Refusal(Exception):
    pass


def run(*cmd: str, stdin: str | None = None, env: dict[str, str] | None = None) -> str:
    done = subprocess.run(cmd, capture_output=True, text=True, check=False, input=stdin, env=env)
    if done.returncode != 0:
        raise Refusal(f"{' '.join(cmd[:3])} failed: {(done.stderr or done.stdout).strip()}")
    return done.stdout


def gh_json(*args: str) -> object:
    return json.loads(run("gh", *args))


def version() -> str:
    v = os.environ.get("V", "")
    if not re.fullmatch(r"\d+\.\d+\.\d+", v):
        raise Refusal("set V to the version, for example V=1.2.0")
    return v


def remote_has(ref: str) -> bool:
    return bool(run("git", "ls-remote", "--heads", "origin", ref).strip())


def branch_of(v: str) -> str:
    for prefix in ("release", "hotfix"):
        if remote_has(f"{prefix}/{v}"):
            return f"{prefix}/{v}"
    raise Refusal(f"neither release/{v} nor hotfix/{v} is on origin; make release-cut or hotfix-cut makes it")


def file_version(ref: str) -> str:
    try:
        return run("git", "show", f"{ref}:{VERSION_FILE}").strip()
    except Refusal:
        return "missing"


def version_problem(branch: str, ref: str) -> str | None:
    """Why ref's version file does not match a release or hotfix branch's name, or None (also for any other branch)."""
    named = re.fullmatch(r"(?:release|hotfix)/(\d+\.\d+\.\d+)", branch)
    if not named:
        return None
    have = file_version(ref)
    if have != named.group(1):
        return f"{VERSION_FILE} on {branch} says {have}, not {named.group(1)}; set it to {named.group(1)} on the branch"
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


def runs_for(workflow: str, sha: str) -> list[dict]:
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
    deploys = []
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


def merged_since_main(head: str) -> list[str]:
    out = run("git", "log", "--first-parent", "--format=%s%x1f%b%x1e", f"origin/main..{head}")
    lines = []
    for entry in filter(None, (e.strip() for e in out.split("\x1e"))):
        subject, _, body = entry.partition("\x1f")
        number = re.match(r"Merge pull request #(\d+)", subject)
        title = body.strip().splitlines()[0] if body.strip() else subject
        lines.append(f"#{number.group(1)} {title}" if number else subject)
    return lines


def breaking_changes(head: str) -> list[str]:
    out = run("git", "log", "--format=%s%x1f%B%x1e", f"origin/main..{head}")
    found = []
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


def release_body(v: str, branch: str, sha: str) -> str:
    head = f"origin/{branch}"
    merged = merged_since_main(head)
    if not merged:
        raise Refusal(f"{branch} has nothing that origin/main lacks")
    breaking = breaking_changes(head)
    sdk_changed = bool(run("git", "diff", "--name-only", "origin/main", head, "--", "sdk").strip())
    before, after = sdk_versions("origin/main"), sdk_versions(head)
    lines = [f"Releases {branch} at {sha[:8]} to main.", "", "Merged since main:"]
    lines += [f"- {m}" for m in merged]
    breaking_text = "; ".join(breaking) if breaking else "none marked in commit messages (check the PRs above)"
    lines += ["", f"Breaking changes: {breaking_text}"]
    lines += ["", f"sdk/**: {'changed' if sdk_changed else 'unchanged'}"]
    lines[-1] += f" (sdk-publish.yml {'runs' if sdk_changed else 'does not run'})"
    for kind in ("python", "typescript"):
        name, old = before[kind]
        new = after[kind][1]
        verdict = "new version, sdk-publish.yml publishes it" if old != new else "same version, nothing is published"
        lines.append(f"- {kind} {name} {old} -> {new}: {verdict}")
    lines += [
        "",
        f"Merge with a merge commit (no squash, no rebase). release-tag.yml then tags the merge v{v}; after that run "
        f"make release-back-merge V={v}.",
    ]
    return "\n".join(lines)


def open_pr(head: str, base: str) -> dict | None:
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


def cut(dry: bool, source: str, prefix: str) -> int:
    v = version()
    branch = f"{prefix}/{v}"
    if remote_has(branch):
        raise Refusal(f"{branch} is already on origin")
    sha = run("git", "rev-parse", f"origin/{source}").strip()
    print(f"release: {branch} from origin/{source} at {sha[:8]}; ci.yml on that commit: {ci_status(sha)}")
    have = file_version(sha)
    if have != v:
        print(f"release: {VERSION_FILE} there says {have}; the branch gets one commit on top that sets it to {v}")
    print(f"release: then git push origin <head>:refs/heads/{branch}")
    print("release: the push runs ci.yml, whose staging job deploys the branch with the click walk")
    if dry:
        print("release: dry run, nothing created (DRY=0 does it)")
        return 0
    head = with_version(sha, v)
    run("git", "push", "origin", f"{head}:refs/heads/{branch}")
    print(f"release: pushed {branch}; watch it with: gh run list --branch {branch}")
    return 0


def pr(dry: bool) -> int:
    v = version()
    branch = branch_of(v)
    run("git", "fetch", "--quiet", "--no-tags", "origin", branch)
    if open_pr(branch, "main"):
        return create_pr(dry, branch, "main", "", "")
    sha = run("git", "rev-parse", f"origin/{branch}").strip()
    wrong = version_problem(branch, sha)
    if wrong:
        raise Refusal(wrong)
    status = ci_status(sha)
    if status != "success":
        raise Refusal(f"ci.yml on {branch} at {sha[:8]} is {status}, not success")
    problem = staging_problem(sha)
    if problem:
        raise Refusal(problem)
    kind = "develop" if branch.startswith("release/") else "hotfix"
    return create_pr(dry, branch, "main", f"release: {v} ({kind} → main)", release_body(v, branch, sha))


def back_merge(dry: bool) -> int:
    v = version()
    if not run("git", "ls-remote", "--tags", "origin", f"refs/tags/v{v}").strip():
        raise Refusal(f"tag v{v} is not on origin; tag main's merge commit of the release first")
    if run("git", "rev-list", "--count", "origin/develop..origin/main").strip() == "0":
        raise Refusal("origin/develop already holds everything on origin/main")
    text = (
        f"Brings the v{v} merge commit and anything else on main back into develop. "
        "Merge with a merge commit (no squash, no rebase)."
    )
    return create_pr(dry, "main", "develop", f"release: merge main back into develop (v{v})", text)


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
        run("git", "fetch", "--quiet", "origin", "develop", "main")
        if command == "cut":
            return cut(dry, "develop", "release")
        if command == "hotfix-cut":
            return cut(dry, "main", "hotfix")
        if command == "pr":
            return pr(dry)
        if command == "back-merge":
            return back_merge(dry)
        raise Refusal("usage: release.py cut | hotfix-cut | pr | back-merge | check-version (V=X.Y.Z)")
    except Refusal as why:
        print(f"release: refused: {why}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
