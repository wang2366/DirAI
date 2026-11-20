"""Share agents between people (proposal 72, improvement/share-agents).

The sharer publishes an agent as a snapshot of its folder into agents/<slug>/ of a private GitHub repo
named <name>_agent_repo, in an org of their own (<login>-dirai), where readers are outside collaborators
with the Read role, so GitHub refuses their pushes. The repo's root holds dirai-share.json, an empty
marker (what makes a repo an agent repo); everything else is read from the folders and git.

Readers find the repos shared with them with gh, clone each into www/shares/<owner>/<repo>/ (served like
any page, but read-only: no chat, and the agent list skips www/) and fetch it every 10 min.

Sharing always goes through one github.com account, "Share as", chosen once in ~/.config/dirai/share_account.json
(else gh's active github.com account), whatever that machine's own logins are (e.g. Purdue's GitHub server,
or another github.com account): gh holds several accounts, DirAI runs gh with that account's token (GH_TOKEN,
GH_HOST=github.com) and git over HTTPS with the same token (a credential helper given per command, never saved),
so the active gh account and your own git stay as they are. checks() are the four steps behind the Share
pill (1-2 make it usable, 3-4 set up your own repo); each failed one has a fix that DirAI runs for you
(fix()), as a background job whose progress the pill polls.

Kept in www/shares.json:
  {"targets": {"<agent>": {"<owner>/<repo>": {"slug", "commit", "published"}}},
   "mode": {"<agent>": "run"},              (absent: by hand; "run": republished when it changed, per pass)
   "connected": {"<owner>/<repo>": {"fetched", "updated": [slugs not opened since the fetch]}}}
Clones: www/shares/<owner>/<repo>/ (others' repos), www/shares/.mine/<owner>/<repo>/ (yours, to publish).
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time

import dirai_config

GH = os.environ.get("DIRAI_GH") or shutil.which("gh") or os.path.expanduser("~/.local/bin/gh")
HOST = "github.com"
GIT_URL = os.environ.get("DIRAI_SHARE_GIT_URL", "https://github.com/%s.git")     # % "owner/repo"
ACCOUNT_FILE = os.path.join(dirai_config.CONFIG_DIR, "share_account.json")      # {"account": "<login>"}
AUTH_S = 300             # the account list and token are asked from gh at most this often (or on demand)
# git asks this for the password: the Share-as account's token, from the environment of that one command
CRED_HELPER = '!f() { test "$1" = get && echo username=x-access-token && echo "password=$DIRAI_SHARE_TOKEN"; }; f'
MARKER = "dirai-share.json"
SUFFIX = "_agent_repo"
TOPIC = "dirai-agents"
ORG_SUFFIXES = ("-dirai", "-dirai-agents", "-dirai-2")     # your org's name: the first free one
CACHE_S = 600            # checks and the gh search are redone at most this often (or on demand)
FILE_MAX = 1 << 20       # files over this are left out of a Publish
FULL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")
LOGIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
SECRET_RE = re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}|sk-ant-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|"
                       r"-----BEGIN [A-Z ]*PRIVATE KEY-----|(?i:password|passwd|secret|api_key)\s*[=:]\s*['\"][^'\"]{6,}")
ABS_RE = re.compile(r"(?<![\w.~])(/(?:home|Users|scratch|depot|work|data|gpfs)/[^\s\"'<>)\]]+)")
QUERY = """query($after: String) { viewer { login
  repositories(first: 100, after: $after, affiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER],
               ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]) {
    pageInfo { hasNextPage endCursor }
    nodes { name nameWithOwner owner { login } viewerPermission pushedAt
      marker: object(expression: "HEAD:dirai-share.json") { id }
      agents: object(expression: "HEAD:agents") { ... on Tree { entries { name type } } } } } } }"""


def run(args, cwd=None, timeout=120, input=None, env=None):
    """(exit code, stdout+stderr) of a command; 127 if it can't start or times out."""
    try:
        p = subprocess.run(args, cwd=cwd, input=input, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           universal_newlines=True, timeout=timeout, env=env)
        return p.returncode, p.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def bare_env():
    """The environment without GitHub tokens or host of the caller's own: gh then reads its own logins."""
    return {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN", "GH_HOST",
                                                              "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")}


def chosen_account():
    a = dirai_config.load_json(ACCOUNT_FILE, {})
    a = a.get("account") if isinstance(a, dict) else None
    return a if isinstance(a, str) and LOGIN_RE.match(a) else None


def choose_account(login):
    dirai_config.save_json(ACCOUNT_FILE, {"account": login}, indent=1)
    _auth["t"] = 0


def gh_accounts():
    """([logins gh holds for github.com], the active one) on this machine."""
    rc, out = run([GH, "auth", "status", "--hostname", HOST], env=bare_env(), timeout=30)
    logins, active = [], None
    parts = re.split(r"Logged in to github\.com (?:account|as) ", out)[1:]
    for p in parts:
        m = re.match(r"([A-Za-z0-9-]+)", p)
        if not m:
            continue
        logins.append(m.group(1))
        if "Active account: true" in p or len(parts) == 1:
            active = m.group(1)
    return logins, active


_auth = {"t": 0}


