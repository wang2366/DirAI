# DirAI

Serve any git repo as browsable HTML pages, with a Claude Code assistant on every page.

Each page folder holds an `index.html`, which starts with a summary card (Objective, Inputs,
Outputs, Result, Open, Updated; see `AGENT_RULE.md`) and carries no CSS (the server links the shared
`page.css`). DirAI lists them on the repo's `www/index.html`. The owner gets an assistant panel on each page: a comment there starts a
background `claude -p` session in that folder, which edits the page, reruns scripts or submits
jobs, then replies in the thread. The parts of the page its latest edit added or changed are
highlighted (compared with a copy saved before the run, in `www/page_prev/`).

If a run leaves SLURM jobs in the queue (ones it submitted, or any of yours running in the page
folder), the page stays "working" while the server checks the queue (`sacct`) every 10 minutes, which
costs no tokens. When the jobs have all left the queue, the server sends the assistant their `sacct`
results so it can update the page. A comment can still go in while the page waits. Five automatic
messages in a row is the limit, until you comment again.

A page's assistant can also get the same message on a schedule: pick Every hour / day / week in
its panel (or in the New agent form) and give the message. The first run is one period later
(New agent also runs it right away), later ones keep that time of day. A run that comes due while
the page is busy or waiting on jobs goes when it is free; one missed while the server was down is
sent once on restart. Each scheduled run starts a fresh session, without the earlier conversation:
it reads the page's `index.html` (its summary card first). A message you send afterwards continues that
run's session. The page is the memory between runs, so each run records its result there
with the date. Thread entries older than a week are dropped from the panel (each page keeps at
least its last 6).

## Setup (once per machine)

```bash
git clone <this repo> <anywhere>/DirAI
ln -s <anywhere>/DirAI/bin/DirAI ~/.local/bin/DirAI      # any folder on your PATH
```

The checkout can live anywhere. `DirAI init` and `DirAI start` keep `~/.config/dirai/AGENT_RULE.md`
linked to it, and a tree's `CLAUDE.md` imports the page rules from there, so the committed import
line works on every machine. After moving the checkout, update the PATH link and run `DirAI start`
(or `init`) once to repoint it. Trees set up when the rules file was `PAGES.md` get their
`CLAUDE.md` import line rewritten by the next `DirAI start` or `init`.

Needs Python 3.6+, `git`, `curl`, and Claude Code (`~/.local/bin/claude`, or set `REVIEW_CLAUDE_CMD`).

## Use (per tree)

A tree is the folder DirAI serves: a git repo, or any folder (e.g. `~/work` holding several repos).

```bash
cd <your folder>      # a repo: anywhere inside it; another folder: its top
DirAI init            # www/dirai.json (port); in a repo also .gitignore lines and the CLAUDE.md import
DirAI start           # on this machine; or: DirAI start NODE | --job (its own sbatch job)
DirAI status | restart | stop | build | list
```

Later commands work from anywhere below the tree: DirAI uses the nearest folder above you holding
`www/dirai.json`, else the git repo you are in. Outside git, `init` asks before adding the page
rules to `CLAUDE.md` (there it would reach every project below), skips `.gitignore`, and `publish`
is unavailable; page assistants get git instructions only for pages inside a repo. `init` refuses
`/` and your home folder, and `start` refuses a tree that overlaps one already running.

Each tree (each clone, even of the same repo) runs its own server on its own port, so trees start
and stop independently. `DirAI list` shows them all.

Opening a page as the owner: connect through an SSH tunnel to the node, then visit
`/_review/login?key=<~/.config/dirai/key>` once to set the owner cookie.

## Where things live

| Where | What |
|---|---|
| this repo | the tool: server, list builder, assistant (`review.py`), panel scripts, `AGENT_RULE.md` rules for page agents |
| `<repo>/www/` | per tree, generated and gitignored: list page, threads (`reviews.json`), caches, `server_host.txt`, logs, and `dirai.json` settings |
| `~/.config/dirai/` | per user: owner key, "Always allow" grants, shared Claude usage reading, the list of trees, and `AGENT_RULE.md` (a link to this checkout's rules for page agents) |

`www/dirai.json`:

```json
{"port": 8765,
 "read_dirs": ["/data/shared"],              "allow": ["Bash(~/tools/run.sh:*)"],
 "slurm": ["-A", "mygroup", "-p", "cpu"],   "exclude": ["data", "projA/build"],
 "permissions": "allowlist"}
```

`read_dirs`: extra folders page assistants may read (the repo itself always). `allow`: extra
Claude Code permission rules for them. `slurm`: extra `sbatch` options for `DirAI start --job`. `permissions`: `"allowlist"` (default) or `"ask"`, see below; the list page's **Assistant permissions** switch sets it. `exclude`: folders the page list skips (a name skips it anywhere, a path with a slash skips that one folder; virtualenvs, `node_modules` and caches are always skipped).

## Assistant safety

Runs use `claude -p --restricted` with an allow list (`review.py`): reads only inside the page's
own area (its nearest git repo, or its own folder outside any repo; the tree's top page sees the
whole tree) and `read_dirs`. To let a page read another folder of the tree, name the path in your
comment (granted for that page automatically) or click Allow when a read is blocked; folder reads
stay with that page even under "Always allow". Scripts the assistant runs (`python3 x.py`) are not
confined by this, only Claude's own file tools and simple shell commands; edits only in the page's folder, deletions only through `page_rm.sh`, destructive git
commands always denied. What happens to an action that isn't allowed depends on the tree's
**Assistant permissions** (top of the list page; `permissions` in `dirai.json`; it applies from each
page's next run, and a session continues across a switch):

- **Allow list** (default): the run is refused it (`--permission-mode dontAsk`) and carries on
  without it; afterwards the panel lists what was blocked, with "Allow once" / "Always allow", which
  grant it and resume the run.
- **Ask in chat**: the run waits, and the page chat shows the request with **Allow** / **Always
  allow** / **Deny** (the page is marked "needs you" in the list); the run continues with your
  answer (`--permission-prompt-tool stdio`). Waiting costs no tokens, but a waiting run holds one of
  the 5 run slots, so after 12 h of waiting in total (`ASK_WAIT_S`) a run's requests are denied, and
  Claude is told not to ask again for something you denied. The 4 h run limit counts working time only.

The owner's MCP servers (user scope, local scope of the page's folder or one above it, and
`.mcp.json` files there) are passed to every run with `--mcp-config` (`--restricted` would ignore
`~/.claude.json`); their tools are not pre-allowed, so each call needs a grant or your answer.
claude.ai connectors (Gmail, Drive, ...) can't be passed this way.
New tasks pause when Claude's 5-hour or weekly usage reaches its stop level (100 % unless you drag
the marker on that usage bar of the list page lower; the levels apply to all your trees) and resume after the
reset (`claude_usage.py`).
