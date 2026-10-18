# DirAI

Serve any git repo as a set of agents: every folder holding an `index.html` is one, browsable in
your browser, with a Claude Code agent working in it.

An agent's `index.html` is its report. It starts with a summary card (Objective, Inputs,
Outputs, Result, Open, Updated; see `AGENT_RULE.md`) and carries no CSS (the server links the shared
`index.css`). DirAI lists every agent on the repo's `www/index.html`, the agent list. The owner gets
the agent's panel on each `index.html`: a message there starts a background `claude -p` session in
that folder, which edits `index.html`, reruns scripts or submits jobs, then replies in the thread.
The parts of `index.html` its latest edit added or changed are highlighted (compared with a copy
saved before the run, in `www/before_run/`).

If a run leaves SLURM jobs in the queue (ones it submitted, or any of yours running in the agent's
folder), the agent stays "working" while the server checks the queue (`sacct`) every 10 minutes, which
costs no tokens. When the jobs have all left the queue, the server sends the agent their `sacct`
results so it can update `index.html`. A message can still go in while the agent waits. Five automatic
messages in a row is the limit, until you send one yourself.

An agent can also get the same message on a schedule: pick Every hour / day / week in
its panel (or in the New agent form) and give the message. The first run is one period later
(New agent also runs it right away), later ones keep that time of day. A run that comes due while
the agent is busy or waiting on jobs goes when it is free; one missed while the server was down is
sent once on restart. Each scheduled run starts a fresh session, without the earlier conversation:
it reads the agent's `index.html` (its summary card first). A message you send afterwards continues that
run's session. `index.html` is the memory between runs, so each run records its result there
with the date. Thread entries older than a week are dropped from the panel (each agent keeps at
least its last 6).

## Setup (once per machine)

```bash
curl -fsSL https://raw.githubusercontent.com/wang2366/DirAI/main/install.sh | bash
```

This clones DirAI into `~/.local/share/dirai`, links `~/.local/bin/DirAI` to it, and says what is
missing (Claude Code, `~/.local/bin` on your PATH). Run it again to update. Settings:
`DIRAI_HOME` (where to clone), `DIRAI_BIN` (where to link the command), `DIRAI_REF` (branch), and
`DIRAI_REPO` (clone URL).

While the repo is private, curl can't fetch the script (GitHub answers 404 without a login), so
collaborators clone it with their SSH key and run the script there, which links that checkout:

```bash
git clone git@github.com:wang2366/DirAI.git ~/.local/share/dirai && ~/.local/share/dirai/install.sh
```

To update that checkout later: `git -C ~/.local/share/dirai pull`.

The checkout can live anywhere. `DirAI init` and `DirAI start` keep `~/.config/dirai/AGENT_RULE.md`
linked to it, and a tree's `CLAUDE.md` imports the agent rules from there, so the committed import
line works on every machine. After moving the checkout, update the PATH link and run `DirAI start`
(or `init`) once to repoint it. Trees set up when the rules file was `PAGES.md` get their
`CLAUDE.md` import line rewritten by the next `DirAI start` or `init`.

Needs Python 3.6+, `git`, `curl`, and Claude Code (`~/.local/bin/claude`, or set `DIRAI_CLAUDE_CMD`).

### Updating from a version before 2026-10

The checkout was reorganized (`bin/`, `lib/`, `web/`, `scripts/`) and "page" became "agent". After
updating, run `DirAI stop && DirAI start` once in each running tree: `DirAI restart` would reload
the server from its old path. On its first start, a tree's `www/reviews.json` becomes
`www/agents.json` and `www/page_prev/` becomes `www/before_run/`, and their `.gitignore` lines are
added. `REVIEW_CLAUDE_CMD` still works, as the old name of `DIRAI_CLAUDE_CMD`. The old
`www/page_sizes.json` and `www/page_tokens.json` caches are no longer used and can be deleted.

## Use (per tree)

A tree is the folder DirAI serves: a git repo, or any folder (e.g. `~/work` holding several repos).

```bash
cd <your folder>      # a repo: anywhere inside it; another folder: its top
DirAI init            # www/dirai.json (port); in a repo also .gitignore lines and the CLAUDE.md import
DirAI start           # on this machine; or: DirAI start NODE | --job (its own sbatch job)
DirAI status | restart | stop | build | list
```

Later commands work from anywhere below the tree: DirAI uses the nearest folder above you holding
`www/dirai.json`, else the git repo you are in. Outside git, `init` asks before adding the agent
rules to `CLAUDE.md` (there it would reach every project below), skips `.gitignore`, and `publish`
is unavailable; agents get git instructions only when their folder is inside a repo. `init` refuses
`/` and your home folder, and `start` refuses a tree that overlaps one already running.

Each tree (each clone, even of the same repo) runs its own server on its own port, so trees start
and stop independently. `DirAI list` shows them all.

