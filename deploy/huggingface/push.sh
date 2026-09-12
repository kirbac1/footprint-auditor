#!/usr/bin/env bash
# Push this repository to a Hugging Face Space, with the Space's own README
# (its front matter is what tells Spaces to build the Dockerfile).
#
#   ./deploy/huggingface/push.sh <your-hf-username>/<space-name>
#
# The Space must already exist: create it at https://huggingface.co/new-space
# with SDK "Docker" and hardware "CPU basic (free)". Log in first with
# `huggingface-cli login` (or `pip install -U huggingface_hub` to get it).
set -euo pipefail

space="${1:-}"
if [[ -z "$space" ]]; then
  echo "usage: $0 <hf-username>/<space-name>" >&2
  exit 1
fi

root="$(cd "$(dirname "$0")/../.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# A clean copy of what is committed: no .env, no databases, no node_modules.
git -C "$root" archive HEAD | tar -x -C "$work"
cp "$root/deploy/huggingface/README.md" "$work/README.md"

cd "$work"
git init -q -b main
git add -A
git -c user.name="$(git -C "$root" log -1 --format=%an)" \
    -c user.email="$(git -C "$root" log -1 --format=%ae)" \
    commit -qm "Deploy $(git -C "$root" rev-parse --short HEAD)"
git remote add space "https://huggingface.co/spaces/$space"
git push --force space main

echo
echo "Pushed. The Space builds the Dockerfile; first build takes a few minutes."
echo "Set the variables and secrets from deploy/huggingface/space.env before it starts."
echo "https://huggingface.co/spaces/$space"
