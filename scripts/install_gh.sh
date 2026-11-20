#!/usr/bin/env bash
# Install GitHub's gh CLI without sudo: the latest official release tarball from github.com/cli/cli,
# unpacked in ~/.local/share/gh and linked as ~/.local/bin/gh. Linux or macOS, x86_64 or arm64. Run again
# to update. The Share pill's "Install gh" button runs this (lib/shares.py).
set -eu
case "$(uname -s)" in Linux) os=linux ext=tar.gz ;; Darwin) os=macOS ext=zip ;; *) echo "unsupported OS" >&2; exit 1 ;; esac
case "$(uname -m)" in x86_64|amd64) arch=amd64 ;; aarch64|arm64) arch=arm64 ;; *) echo "unsupported CPU $(uname -m)" >&2; exit 1 ;; esac
# the latest tag, from where /releases/latest redirects (no API call, so no rate limit)
tag=$(curl -fsSLo /dev/null -w '%{url_effective}' https://github.com/cli/cli/releases/latest)
v=${tag##*/v}
name=gh_${v}_${os}_${arch}
dest=$HOME/.local/share/gh
mkdir -p "$dest" "$HOME/.local/bin"
echo "downloading $name.$ext"
if [ "$ext" = zip ]; then
    curl -fsSLo "$dest/$name.zip" "https://github.com/cli/cli/releases/download/v$v/$name.zip"
    (cd "$dest" && unzip -oq "$name.zip" && rm "$name.zip")
else
    curl -fsSL "https://github.com/cli/cli/releases/download/v$v/$name.tar.gz" | tar xz -C "$dest"
fi
ln -sfn "$dest/$name/bin/gh" "$HOME/.local/bin/gh"
"$HOME/.local/bin/gh" --version
