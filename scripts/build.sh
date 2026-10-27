#!/usr/bin/env bash
# Build private StayFree APKs from the latest (or a given) upstream release.
#
#   scripts/build.sh [--variant sync|max|both] [--input file.xapk] [--skip-fetch] [--no-sign]
#   scripts/build.sh --scan-only      # detect-only: exit 2 if a CRITICAL patch target is missing
#   STAYFREE_DISABLE=fb-domains STAYFREE_ENABLE=webview-scripts scripts/build.sh --variant sync
#                                     # feature toggles (ids: python3 patches/stayfree_patch.py list)
#
# Signing (first match wins):
#   KEYSTORE_PATH or KEYSTORE_BASE64, plus KEYSTORE_PASSWORD, KEY_ALIAS, KEY_PASSWORD
#   otherwise a local key is generated once in keys/ (git-ignored; keep it to be able to update).
# Outputs: dist/StayFree-<ver>-<variant>.apk, dist/report-<variant>.json, dist/SHA256SUMS
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS="${TOOLS_DIR:-$ROOT/tools}"
WORK="${WORK_DIR:-$ROOT/work}"
DIST="${DIST_DIR:-$ROOT/dist}"
VARIANT=both; INPUT=""; SKIP_FETCH=0; SIGN=1; STRICT="--strict"; SCAN_ONLY=0
while [[ $# -gt 0 ]]; do case "$1" in
  --variant) VARIANT="$2"; shift 2;;
  --input) INPUT="$2"; shift 2;;
  --skip-fetch) SKIP_FETCH=1; shift;;
  --no-sign) SIGN=0; shift;;
  --no-strict) STRICT=""; shift;;
  --scan-only) SCAN_ONLY=1; shift;;
  -h|--help) sed -n '2,12p' "$0"; exit 0;;
  *) echo "unknown arg $1" >&2; exit 64;; esac; done
case "$VARIANT" in sync) VARIANTS=(sync);; max) VARIANTS=(max);; both) VARIANTS=(sync max);;
  *) echo "--variant must be sync|max|both" >&2; exit 64;; esac
[[ -x "$TOOLS/jdk/bin/java" ]] && export PATH="$TOOLS/jdk/bin:$PATH"
[[ -f "$TOOLS/apktool.jar" ]] || "$ROOT/scripts/setup_tools.sh"
J() { java -Xmx6g -jar "$@"; }
mkdir -p "$WORK" "$DIST"

# 1. fetch + verify original signer
if [[ $SKIP_FETCH == 0 ]]; then
  python3 "$ROOT/scripts/fetch_latest.py" --out "$WORK/src" ${INPUT:+--input "$INPUT"} > /dev/null
fi
VER="$(python3 -c "import json;print(json.load(open('$WORK/src/source.json'))['version'] or 'unknown')")"
echo "== StayFree $VER"

