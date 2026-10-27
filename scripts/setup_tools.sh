#!/usr/bin/env bash
# Download pinned, checksum-verified build tools into ./tools (never committed).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS="${TOOLS_DIR:-$ROOT/tools}"
mkdir -p "$TOOLS"

fetch() { # url dest sha256
  local url="$1" dest="$2" sum="$3"
  if [[ -f "$dest" ]] && echo "$sum  $dest" | sha256sum -c --status; then
    echo "[tools] ok   $(basename "$dest")"; return; fi
  echo "[tools] get  $url"
  curl -fsSL --retry 3 -o "$dest.part" "$url"
  echo "$sum  $dest.part" | sha256sum -c --status || { echo "[tools] CHECKSUM MISMATCH for $url" >&2; rm -f "$dest.part"; exit 1; }
  mv "$dest.part" "$dest"
}

fetch https://github.com/iBotPeaches/Apktool/releases/download/v2.10.0/apktool_2.10.0.jar \
  "$TOOLS/apktool.jar" c0350abbab5314248dfe2ee0c907def4edd14f6faef1f5d372d3d4abd28f0431
fetch https://github.com/REAndroid/APKEditor/releases/download/V1.4.5/APKEditor-1.4.5.jar \
  "$TOOLS/APKEditor.jar" 71999a1f28cf6b457aff17c139436349cd6ea30d75a0f9cd52f07bd52e21897b
fetch https://github.com/patrickfav/uber-apk-signer/releases/download/v1.3.0/uber-apk-signer-1.3.0.jar \
  "$TOOLS/uber-apk-signer.jar" e1299fd6fcf4da527dd53735b56127e8ea922a321128123b9c32d619bba1d835

# apksigner (AOSP build-tools 33.0.2) ships inside uber-apk-signer; extract it for verify --print-certs
if [[ ! -f "$TOOLS/apksigner.jar" ]]; then
  tmp="$(mktemp -d)"; unzip -q -o "$TOOLS/uber-apk-signer.jar" 'lib/apksigner_33_0_2.jar' -d "$tmp"
  mv "$tmp/lib/apksigner_33_0_2.jar" "$TOOLS/apksigner.jar"; rm -rf "$tmp"
fi

# JDK 17: reuse one on PATH (e.g. actions/setup-java), else pinned Temurin 17.0.21+9
if command -v java >/dev/null && java -version 2>&1 | grep -qE 'version "(1[7-9]|2[0-9])'; then
  echo "[tools] ok   java on PATH ($(java -version 2>&1 | head -1))"
else
  fetch "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.21%2B9/OpenJDK17U-jdk_x64_linux_hotspot_17.0.21_9.tar.gz" \
    "$TOOLS/jdk.tgz" 8b9b611d917e3dfd8419d3566b5949226f69b052fed7e109c1368add1dfe8711
  rm -rf "$TOOLS/jdk" && mkdir -p "$TOOLS/jdk" && tar -xzf "$TOOLS/jdk.tgz" -C "$TOOLS/jdk" --strip-components=1
  echo "[tools] JDK in $TOOLS/jdk (export PATH=$TOOLS/jdk/bin:\$PATH)"
fi
echo "[tools] done -> $TOOLS"
