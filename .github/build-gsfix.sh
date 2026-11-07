#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Builds src/gsfix.so in an Ubuntu 22.04 container (glibc 2.35, libwayland 1.20), so the result
# also runs on older systems than the runner's. Used by the release workflow (for the archive) and
# the tests workflow (so a build error shows up before a release).
#
#   .github/build-gsfix.sh [output]    (default: src/gsfix.so)
set -euo pipefail
cd "$(dirname "$0")/.."
out="${1:-src/gsfix.so}"
tmp=".gsfix.so.tmp"  # inside the repository folder, the only one the container sees
docker run --rm -e DEBIAN_FRONTEND=noninteractive -v "$PWD:/w" -w /w ubuntu:22.04 sh -c '
  apt-get update -qq &&
  apt-get install -y -qq --no-install-recommends gcc libc6-dev libwayland-dev >/dev/null &&
  gcc -O2 -Wall -Werror -shared -fPIC -o "$1" src/gsfix.c -ldl &&
  chown "$2" "$1"' sh "$tmp" "$(id -u):$(id -g)"
mv "$tmp" "$out"
echo "$out built (Ubuntu 22.04)"