Opening an agent as the owner: connect through an SSH tunnel to the node, then visit
`/_review/login?key=<~/.config/dirai/key>` once to set the owner cookie.

`DirAI publish` puts the tree's committed `*.html` files and an agent list on its `gh-pages` branch
for GitHub Pages. That list has no folder sizes or token counts, and nothing else from `www/` is
published.

## Where things live

| Where | What |
|---|---|
| this repo | the tool: `bin/` the `DirAI` command and `dirai_serve`; `lib/` the Python (`server.py`, the agent list `agent_list.py`, the agents `agents.py` with `agent_permissions.py`, `agent_prompts.py`, `claude_run.py`, SLURM jobs `slurm.py`); `web/` `index.css` and the panel scripts; `scripts/` `agent_rm.sh`, `publish_pages.sh`; `AGENT_RULE.md` rules for agents |
| `<repo>/www/` | per tree, generated and gitignored: the agent list, threads and agent state (`agents.json`), `before_run/`, caches, `server_host.txt`, logs, and `dirai.json` settings |
| `~/.config/dirai/` | per user: owner key, "Always allow" grants, shared Claude usage reading, the list of trees, and `AGENT_RULE.md` (a link to this checkout's rules for agents) |

`www/dirai.json`:

```json
{"port": 8765,
 "read_dirs": ["/data/shared"],              "allow": ["Bash(~/tools/run.sh:*)"],
 "slurm": ["-A", "mygroup", "-p", "cpu"],   "exclude": ["data", "projA/build"],
 "permissions": "allowlist"}
```

`read_dirs`: extra folders agents may read (the repo itself always). `allow`: extra
Claude Code permission rules for them. `slurm`: extra `sbatch` options for `DirAI start --job`. `permissions`: `"allowlist"` (default) or `"ask"`, see below; the agent list's **Agent permissions** switch sets it. `exclude`: folders the agent list skips (a name skips it anywhere, a path with a slash skips that one folder; virtualenvs, `node_modules` and caches are always skipped).

## Agent safety

Runs use `claude -p --restricted` with an allow list (`agent_permissions.py`): reads only inside the agent's
own area (its nearest git repo, or its own folder outside any repo; the tree's top agent sees the
whole tree) and `read_dirs`. To let an agent read another folder of the tree, name the path in your
message (granted for that agent automatically) or click Allow when a read is blocked; folder reads
stay with that agent even under "Always allow". Scripts the agent runs (`python3 x.py`) are not
confined by this, only Claude's own file tools and simple shell commands; edits only in the agent's folder, deletions only through `agent_rm.sh`, destructive git
commands always denied. What happens to an action that isn't allowed depends on the tree's
**Agent permissions** (top of the agent list; `permissions` in `dirai.json`; it applies from each
agent's next run, and a session continues across a switch):

- **Allow list** (default): the run is refused it (`--permission-mode dontAsk`) and carries on
  without it; afterwards the panel lists what was blocked, with "Allow once" / "Always allow", which
  grant it and resume the run.
- **Ask in chat**: the run waits, and the agent's chat shows the request with **Allow** / **Always
  allow** / **Deny** (the agent is marked "needs you" in the list); the run continues with your
  answer (`--permission-prompt-tool stdio`). Waiting costs no tokens, but a waiting run holds one of
  the 5 run slots, so after 12 h of waiting in total (`ASK_WAIT_S`) a run's requests are denied, and
  Claude is told not to ask again for something you denied. The 4 h run limit counts working time only.

The owner's MCP servers (user scope, local scope of the agent's folder or one above it, and
`.mcp.json` files there) are passed to every run with `--mcp-config` (`--restricted` would ignore
`~/.claude.json`); their tools are not pre-allowed, so each call needs a grant or your answer.
claude.ai connectors (Gmail, Drive, ...) can't be passed this way.
New tasks pause when Claude's 5-hour or weekly usage reaches its pause level, and resume by
themselves (`claude_usage.py`). The 5-hour level is 100 % unless you drag the marker on its bar on
the agent list lower; it resumes after the reset. The weekly level follows the day of the week while
its **Auto** button is on (the default): n/7 of the limit on day n of the 7-day window, so a paused
run resumes when the next day starts; dragging its marker sets it by hand (Auto off) and it resumes
after the weekly reset. The levels apply to all your trees.

## Tests

```bash
python3 -m unittest discover -s tests -t .     # from the DirAI checkout; no extra packages
```

`tests/test_helpers.py` covers the pure helpers (permission rules, selections, summary cards,
config), `tests/test_agents.py` the message queue and its state in `agents.json`, and
`tests/test_server.py` runs `lib/server.py` on a temporary tree with `tests/fake_claude.py`
standing in for `claude`, and the agent list (`--public` included). Nothing touches
`~/.config/dirai` or `~/.claude`.