def auth(force=False):
    """{"accounts", "active", "chosen", "login" (who shares), "token" (None: not held here)}, cached AUTH_S."""
    if not force and time.time() - _auth["t"] < AUTH_S:
        return _auth
    a = {"accounts": [], "active": None, "chosen": chosen_account(), "login": None, "token": None}
    if os.access(GH, os.X_OK):
        a["accounts"], a["active"] = gh_accounts()
        a["login"] = a["chosen"] or a["active"]
        if a["login"] in a["accounts"]:
            rc, tok = run([GH, "auth", "token", "--hostname", HOST, "--user", a["login"]], env=bare_env(), timeout=30)
            a["token"] = tok if rc == 0 and tok else None
    _auth.clear()
    _auth.update(a, t=time.time())
    return _auth


def gh_env():
    a = auth()
    return dict(bare_env(), GH_HOST=HOST, GH_TOKEN=a["token"]) if a["token"] else None


def gh(*args, **kw):
    """gh as the Share-as account, on github.com; refused when that account isn't logged in here."""
    env = gh_env()
    if env is None:
        return 1, "gh holds no github.com login for %s on this machine" % (auth()["login"] or "you")
    return run([GH] + list(args), env=env, **kw)


def gh_json(*args):
    rc, out = gh(*args)
    if rc:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def git(cwd, *args, timeout=180):
    # a commit made by DirAI needs a name even where git has none configured
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    for k, v in (("GIT_AUTHOR_NAME", "DirAI"), ("GIT_AUTHOR_EMAIL", "dirai@localhost")):
        if run(["git", "config", "--get", "user." + k.split("_")[-1].lower()], cwd=cwd)[0]:
            env.setdefault(k, v)
            env.setdefault(k.replace("AUTHOR", "COMMITTER"), v)
    pre = []
    if GIT_URL.startswith("https://") and args and args[0] in ("clone", "fetch", "push", "pull", "ls-remote"):
        tok = auth()["token"]       # the Share-as account, for this command only (your own helpers are off)
        if tok:
            env["DIRAI_SHARE_TOKEN"] = tok
            pre = ["-c", "credential.helper=", "-c", "credential.helper=" + CRED_HELPER]
    return run(["git"] + pre + list(args), cwd=cwd, timeout=timeout, env=env)


def org_name(login, suffix):
    """GitHub names: letters, digits, single hyphens, at most 39 characters."""
    return login[:39 - len(suffix)].rstrip("-") + suffix


def page_title(path):
    """The <h1> of an index.html, as text."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            m = re.search(r"<h1[^>]*>(.*?)</h1>", f.read(200000), re.S | re.I)
    except OSError:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""


def same_file(a, b):
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def clean_name(p):
    """A folder name safe in the repo: letters, digits, . _ -"""
    return re.sub(r"[^A-Za-z0-9._-]", "-", p).strip(".-") or "agent"


def is_agent(d):
    return os.path.isfile(os.path.join(d, "index.html"))


def clear_snapshot(dest):
    """Empty an agent's published folder before it is copied again, keeping the folders of the agents
    published inside it (its children), which their own Publish writes."""
    if not os.path.isdir(dest):
        return
    for d, dirs, names in os.walk(dest):
        dirs[:] = [n for n in dirs if not is_agent(os.path.join(d, n))]
        for n in names:
            os.remove(os.path.join(d, n))
    for d, dirs, names in os.walk(dest, topdown=False):
        if d != dest and not os.listdir(d):
            os.rmdir(d)


def owning_agent(top, name):
    """The agent (slug) a changed repo path agents/<...>/file belongs to: its deepest folder holding an
    index.html; a deleted agent's top folder when none is left."""
    parts = name.split("/")[1:-1]
    for i in range(len(parts), 0, -1):
        if is_agent(os.path.join(top, *parts[:i])):
            return "/".join(parts[:i])
    return parts[0]


