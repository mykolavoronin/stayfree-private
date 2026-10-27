#!/usr/bin/env bash
# Install each built APK on a running emulator/device, launch it, capture a
# screenshot + logcat, and fail on a crash.  Usage: emulator_smoke.sh <dist-dir>
set -uo pipefail
DIST="${1:-dist}"; OUT="${OUT_DIR:-emu-out}"; PKG=com.burockgames.timeclocker
mkdir -p "$OUT"; fail=0
for apk in "$DIST"/StayFree-*-sync.apk "$DIST"/StayFree-*-max.apk; do
  [[ -f "$apk" ]] || continue
  v=$(basename "$apk" .apk); echo "== $v"
  adb uninstall "$PKG" >/dev/null 2>&1
  adb logcat -c
  if ! adb install -r -g "$apk" > "$OUT/$v-install.txt" 2>&1; then echo "install FAILED"; cat "$OUT/$v-install.txt"; fail=1; continue; fi
  adb shell appops set "$PKG" GET_USAGE_STATS allow || true
  adb shell appops set "$PKG" SYSTEM_ALERT_WINDOW allow || true
  adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
  sleep 25
  adb exec-out screencap -p > "$OUT/$v-launch.png"
  pid=$(adb shell pidof "$PKG" | tr -d '\r')
  adb logcat -d > "$OUT/$v-logcat.txt"
  if grep -qE "FATAL EXCEPTION.*|Process: $PKG" "$OUT/$v-logcat.txt" && grep -q "FATAL EXCEPTION" "$OUT/$v-logcat.txt"; then
    echo "CRASH detected"; grep -A20 "FATAL EXCEPTION" "$OUT/$v-logcat.txt" | head -40; fail=1
  elif [[ -z "$pid" ]]; then echo "process not running after launch"; fail=1
  else echo "running (pid $pid)"; fi
  grep -oE "(UnknownHost|Unable to resolve host|Failed to connect to)[^\n]{0,120}" "$OUT/$v-logcat.txt" | sort | uniq -c | head -20 > "$OUT/$v-blocked-net.txt"
done
exit $fail
