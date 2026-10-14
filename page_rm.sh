#!/bin/bash
# Delete files/folders for a page agent: only inside the agent's own page folder
# (REVIEW_PAGE_DIR, set by review.py for each run). Every path is resolved first (symlinks,
# "..") and refused unless it lies inside that folder; the folder itself can't be deleted.
# Deletion is immediate (rm -rf), with no trash.
#   usage: page_rm.sh PATH...
set -u
PAGE=$(realpath -e "${REVIEW_PAGE_DIR:-}" 2>/dev/null) || { echo "page_rm: REVIEW_PAGE_DIR not set; only page agents can use this" >&2; exit 2; }
status=0
for target in "$@"; do
    if [[ -L "$target" ]]; then                  # a symlink: remove the link, never what it points to
        link_dir=$(realpath -e -- "$(dirname -- "$target")" 2>/dev/null)
        if [[ "$link_dir" == "$PAGE" || "$link_dir" == "$PAGE"/* ]]; then
            rm -f -- "$target" && echo "deleted link: $target" || status=1
        else
            echo "page_rm: refused, not inside the page folder $PAGE: $target" >&2; status=1
        fi
        continue
    fi
    real=$(realpath -e -- "$target" 2>/dev/null) || { echo "page_rm: no such file: $target" >&2; status=1; continue; }
    if [[ "$real" == "$PAGE" || "$real" != "$PAGE"/* ]]; then
        echo "page_rm: refused, not inside the page folder $PAGE: $real" >&2; status=1; continue
    fi
    rm -rf -- "$real" && echo "deleted: $real" || status=1
done
exit $status