class Shares:
    def __init__(self, root):
        self.root = root
        self.dir = os.path.join(dirai_config.data_dir(root), "shares")
        self.state_path = os.path.join(dirai_config.data_dir(root), "shares.json")
        self.lock = threading.RLock()       # state and the clones
        self.job = {}                       # the one fix or action running: {"op", "state", "out", "code", "url"}
        self._checks = (0, None)
        self._found = (0, None)
        self._refreshing = False

    # --- state ------------------------------------------------------------------------------------
    def state(self):
        s = dirai_config.load_json(self.state_path, {})
        for k in ("targets", "mode", "connected"):
            s.setdefault(k, {})
        return s

    def save(self, s):
        dirai_config.save_json(self.state_path, s, indent=1)

    def clone_dir(self, full, mine=False):
        return os.path.join(self.dir, ".mine", full) if mine else os.path.join(self.dir, full)

    # --- the checks behind the pill ---------------------------------------------------------------
    def checks(self, force=False):
        """[{n, name, ok (True/False/None: waits), found, fixes: [{op, label, runs}]}], cached CACHE_S."""
        t, c = self._checks
        if c is not None and not force and time.time() - t < CACHE_S:
            return c
        c = self._compute_checks()
        self._checks = (time.time(), c)
        return c

    def _compute_checks(self):
        out = []
        have_gh = os.access(GH, os.X_OK)
        out.append({"n": 1, "name": "gh installed", "ok": have_gh, "found": GH if have_gh else "no gh found",
                    "fixes": [{"op": "install_gh", "label": "Install gh",
                               "runs": "bash scripts/install_gh.sh (curl, into ~/.local, no sudo)"}]})
        a = auth(force=True)
        user = gh_json("api", "user") if a["token"] else None      # the token works, and whose it is
        login = user and user.get("login")
        want = a["login"]
        if login:
            found = login + ("" if a["chosen"] else " (gh's active account; pick one to keep it)")
        elif want:
            found = "%s isn't logged in to gh here" % want
        else:
            found = "no github.com account in gh"
        out.append({"n": 2, "name": "Share as (github.com)", "ok": bool(login) if have_gh else None,
                    "found": found, "accounts": a["accounts"], "chosen": a["chosen"],
                    "fixes": [{"op": "gh_login", "label": "Log in to github.com" + (" as " + want if want else ""),
                               "runs": "gh auth login --hostname github.com --web (adds the account; "
                                       "your active gh account is switched back after)"}]})
        org, mine = None, False
        if login:
            names = [org_name(login, s) for s in ORG_SUFFIXES]
            for n in names:      # an org of these names where you are an admin
                mem = gh_json("api", "user/memberships/orgs/" + n)
                if mem and mem.get("role") == "admin" and mem.get("state") == "active":
                    org, mine = n, True
                    break
            if not org:
                org = next((n for n in names if gh("api", "users/" + n)[0] != 0), None)
        out.append({"n": 3, "name": "my org", "ok": mine if login else None,
                    "found": (org + (" (yours)" if mine else " (free to create)")) if org else "no free name",
                    "org": org,
                    "fixes": [{"op": "open_org", "label": "Open GitHub: new org",
                               "url": "https://github.com/account/organizations/new",
                               "runs": "make the org %s on the web, Free plan (GitHub's API can't make orgs)" % org}]})
        repos = [r["full"] for r in self.found().get("mine", [])] if mine else []
        out.append({"n": 4, "name": "my agent repo", "ok": bool(repos) if mine else None,
                    "found": ", ".join(repos) or "%s/%s%s" % (org, login, SUFFIX),
                    "fixes": [{"op": "create_repo", "label": "Create my agent repo",
                               "runs": "gh repo create %s/%s%s --private, topic %s, empty %s" % (
                                   org, login, SUFFIX, TOPIC, MARKER)}]})
        out[0]["login"] = login
        return out

    def ready(self, checks=None):
        return all(c["ok"] for c in (checks or self.checks())[:2])

    def cached_ready(self):
        """ready() from the last checks, None if none were made yet (no gh call)."""
        return self.ready(self._checks[1]) if self._checks[1] else None

    def login(self):
        return self.checks()[0].get("login")

    def my_org(self):
        c = self.checks()[2]
        return c["org"] if c["ok"] else None

    # --- what gh finds -----------------------------------------------------------------------------
    def found(self, force=False):
        """{"mine": [{full, agents}], "shared": [{full, owner, agents, pushed}], "invitations": [{id, full, from}]},
        from one GraphQL search (cached CACHE_S) and the pending invitations."""
        t, f = self._found
        if f is not None and not force and time.time() - t < CACHE_S:
            return f
        f = self._search()
        self._found = (time.time(), f)
        return f

    def refresh_soon(self):
        """found() again in the background, for a report that mustn't wait for gh."""
        if self._refreshing:
            return
        self._refreshing = True

        def go():
            try:
                self.found(force=True)
            finally:
                self._refreshing = False
        threading.Thread(target=go, daemon=True).start()

    def _search(self):
        f = {"mine": [], "shared": [], "invitations": []}
        if not os.access(GH, os.X_OK):
            return f
        nodes, after, me = [], None, None
        while True:
            args = ["api", "graphql", "-f", "query=" + QUERY] + (["-f", "after=" + after] if after else [])
            d = gh_json(*args)
            if not d or "data" not in d:
                return f
            v = d["data"]["viewer"]
            me, r = v["login"], v["repositories"]
            nodes += r["nodes"]
            if not r["pageInfo"]["hasNextPage"]:
                break
            after = r["pageInfo"]["endCursor"]
        for n in nodes:
            if not n.get("marker"):
                continue
            entries = (n.get("agents") or {}).get("entries") or []
            item = {"full": n["nameWithOwner"], "owner": n["owner"]["login"],
                    "agents": sum(1 for e in entries if e.get("type") == "tree"), "pushed": (n["pushedAt"] or "")[:10]}
            (f["mine"] if n["viewerPermission"] == "ADMIN" else f["shared"]).append(item)
        for i in gh_json("api", "user/repository_invitations") or []:
            repo = i.get("repository") or {}
            if repo.get("name", "").endswith(SUFFIX):
                f["invitations"].append({"id": i["id"], "full": repo["full_name"],
                                         "from": (i.get("inviter") or {}).get("login", "")})
        for item in f["mine"]:
            item["readers"] = self.readers(item["full"])
        f["me"] = me
        return f

    def readers(self, full):
        """[{login, role}] of the outside collaborators of one of your repos."""
        got = gh_json("api", "repos/%s/collaborators?affiliation=outside" % full) or []
        return [{"login": c["login"], "role": c.get("role_name", "")} for c in got if isinstance(c, dict)]

    # --- publishing ---------------------------------------------------------------------------------
    def folder(self, agent):
        """(files [(rel, size)], left_out [(rel, why)], children [agent paths]) of an agent's folder:
        hidden files, tmp/, *.log, links and files over FILE_MAX stay out; a folder with its own index.html
        is another agent (a child), never part of this one's snapshot."""
        top = os.path.join(self.root, agent)
        files, out, children = [], [], []
        for d, dirs, names in os.walk(top):
            rel_d = os.path.relpath(d, top)
            rel_d = "" if rel_d == "." else rel_d
            keep = []
            for n in sorted(dirs):
                p = os.path.join(d, n)
                rel = os.path.join(rel_d, n)
                if n.startswith(".") or os.path.islink(p):
                    continue
                if n == "tmp" or (not rel_d and n in ("www", "pasted")):
                    out.append((rel + "/", "left out"))
                elif os.path.isfile(os.path.join(p, "index.html")):
                    children.append(os.path.join(agent, rel) if agent else rel)
                else:
                    keep.append(n)
            dirs[:] = keep
            for n in sorted(names):
                p = os.path.join(d, n)
                rel = os.path.join(rel_d, n)
                if n.startswith(".") or os.path.islink(p):
                    continue
                size = os.path.getsize(p)
                if n.endswith(".log"):
                    out.append((rel, "log"))
                elif size > FILE_MAX:
                    out.append((rel, "%.1f MB" % (size / 1e6)))
                else:
                    files.append((rel, size))
        return files, out, children

    def warnings(self, agent, files, limit=5):
        """Secret-like strings, and absolute paths outside the agent's folder, in the files to publish."""
        top = os.path.realpath(os.path.join(self.root, agent))
        warn = []
        for rel, size in files:
            if len(warn) >= limit:
                break
            try:
                with open(os.path.join(top, rel), encoding="utf-8") as f:
                    text = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            if SECRET_RE.search(text):
                warn.append("%s: something that looks like a password or key" % rel)
            outside = [p for p in ABS_RE.findall(text) if not dirai_config.within(p.rstrip("/.,;:"), top)]
            if outside:
                warn.append("%s: %d path%s outside the folder (readers won't have %s), e.g. %s" % (
                    rel, len(outside), "" if len(outside) == 1 else "s", "it" if len(outside) == 1 else "them",
                    outside[0]))
        return warn

    def slug(self, s, agent, full, parent_slug=None, parent=None):
        """The folder for this agent under agents/ in this repo. A child published with its parent goes
        inside the parent's, at its path below the parent (<parent slug>/<path>), so the repo keeps the
        folder structure (a child published before 2026-11-19 as <parent>--<child> moves there on its
        next Publish). An agent published alone gets its folder name, kept once given. The tree's own
        paths above the agent never show."""
        if parent_slug:
            return parent_slug + "/" + "/".join(clean_name(p) for p in os.path.relpath(agent, parent).split(os.sep))
        old = s["targets"].get(agent, {}).get(full, {}).get("slug")
        if old:
            return old
        base = clean_name(os.path.basename(agent) or "tree")
        used = {t[full]["slug"] for a, t in s["targets"].items() if full in t and a != agent}
        slug, i = base, 2
        while slug in used:
            slug, i = "%s-%d" % (base, i), i + 1
        return slug

    def changed(self, agent, full, slug):
        """How many files differ between the folder and what was published (None: not published here)."""
        pub = os.path.join(self.clone_dir(full, mine=True), "agents", slug)
        if not os.path.isdir(pub):
            return None
        files = {rel for rel, _ in self.folder(agent)[0]}
        top = os.path.join(self.root, agent)
        there = set()
        for d, dirs, names in os.walk(pub):
            dirs[:] = [n for n in dirs if not is_agent(os.path.join(d, n))]   # its children, published inside it
            for n in names:
                there.add(os.path.relpath(os.path.join(d, n), pub))
        return len(files ^ there) + sum(1 for rel in files & there
                                        if not same_file(os.path.join(top, rel), os.path.join(pub, rel)))

    def sync_mine(self, full):
        """Your clone of one of your repos, up to date with GitHub (cloned the first time)."""
        path = self.clone_dir(full, mine=True)
        if not os.path.isdir(os.path.join(path, ".git")):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            rc, out = git(None, "clone", "-q", GIT_URL % full, path)
            return None if rc == 0 else "git clone %s: %s" % (full, out)
        git(path, "remote", "set-url", "origin", GIT_URL % full)     # HTTPS even for a clone made over ssh
        rc, out = git(path, "fetch", "-q", "origin")
        if rc:
            return "git fetch %s: %s" % (full, out)
        rc, out = git(path, "reset", "-q", "--hard", "@{u}")      # only Publish writes here
        return None if rc == 0 else out

    def publish(self, agent, repos, children=()):
        """Copy the agent's folder into agents/<slug>/ of each repo, and the ticked children inside it at
        their paths below it (each its own entry), commit and push. A rejected push is rebased on GitHub's and tried once more."""
        with self.lock:
            s = self.state()
            errors = []
            for full in repos:
                if not FULL_RE.match(full):
                    errors.append("bad repo name %s" % full)
                    continue
                why = self.sync_mine(full)
                if why:
                    errors.append(why)
                    continue
                clone = self.clone_dir(full, mine=True)
                pslug = self.slug(s, agent, full)
                todo = [(agent, pslug)] + [(c, self.slug(s, c, full, pslug, agent)) for c in children]
                for a, slug in todo:
                    old = s["targets"].get(a, {}).get(full, {}).get("slug")
                    if old and old != slug and not slug.startswith(old + "/"):
                        # published before elsewhere (alone, or as <parent>--<child>): it moves inside its parent
                        for b in self.inside(s, a, full):
                            shutil.rmtree(os.path.join(clone, "agents", s["targets"][b][full]["slug"]), ignore_errors=True)
                            del s["targets"][b][full]
                            if not s["targets"][b]:
                                del s["targets"][b]
                        shutil.rmtree(os.path.join(clone, "agents", old), ignore_errors=True)
                    dest = os.path.join(clone, "agents", slug)
                    clear_snapshot(dest)
                    for rel, _ in self.folder(a)[0]:
                        os.makedirs(os.path.dirname(os.path.join(dest, rel)), exist_ok=True)
                        shutil.copy2(os.path.join(self.root, a, rel), os.path.join(dest, rel))
                git(clone, "add", "-A", "agents")
                if git(clone, "diff", "--cached", "--quiet")[0]:
                    rc, out = git(clone, "commit", "-q", "-m", "Publish " + ", ".join(sl for _, sl in todo))
                    if rc:
                        errors.append("git commit: " + out)
                        continue
                    rc, out = git(clone, "push", "-q", "origin", "HEAD")
                    if rc:
                        git(clone, "pull", "-q", "--rebase", "origin")
                        rc, out = git(clone, "push", "-q", "origin", "HEAD")
                    if rc:
                        errors.append("git push %s: %s" % (full, out))
                        continue
                head = git(clone, "rev-parse", "--short", "HEAD")[1]
                now = time.strftime("%Y-%m-%dT%H:%M:%S")
                for a, slug in todo:
                    s["targets"].setdefault(a, {})[full] = {"slug": slug, "commit": head, "published": now}
            self.save(s)
            return errors

    def inside(self, s, agent, full):
        """The agents published inside this one's folder in this repo (its children, theirs, ...), and its
        children published before 2026-11-19 beside it as <slug>--<child>."""
        t = s["targets"].get(agent, {}).get(full)
        if not t:
            return []
        pre = (t["slug"] + "/", t["slug"] + "--")
        return sorted(a for a, ts in s["targets"].items() if full in ts and ts[full]["slug"].startswith(pre))

    def unshare(self, agent, full):
        """Remove the agent, and the children published inside its folder, from the repo in a new commit
        (its old commits still hold them)."""
        with self.lock:
            s = self.state()
            t = s["targets"].get(agent, {}).get(full)
            if not t:
                return "not shared to %s" % full
            why = self.sync_mine(full)
            if why:
                return why
            clone = self.clone_dir(full, mine=True)
            gone = [agent] + self.inside(s, agent, full)
            paths = [os.path.join("agents", s["targets"][a][full]["slug"]) for a in gone]
            paths = [p for p in paths if os.path.isdir(os.path.join(clone, p))
                     and not any(p.startswith(q + "/") for q in paths)]    # an old <slug>--<child> is its own folder
            if paths:
                git(clone, "rm", "-rq", *paths)
                rc, out = git(clone, "commit", "-q", "-m", "Unshare " + t["slug"])
                if rc == 0:
                    rc, out = git(clone, "push", "-q", "origin", "HEAD")
                if rc:
                    return out
            for a in gone:
                del s["targets"][a][full]
                if not s["targets"][a]:
                    del s["targets"][a]
            self.save(s)
            return None

    def page_state(self, agent):
        """What the Share pill and its popover show for one of your agents."""
        c = self.checks()
        s = self.state()
        targets = s["targets"].get(agent, {})
        files, out, children = self.folder(agent)
        repos = []
        if self.ready(c):
            for r in self.found().get("mine", []):
                t = targets.get(r["full"])
                repos.append(dict(r, shared=bool(t), published=t and t["published"],
                                  changed=self.changed(agent, r["full"], t["slug"]) if t else None))
        return {"checks": c, "ready": self.ready(c), "repos": repos, "mode": s["mode"].get(agent, "hand"),
                "children": [{"agent": ch, "title": page_title(os.path.join(self.root, ch, "index.html")),
                              "shared": sorted(s["targets"].get(ch, {}))} for ch in children],
                "files": len(files), "bytes": sum(n for _, n in files), "left_out": ["%s (%s)" % (r, why) if why != "left out" else r for r, why in out][:8],
                "warnings": self.warnings(agent, files), "job": self.job}

    def republish_changed(self):
        """Agents set to "after each run": publish again where files changed since (each pass)."""
        s = self.state()
        for agent, mode in list(s["mode"].items()):
            if mode != "run" or not os.path.isfile(os.path.join(self.root, agent, "index.html")):
                continue
            for full, t in s["targets"].get(agent, {}).items():
                if self.changed(agent, full, t["slug"]):
                    self.publish(agent, [full])

    # --- reading others' repos ---------------------------------------------------------------------
    def connect(self, full, invitation=None):
        if not FULL_RE.match(full):
            return "bad repo name"
        if invitation is not None:
            rc, out = gh("api", "-X", "PATCH", "user/repository_invitations/%d" % int(invitation))
            if rc:
                return "accepting the invitation: " + out
        path = self.clone_dir(full)
        with self.lock:
            if not os.path.isdir(os.path.join(path, ".git")):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                rc, out = git(None, "clone", "-q", GIT_URL % full, path)
                if rc:
                    shutil.rmtree(path, ignore_errors=True)
                    return "git clone: " + out
            s = self.state()
            s["connected"][full] = {"fetched": time.strftime("%Y-%m-%dT%H:%M:%S"), "updated": []}
            self.save(s)
        self.refresh_soon()
        return None

    def disconnect(self, full):
        with self.lock:
            s = self.state()
            if full not in s["connected"]:
                return "not connected"
            shutil.rmtree(self.clone_dir(full), ignore_errors=True)
            del s["connected"][full]
            self.save(s)
        return None

    def fetch(self, full):
        """Bring one connected clone to GitHub's version; the agents whose folders changed are marked."""
        path = self.clone_dir(full)
        git(path, "remote", "set-url", "origin", GIT_URL % full)
        rc, out = git(path, "fetch", "-q", "origin")
        if rc:
            return out
        rc, names = git(path, "diff", "--name-only", "HEAD", "@{u}", "--", "agents")
        names = [n for n in names.splitlines() if n.count("/") >= 2] if rc == 0 else []
        git(path, "reset", "-q", "--hard", "@{u}")      # a reader's clone is never written to
        top = os.path.join(path, "agents")
        with self.lock:
            s = self.state()
            c = s["connected"].get(full)
            if c is not None:
                c["fetched"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                c["updated"] = sorted(set(c.get("updated", [])) | {owning_agent(top, n) for n in names})
                self.save(s)
        return None

    def fetch_all(self):
        """The 10-min pass: fetch every connected repo, republish "after each run" agents, search again."""
        for full in list(self.state()["connected"]):
            self.fetch(full)
        self.republish_changed()
        if os.access(GH, os.X_OK):
            self.found(force=True)
            self.checks(force=True)

    def seen(self, full, slug):
        with self.lock:
            s = self.state()
            c = s["connected"].get(full)
            if c and slug in c.get("updated", []):
                c["updated"].remove(slug)
                self.save(s)

    def published(self, full, slug):
        """The date of the last commit that changed agents/<slug> in a connected clone ("" if unknown)."""
        rc, out = git(self.clone_dir(full), "log", "-1", "--format=%cs", "--", "agents/" + slug)
        return out if rc == 0 else ""

    def box(self, full):
        """One connected repo, as its box in the Machines map: its agents, nested by slug."""
        path = self.clone_dir(full)
        c = self.state()["connected"].get(full, {})
        agents = []
        top = os.path.join(path, "agents")
        for d, dirs, names in os.walk(top):     # top-down, sorted: a parent comes before its children
            dirs[:] = sorted(n for n in dirs if not n.startswith("."))
            if d == top or "index.html" not in names:
                continue
            slug = os.path.relpath(d, top).replace(os.sep, "/")
            page = os.path.join(d, "index.html")
            parent = os.path.dirname(slug)
            while parent and not is_agent(os.path.join(top, parent)):
                parent = os.path.dirname(parent)
            if not parent and "--" in slug:      # published before 2026-11-19: <parent>--<child>, side by side
                parent = slug.rsplit("--", 1)[0]
            agents.append({"slug": slug, "title": page_title(page),
                           "parent": parent or None,
                           "published": self.published(full, slug),
                           "updated": slug in c.get("updated", []),
                           "url": "/%s/shares/%s/agents/%s/" % (dirai_config.DATA, full, slug)})
        owner, repo = full.split("/")
        return {"full": full, "name": repo[:-len(SUFFIX)] if repo.endswith(SUFFIX) else repo, "owner": owner,
                "fetched": c.get("fetched", ""), "updated": len(c.get("updated", [])), "agents": agents}

    def report(self):
        """For the agent list's Machines map: never waits for gh (stale results refresh in the background)."""
        t, f = self._found
        if f is None or time.time() - t > CACHE_S:
            self.refresh_soon()
        f = f or {}
        s = self.state()
        connected = set(s["connected"])
        return {"gh": os.access(GH, os.X_OK), "me": f.get("me"),
                "shared": [r for r in f.get("shared", []) if r["full"] not in connected],
                "invitations": [i for i in f.get("invitations", []) if i["full"] not in connected],
                "mine": f.get("mine", []), "connected": [self.box(full) for full in sorted(connected)]}

    def shared_page(self, page):
        """For a page under www/shares/<owner>/<repo>/agents/<slug>/: {full, slug, owner, published}."""
        parts = page.split("/")
        if len(parts) < 6 or parts[:2] != [dirai_config.DATA, "shares"] or parts[4] != "agents":
            return None
        full, slug = parts[2] + "/" + parts[3], "/".join(p for p in parts[5:] if p)    # a child: <parent>/<child>
        if not slug or ".." in slug.split("/"):
            return None
        if full not in self.state()["connected"]:
            return None
        self.seen(full, slug)
        return {"full": full, "slug": slug, "owner": parts[2], "repo": parts[3],
                "published": self.published(full, slug)}

    # --- copies in your tree -----------------------------------------------------------------------
    def copy(self, page, dest):
        """Copy a shared agent into your tree at dest (a new folder), with .dirai-origin for updates."""
        sp = self.shared_page(page)
        if not sp:
            return "not a shared agent"
        src = os.path.join(self.root, page)
        to = os.path.join(self.root, dest)
        if os.path.exists(to):
            return "%s/ already exists" % dest
        shutil.copytree(src, to)
        commit = git(self.clone_dir(sp["full"]), "log", "-1", "--format=%H", "--", "agents/" + sp["slug"])[1]
        dirai_config.save_json(os.path.join(to, ".dirai-origin"),
                               {"repo": sp["full"], "slug": sp["slug"], "commit": commit}, indent=1)
        return None

    def origin(self, agent):
        """For a copy: {repo, slug, files: [changed upstream since the copy]}, or None."""
        o = dirai_config.load_json(os.path.join(self.root, agent, ".dirai-origin"), None)
        if not isinstance(o, dict) or o.get("repo") not in self.state()["connected"]:
            return None
        clone = self.clone_dir(o["repo"])
        new = git(clone, "log", "-1", "--format=%H", "--", "agents/" + o["slug"])[1]
        if not new or new == o.get("commit"):
            return dict(o, files=[], new=new)
        rc, names = git(clone, "diff", "--name-only", o["commit"], new, "--", "agents/" + o["slug"])
        pre = "agents/%s/" % o["slug"]
        return dict(o, new=new, files=[n[len(pre):] for n in names.splitlines() if n.startswith(pre)] if rc == 0 else [])

    def update_copy(self, agent):
        """Take the owner's newer version: files you didn't change are replaced; where you did, yours stay
        and theirs go next to them as <file>.theirs. Returns (updated, kept) file lists."""
        o = self.origin(agent)
        if not o or not o["files"]:
            return [], []
        clone = self.clone_dir(o["repo"])
        top = os.path.join(self.root, agent)
        done, kept = [], []

        def show(commit, rel):      # the file's bytes at that commit, None if it wasn't there
            p = subprocess.run(["git", "show", "%s:agents/%s/%s" % (commit, o["slug"], rel)], cwd=clone,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            return p.stdout if p.returncode == 0 else None

        def put(path, data):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        for rel in o["files"]:
            path = os.path.realpath(os.path.join(top, rel))
            if not dirai_config.within(path, os.path.realpath(top)):
                continue
            old, new = show(o["commit"], rel), show(o["new"], rel)
            try:
                with open(path, "rb") as f:
                    mine = f.read()
            except OSError:
                mine = None
            if mine == old:          # untouched since the copy: take theirs
                if new is None:
                    if os.path.exists(path):
                        os.remove(path)
                else:
                    put(path, new)
                done.append(rel)
            elif new is not None:    # you changed it: keep yours, theirs beside it
                put(path + ".theirs", new)
                kept.append(rel)
        dirai_config.save_json(os.path.join(top, ".dirai-origin"),
                               {"repo": o["repo"], "slug": o["slug"], "commit": o["new"]}, indent=1)
        return done, kept

    # --- the fixes and setup actions, as one background job at a time -----------------------------
    def start(self, op, fn, *args):
        if self.job.get("state") == "running":
            return "busy: %s is still running" % self.job["op"]
        self.job = {"op": op, "state": "running", "out": "", "started": time.time()}

        def go():
            try:
                why = fn(*args)
            except Exception as e:     # a job's failure is shown in the popover, never kills the server
                why = str(e)
            self.job.update(state="failed" if why else "done", out=(why or self.job.get("out", ""))[-2000:])
            self._checks = (0, None)
            self._found = (0, None)
        threading.Thread(target=go, daemon=True).start()
        return None

    def fix(self, op, body):
        if op == "install_gh":
            return self.start(op, self._install_gh)
        if op == "gh_login":
            return self.start(op, self._gh_login)
        if op == "create_repo":
            name = str(body.get("name") or "")
            return self.start(op, self._create_repo, name)
        if op == "add_reader":
            full, login = str(body.get("repo") or ""), str(body.get("login") or "").strip().lstrip("@")
            if not FULL_RE.match(full) or not LOGIN_RE.match(login):
                return "give a GitHub login, e.g. alice"
            return self.start(op, self._add_reader, full, login)
        return "unknown fix %s" % op

    def _install_gh(self):
        rc, out = run(["bash", os.path.join(dirai_config.SCRIPTS_DIR, "install_gh.sh")], timeout=300)
        self.job["out"] = out
        return None if rc == 0 else out

    def _gh_login(self):
        """gh's device login: its one-time code goes to the popover, which links to github.com/login/device;
        gh returns when the owner approves there. gh adds the account next to the ones it holds and makes it
        the active one: the account that was active is switched back, and the new one becomes Share as."""
        before, active = gh_accounts()
        rc, proto = run([GH, "config", "get", "git_protocol", "--host", HOST], env=bare_env())
        proto = proto if rc == 0 and proto in ("ssh", "https") else "ssh"     # kept as it was: DirAI's git doesn't use it
        env = dict(bare_env(), GH_BROWSER="true", BROWSER="true")      # never a browser on the server
        p = subprocess.Popen([GH, "auth", "login", "--hostname", HOST, "--web", "--git-protocol", proto,
                              "--skip-ssh-key"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             universal_newlines=True, env=env)
        self.job["url"] = "https://github.com/login/device"
        try:
            p.stdin.write("\n")      # "Press Enter to open github.com in your browser"
            p.stdin.flush()
        except OSError:
            pass
        lines = []
        for line in p.stdout:
            lines.append(line.rstrip())
            m = re.search(r"code: ([A-Z0-9]{4}-[A-Z0-9]{4})", line)
            if m:
                self.job["code"] = m.group(1)
            self.job["out"] = "\n".join(lines[-8:])
        if p.wait() != 0:
            return "\n".join(lines[-8:]) or "gh auth login failed"
        after, now = gh_accounts()
        new = next((x for x in after if x not in before), now)
        if active and now and now != active:       # your terminal's gh stays on the account it was on
            run([GH, "auth", "switch", "--hostname", HOST, "--user", active], env=bare_env())
        if new:
            choose_account(new)
        auth(force=True)
        return None

    def _create_repo(self, name):
        login, org = self.login(), self.my_org()
        if not org:
            return "make your org first (step 3)"
        name = name or login + SUFFIX
        if not name.endswith(SUFFIX):
            name += SUFFIX
        if not NAME_RE.match(name):
            return "bad repo name"
        full = "%s/%s" % (org, name)
        for args in (["repo", "create", full, "--private", "--description", "DirAI agents shared by " + login],
                     ["repo", "edit", full, "--add-topic", TOPIC]):
            rc, out = gh(*args)
            if rc:
                return out
        clone = self.clone_dir(full, mine=True)
        shutil.rmtree(clone, ignore_errors=True)
        os.makedirs(clone)
        with open(os.path.join(clone, MARKER), "w"):
            pass
        with open(os.path.join(clone, "README.md"), "w") as f:
            f.write("# %s\n\nAgents shared by %s with DirAI. One folder per agent under agents/. Read-only for you:\n"
                    "copy an agent into your own tree to run or change it.\n" % (name, login))
        for args in (["init", "-q"], ["add", MARKER, "README.md"], ["commit", "-q", "-m", "Start the agent repo (DirAI)"],
                     ["branch", "-M", "main"], ["remote", "add", "origin", GIT_URL % full], ["push", "-q", "-u", "origin", "main"]):
            rc, out = git(clone, *args)
            if rc:
                return out
        return None

    def _add_reader(self, full, login):
        rc, out = gh("api", "-X", "PUT", "repos/%s/collaborators/%s" % (full, login), "-f", "permission=pull")
        return None if rc == 0 else out

    # --- the one entry point for the server ---------------------------------------------------------
    def act(self, body, agent=None):
        """POST /_review/share. agent: one of your agents (the page's), or the shared page's path."""
        op = body.get("op")
        if op == "check":
            self.checks(force=True)
            self.found(force=True)
            return {"ok": True}
        if op in ("install_gh", "gh_login", "create_repo", "add_reader"):
            why = self.fix(op, body)
            return {"error": why} if why else {"ok": True}
        if op == "account":       # Share as: one of the github.com accounts gh holds here
            login = str(body.get("account") or "")
            if login not in auth(force=True)["accounts"]:
                return {"error": "gh holds no github.com login for %s here: Add another account" % login}
            choose_account(login)
            self._checks = (0, None)
            self._found = (0, None)
            return {"ok": True}
        if op == "connect":
            why = self.connect(str(body.get("repo") or ""), body.get("invitation"))
            return {"error": why} if why else {"ok": True}
        if op == "disconnect":
            why = self.disconnect(str(body.get("repo") or ""))
            return {"error": why} if why else {"ok": True}
        if op == "fetch":
            full = str(body.get("repo") or "")
            if full not in self.state()["connected"]:
                return {"error": "not connected"}
            why = self.fetch(full)
            return {"error": why} if why else {"ok": True}
        if agent is None:
            return {"error": "no such agent"}
        if op == "publish":
            if not self.ready():
                return {"error": "GitHub isn't ready on this machine: see the checklist"}
            mine = {r["full"] for r in self.found().get("mine", [])}
            repos = [r for r in body.get("repos") or [] if r in mine]
            if not repos:
                return {"error": "tick a repo to share to"}
            kids = set(self.folder(agent)[2])
            children = [c for c in body.get("children") or [] if c in kids]
            errors = self.publish(agent, repos, children)
            return {"error": "; ".join(errors)} if errors else {"ok": True}
        if op == "unshare":
            # agents: this one and/or its children (default this one; or child: one of them);
            # repos: the ones to remove them from (or repo: one, "*" every repo each is in)
            kids = set(self.folder(agent)[2])
            names = body.get("agents") or [body.get("child") or agent]
            if any(a != agent and a not in kids for a in names):
                return {"error": "not this agent or one of its children"}
            names = sorted(set(names), key=lambda a: a != agent)    # this agent first: it takes its children along
            want = body.get("repos") or [str(body.get("repo") or "*")]
            errors, done = [], 0
            for a in names:
                have = sorted(self.state()["targets"].get(a, {}))     # read again: a parent's Unshare drops its children
                for r in (have if want == ["*"] else [r for r in want if r in have]):
                    w = self.unshare(a, r)
                    if w:
                        errors.append(w)
                    else:
                        done += 1
            if errors:
                return {"error": "; ".join(errors)}
            return {"ok": True} if done else {"error": "none of these agents is shared to those repos"}
        if op == "mode":
            with self.lock:
                s = self.state()
                if body.get("mode") == "run":
                    s["mode"][agent] = "run"
                else:
                    s["mode"].pop(agent, None)
                self.save(s)
            return {"ok": True}
        if op == "update_copy":
            done, kept = self.update_copy(agent)
            return {"ok": True, "updated": done, "kept": kept}
        return {"error": "unknown op"}
