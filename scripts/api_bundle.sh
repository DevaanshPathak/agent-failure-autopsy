#!/bin/sh
# Build the API's Vercel deploy directory from HEAD: apps/api plus a copy of fixtures/
# (demo sites, the sample run, recorded traces). Prints the directory to deploy from.
# Usage: scripts/api_bundle.sh <out-dir>   then: cd <printed dir> && vercel --prod --yes
set -eu
out="${1:?usage: scripts/api_bundle.sh <out-dir>}"
root="$(git rev-parse --show-toplevel)"
rm -rf "$out"
mkdir -p "$out"
git -C "$root" archive HEAD apps/api fixtures | tar -x -C "$out"
mv "$out/fixtures" "$out/apps/api/fixtures"
# The Vercel project link (gitignored) lives in apps/api/.vercel once linked.
if [ -d "$root/apps/api/.vercel" ]; then cp -r "$root/apps/api/.vercel" "$out/apps/api/"; fi
echo "$out/apps/api"