# 2. merge splits into one APK
if [[ ! -f "$WORK/merged-$VER.apk" ]]; then
  n=$(ls "$WORK/src/splits"/*.apk | wc -l)
  if [[ $n -gt 1 ]]; then J "$TOOLS/APKEditor.jar" m -i "$WORK/src/splits" -o "$WORK/merged-$VER.apk" -f > "$WORK/merge.log"
  else cp "$WORK/src/splits"/*.apk "$WORK/merged-$VER.apk"; fi
fi

# 2b. detect-only scan of every preset (nothing is modified)
if [[ $SCAN_ONLY == 1 ]]; then
  D="$WORK/decoded-scan"; rm -rf "$D"
  J "$TOOLS/apktool.jar" d -f -q "$WORK/merged-$VER.apk" -o "$D"
  set +e
  python3 "$ROOT/patches/stayfree_patch.py" scan "$D" --preset all --strict --report "$DIST/scan.json" | tee "$WORK/scan.log" | grep -v '^        '
  rc=${PIPESTATUS[0]}; set -e
  cp "$WORK/src/source.json" "$DIST/source.json"
  [[ "${KEEP_WORK:-0}" == 1 ]] || rm -rf "$D"
  exit $rc
fi

# 3. signing key
KS=""
if [[ $SIGN == 1 ]]; then
  if [[ -n "${KEYSTORE_PATH:-}" ]]; then KS="$KEYSTORE_PATH"
  elif [[ -n "${KEYSTORE_BASE64:-}" ]]; then KS="$WORK/ci.keystore"; echo "$KEYSTORE_BASE64" | base64 -d > "$KS"
  else
    KS="$ROOT/keys/stayfree-private.jks"
    if [[ ! -f "$KS" ]]; then
      mkdir -p "$ROOT/keys"; chmod 700 "$ROOT/keys"
      PW="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)"
      keytool -genkeypair -keystore "$KS" -storetype PKCS12 -alias stayfreeprivate -keyalg RSA -keysize 4096 \
        -validity 10000 -storepass "$PW" -keypass "$PW" -dname "CN=StayFree Private Build" >/dev/null 2>&1
      printf 'KEYSTORE_PASSWORD=%s\nKEY_ALIAS=stayfreeprivate\nKEY_PASSWORD=%s\n' "$PW" "$PW" > "$ROOT/keys/keystore.env"
      chmod 600 "$ROOT/keys/keystore.env" "$KS"
      echo "== generated local signing key keys/stayfree-private.jks (back it up; never commit it)"
    fi
    # shellcheck disable=SC1091
    source "$ROOT/keys/keystore.env"
  fi
  : "${KEYSTORE_PASSWORD:?KEYSTORE_PASSWORD missing}"; KEY_ALIAS="${KEY_ALIAS:-stayfreeprivate}"; KEY_PASSWORD="${KEY_PASSWORD:-$KEYSTORE_PASSWORD}"
fi

# 4. per variant: decode, patch, build, align+sign, verify
: > "$DIST/SHA256SUMS.$$"
for V in "${VARIANTS[@]}"; do
  echo "== variant $V"
  D="$WORK/decoded-$V"; rm -rf "$D"
  J "$TOOLS/apktool.jar" d -f -q "$WORK/merged-$VER.apk" -o "$D"
  python3 "$ROOT/patches/stayfree_patch.py" apply "$D" --preset "$V" $STRICT --report "$DIST/report-$V.json" | tee "$WORK/patch-$V.log" | grep -v '^        '
  rc=${PIPESTATUS[0]}; [[ $rc == 0 ]] || { echo "!! patch step failed for $V (exit $rc)"; exit $rc; }
  J "$TOOLS/apktool.jar" b -q "$D" -o "$WORK/unsigned-$V.apk"
  OUT="$DIST/StayFree-$VER-$V.apk"
  if [[ $SIGN == 1 ]]; then
    rm -rf "$WORK/signed-$V"
    J "$TOOLS/uber-apk-signer.jar" -a "$WORK/unsigned-$V.apk" -o "$WORK/signed-$V" \
      --ks "$KS" --ksAlias "$KEY_ALIAS" --ksPass "$KEYSTORE_PASSWORD" --ksKeyPass "$KEY_PASSWORD" > "$WORK/sign-$V.log"
    cp "$WORK/signed-$V"/*-aligned-signed.apk "$OUT"
    java -jar "$TOOLS/apksigner.jar" verify --print-certs "$OUT" | grep -E 'SHA-256|DN' | sed 's/^/   /'
  else
    cp "$WORK/unsigned-$V.apk" "${OUT%.apk}-unsigned.apk"; OUT="${OUT%.apk}-unsigned.apk"
    echo "   WARNING: not signed (no keystore). Android will refuse to install it until you sign it."
  fi
  if [[ -n "${STAYFREE_DISABLE:-}${STAYFREE_ENABLE:-}" ]]; then
    python3 "$ROOT/scripts/smoke_check.py" "$OUT" --variant "$V" --report "$DIST/smoke-$V.json" --reference "$WORK/merged-$VER.apk" \
      || echo "   WARNING: smoke check differs from the stock preset (expected with feature toggles)"
  else
    python3 "$ROOT/scripts/smoke_check.py" "$OUT" --variant "$V" --report "$DIST/smoke-$V.json" --reference "$WORK/merged-$VER.apk"
  fi
  (cd "$DIST" && sha256sum "$(basename "$OUT")") >> "$DIST/SHA256SUMS.$$"
  [[ "${KEEP_WORK:-0}" == 1 ]] || rm -rf "$D"
done
mv "$DIST/SHA256SUMS.$$" "$DIST/SHA256SUMS"
cp "$WORK/src/source.json" "$DIST/source.json"
echo "== done"; cat "$DIST/SHA256SUMS"
