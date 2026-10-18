#!/bin/bash
# Delete files/folders for an agent: only inside the agent's own folder
# (DIRAI_AGENT_DIR, set by agents.py for each run). Every path is resolved first (symlinks,
# "..") and refused unless it lies inside that folder; the folder itself can't be deleted.
# Deletion is immediate (rm -rf), with no trash.
#   usage: agent_rm.sh PATH...
set -u
AGENT=$(realpath -e "${DIRAI_AGENT_DIR:-}" 2>/dev/null) || { echo "agent_rm: DIRAI_AGENT_DIR not set; only agents can use this" >&2; exit 2; }
status=0
for target in "$@"; do
    if [[ -L "$target" ]]; then                  # a symlink: remove the link, never what it points to
        link_dir=$(realpath -e -- "$(dirname -- "$target")" 2>/dev/null)
        if [[ "$link_dir" == "$AGENT" || "$link_dir" == "$AGENT"/* ]]; then
            rm -f -- "$target" && echo "deleted link: $target" || status=1
        else
            echo "agent_rm: refused, not inside the agent folder $AGENT: $target" >&2; status=1
        fi
        continue
    fi
    real=$(realpath -e -- "$target" 2>/dev/null) || { echo "agent_rm: no such file: $target" >&2; status=1; continue; }
    if [[ "$real" == "$AGENT" || "$real" != "$AGENT"/* ]]; then
        echo "agent_rm: refused, not inside the agent folder $AGENT: $real" >&2; status=1; continue
    fi
    rm -rf -- "$real" && echo "deleted: $real" || status=1
done
exit $status
