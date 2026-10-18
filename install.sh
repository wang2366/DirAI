#!/bin/bash
# Install or update DirAI:
#   curl -fsSL https://raw.githubusercontent.com/wang2366/DirAI/main/install.sh | bash
# or, from a checkout you already have:  ./install.sh
# Clones (or pulls) DirAI into $DIRAI_HOME (default ~/.local/share/dirai) and links the DirAI
# command into $DIRAI_BIN (default ~/.local/bin). Run it again to update.
#   DIRAI_REPO   where to clone from (default https://github.com/wang2366/DirAI.git; an
#                git@github.com:... URL uses your SSH key, e.g. while the repo is private)
#   DIRAI_REF    branch to install (default main)
set -euo pipefail

REPO=${DIRAI_REPO:-https://github.com/wang2366/DirAI.git}
REF=${DIRAI_REF:-main}
BIN=${DIRAI_BIN:-$HOME/.local/bin}

say() { printf '%s\n' "$*"; }
die() { printf 'DirAI install: %s\n' "$*" >&2; exit 1; }

for c in git python3 curl; do
    command -v "$c" >/dev/null 2>&1 || die "needs $c on PATH"
done
python3 -c 'import sys; sys.exit(sys.version_info < (3, 6))' || die "needs Python 3.6+"

# run from inside a checkout (./install.sh): install that one, without cloning
SELF=${BASH_SOURCE[0]:-}
if [[ -n "$SELF" && -f "$SELF" && -x "$(dirname "$SELF")/bin/DirAI" ]]; then
    HOME_DIR=$(cd "$(dirname "$SELF")" && pwd -P)
    say "Using this checkout: $HOME_DIR"
else
    HOME_DIR=${DIRAI_HOME:-$HOME/.local/share/dirai}
    if [[ -d "$HOME_DIR/.git" ]]; then
        say "Updating $HOME_DIR"
        git -C "$HOME_DIR" fetch -q origin "$REF"
        git -C "$HOME_DIR" checkout -q "$REF"
        git -C "$HOME_DIR" merge -q --ff-only "origin/$REF" \
            || die "$HOME_DIR has local changes that block the update; commit or drop them and rerun"
    elif [[ -e "$HOME_DIR" ]]; then
        die "$HOME_DIR exists and is not a git checkout; move it or set DIRAI_HOME"
    else
        say "Cloning $REPO into $HOME_DIR"
        mkdir -p "$(dirname "$HOME_DIR")"
        git clone -q --branch "$REF" "$REPO" "$HOME_DIR" \
            || die "clone failed (a private repo needs DIRAI_REPO=git@github.com:wang2366/DirAI.git)"
    fi
fi

mkdir -p "$BIN"
ln -sfn "$HOME_DIR/bin/DirAI" "$BIN/DirAI"
say "Linked $BIN/DirAI -> $HOME_DIR/bin/DirAI"

# repoint ~/.config/dirai/AGENT_RULE.md if a running tree's checkout moved (DirAI start does this too)
mkdir -p "$HOME/.config/dirai"
ln -sfn "$HOME_DIR/AGENT_RULE.md" "$HOME/.config/dirai/AGENT_RULE.md"

CLAUDE=${REVIEW_CLAUDE_CMD:-$HOME/.local/bin/claude}
if [[ ! -x "$CLAUDE" ]]; then
    say ""
    say "Claude Code not found at $CLAUDE. Install it with"
    say "    curl -fsSL https://claude.ai/install.sh | bash"
    say "or set REVIEW_CLAUDE_CMD to its path."
fi

case ":$PATH:" in *":$BIN:"*) ;; *)
    say ""
    say "$BIN is not on your PATH. Add this to ~/.bashrc (or your shell's rc file):"
    say "    export PATH=\"$BIN:\$PATH\""
esac

say ""
say "Done. Next, in the folder to serve:  DirAI init && DirAI start"
