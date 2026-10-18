#!/bin/bash
# Publish only the *.html files committed on origin/main to the gh-pages branch,
# which GitHub Pages serves (Settings -> Pages -> branch gh-pages, / (root)).
# Nothing else from the repo ends up on the public Pages site.
#
# Usage: DirAI publish [-n]   in the tree (-n: build and show the branch content, don't commit/push)
set -euo pipefail

DRY_RUN=0
[[ "${1:-}" == "-n" ]] && DRY_RUN=1

REPO=$(git rev-parse --show-toplevel)          # the tree DirAI was run in
TOOL=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
BRANCH=gh-pages
WT=$(mktemp -d) && rmdir "$WT"        # git worktree add creates it
TMP_BRANCH="$BRANCH-tmp-$$"            # only used when gh-pages doesn't exist yet
cleanup() {
    git -C "$REPO" worktree remove --force "$WT" 2>/dev/null || rm -rf "$WT"
    git -C "$REPO" branch -q -D "$TMP_BRANCH" 2>/dev/null || true
}
trap cleanup EXIT

cd "$REPO"
git fetch -q origin
if git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null; then
    git worktree add -q --detach "$WT" "origin/$BRANCH"
else
    git worktree add -q --orphan -b "$TMP_BRANCH" "$WT"
fi

# Start from an empty tree so files deleted/renamed on main disappear here too.
git -C "$WT" rm -rq --ignore-unmatch -- . >/dev/null
mapfile -t files < <(git ls-tree -r --name-only origin/main | grep -iE '\.html?$' | grep -v '^www/index\.html$')
[[ ${#files[@]} -gt 0 ]] && git archive origin/main -- "${files[@]}" | tar -x -C "$WT"

: > "$WT/.nojekyll"
# the agent list at www/index.html, headed by the tree's path like its own (not the worktree's);
# --public: without the folder sizes and token counts, and without writing their caches
TITLE=$REPO
DIRAI_TITLE=$TITLE python3 "$TOOL/lib/agent_list.py" "$WT" --public >/dev/null
cat > "$WT/index.html" <<EOF
<!doctype html>
<meta charset="utf-8">
<meta http-equiv="refresh" content="0; url=www/">
<title>$TITLE</title>
<a href="www/">$TITLE agents</a>
EOF

# only what is meant to be public: the HTML files, the agent list, the redirect and .nojekyll
# (never git add -A: anything else written into the worktree would be published too)
git -C "$WT" add -- ${files[@]+"${files[@]}"} www/index.html index.html .nojekyll
echo "Files on $BRANCH:"
git -C "$WT" diff --cached --name-status HEAD 2>/dev/null || git -C "$WT" ls-files | sed 's/^/A\t/'
if (( DRY_RUN )); then
    echo "(dry run: nothing committed)"
    exit 0
fi

if git -C "$WT" rev-parse -q --verify HEAD >/dev/null && git -C "$WT" diff --cached --quiet HEAD -- . ':!www/index.html'; then
    echo "No changes to the HTML files; nothing to publish."
    exit 0
fi
git -C "$WT" commit -q -m "Publish HTML files from main $(git rev-parse --short origin/main)"
git -C "$WT" push -q origin "HEAD:refs/heads/$BRANCH"
echo "Pushed $BRANCH of $(git remote get-url origin). Pages appear once GitHub Pages serves that branch."
