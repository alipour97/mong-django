#!/usr/bin/env bash
# Builds the two Runflare upload packages from the last commit of this branch.
# Only what each service runs goes in: no .env, no _src, no docs.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
out="$PWD/dist/runflare"
mkdir -p "$out"

git archive --format=zip -o "$out/backend.zip" HEAD manage.py requirements.txt config apps
git archive --format=zip -o "$out/frontend.zip" HEAD:mong_front

ls -lh "$out"
