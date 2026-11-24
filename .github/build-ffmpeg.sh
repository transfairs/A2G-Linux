#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Builds src/ffmpeg.exe for src/a2patcher.exe: a Windows ffmpeg (MinGW-w64, static, LGPL) with just
# what the conversion of the Indeo 3 videos needs: the AVI demuxer and muxer, the Indeo 3 decoder,
# the MS Video 1 encoder and the scaler for RGB555. Used by the release workflow (for the archive).
#
#   .github/build-ffmpeg.sh [output]    (default: src/ffmpeg.exe; needs x86_64-w64-mingw32-gcc, curl, make)
set -euo pipefail
cd "$(dirname "$0")/.."
out="${1:-src/ffmpeg.exe}"
version=7.1.1
sha256=733984395e0dbbe5c046abda2dc49a5544e7e0e1e2366bba849222ae9e3a03b1
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -sSfL -o "$tmp/ffmpeg.tar.xz" "https://ffmpeg.org/releases/ffmpeg-$version.tar.xz"
echo "$sha256  $tmp/ffmpeg.tar.xz" | sha256sum -c --quiet
tar -xJf "$tmp/ffmpeg.tar.xz" -C "$tmp"
(
  cd "$tmp/ffmpeg-$version"
  ./configure --enable-cross-compile --arch=x86_64 --target-os=mingw32 --cross-prefix=x86_64-w64-mingw32- \
    --disable-everything --disable-autodetect --disable-x86asm --disable-doc --disable-debug \
    --disable-network --disable-ffplay --disable-ffprobe --disable-avdevice --disable-swresample \
    --enable-small --extra-ldflags=-static \
    --enable-decoder=indeo3 --enable-encoder=msvideo1 --enable-demuxer=avi --enable-muxer=avi \
    --enable-protocol=file --enable-filter=scale,format,null >/dev/null
  make -j"$(nproc)" ffmpeg.exe >make.log 2>&1 || { tail -30 make.log; exit 1; }
  x86_64-w64-mingw32-strip ffmpeg.exe
)
cp "$tmp/ffmpeg-$version/ffmpeg.exe" "$out"
echo "$out built (ffmpeg $version, $(du -h "$out" | cut -f1))"
