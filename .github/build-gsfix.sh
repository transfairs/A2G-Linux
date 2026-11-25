#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Builds src/gsfix.so and, next to it, src/gsdisplay.so in an Ubuntu 22.04 container (glibc 2.35,
# libwayland 1.20), so the result also runs on older systems than the runner's. Used by the release
# workflow (for the archive) and the tests workflow (so a build error shows up before a release).
#
#   .github/build-gsfix.sh [output]    (default: src/gsfix.so; gsdisplay.so goes into the same folder)
set -euo pipefail
cd "$(dirname "$0")/.."
out="${1:-src/gsfix.so}"
out2="$(dirname "$out")/gsdisplay.so"
tmp=".gsfix.so.tmp" tmp2=".gsdisplay.so.tmp"  # inside the repository folder, the only one the container sees
docker run --rm -e DEBIAN_FRONTEND=noninteractive -v "$PWD:/w" -w /w ubuntu:22.04 sh -c '
  apt-get update -qq &&
  apt-get install -y -qq --no-install-recommends gcc libc6-dev libwayland-dev >/dev/null &&
  gcc -O2 -Wall -Werror -shared -fPIC -o "$1" src/gsfix.c -ldl &&
  gcc -O2 -Wall -Werror -shared -fPIC -o "$3" src/gsdisplay.c &&
  chown "$2" "$1" "$3"' sh "$tmp" "$(id -u):$(id -g)" "$tmp2"
mv "$tmp" "$out"
mv "$tmp2" "$out2"
echo "$out and $out2 built (Ubuntu 22.04)"
