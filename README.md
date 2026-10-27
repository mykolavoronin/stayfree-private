# stayfree-private

Build **privacy-patched copies of StayFree** (`com.burockgames.timeclocker`) from the latest official
release, automatically. This repo contains **only the patcher** (Python + shell + GitHub Actions).
It never contains the StayFree APK, decompiled code, signing keys or API keys from the app.

> ⚠️ **Personal use only.** StayFree is proprietary software. Build it for yourself from your own copy,
> don't redistribute patched APKs, and keep this repo private. No warranty. Not affiliated with
> StayFree / Sensor Tower.

## Why

A static audit of StayFree 20.18.2 ([docs/AUDIT.md](docs/AUDIT.md)) found that the "screen-time" app
embeds Sensor Tower's research-panel SDK:

- Uploads usage sessions **with demographics**, visited **websites (URLs, UTMs, query params)**,
  **AI chat prompts**, shopping/purchases, ads you saw (incl. screenshots) and **screen-text dumps**
  to `api.stayfreeapps.com` / `adbl0ck.com`. Data collection is on by default.
- Third-party trackers: Singular, Amplitude, Bugsnag, Firebase Analytics, Facebook SDK, advertising ID.
- **Accessibility service** listens to every event, reads every app's screen, was allowed to take
  **screenshots**, and has scrapers for social, shopping, ride-hailing and some finance apps. No filter
  that drops password-field text before upload (Android blanks most password text for accessibility,
  but screenshots show whatever is on screen).
- The optional StayFresh e-mail feature injects WebView JavaScript that captures generated
  **Google/Yahoo app passwords**.
- Hard-coded API keys and a static AES key (redacted in the docs).

## The two presets

| | `sync` (milder, default for daily use) | `max` (strict, local-only) |
|---|---|---|
| Sensor Tower research-panel uploads | ❌ blocked per endpoint | ❌ blocked (hosts → `.invalid`) |
| Singular / Amplitude / Bugsnag / Firebase Analytics / Facebook events / AD_ID | ❌ | ❌ |
| Accessibility screenshots | ❌ | ❌ |
| StayFresh e-mail backend + app-password scripts | ❌ backend blocked | ❌ backend + scripts emptied |
| Cross-device **sync / pairing / friends** | ✅ kept | ❌ |
| Remote config (`config.stayfreeapps.com`), app categories & icons | ✅ kept | ❌ (bundled defaults) |
| Firebase Installations / Remote Config / FCM push | ✅ kept | ❌ |
| Play Billing (premium) | kept in code — see limits below | kept in code — see limits below |
| Local features: usage stats, limits, overlays, focus/sleep modes, widgets, app lock, website blocking | ✅ | ✅ |

Details per patch: [docs/VARIANTS.md](docs/VARIANTS.md).

## Verified vs untested

Tested on the box, StayFree **20.18.2**, 27 Oct 2026:

| Check | `sync` | `max` |
|---|---|---|
| Upstream signer = Play cert `5b4aa54d…617593` | ✅ | ✅ |
| Strict patch run: all critical targets found, 0 warnings | ✅ 8/8 | ✅ 15/15 |
| apksigner verify (v2/v3, own key) | ✅ | ✅ |
| Static smoke test: blocked hosts gone, sync/config endpoints and Firebase hosts kept, manifest perms/components, a11y config, **resource IDs unchanged** (11 890) | ✅ 27/27 | ✅ 26/26 |
| Installs + launches on an Android 14 emulator (x86_64 + ARM translation), no crash, onboarding screen shows | ✅¹ | ✅ |
| Onboarding → usage access → a block rule | ⚠️ untested | ⚠️ untested |
| Cross-device sync / pairing / friends | ⚠️ untested (emulator had no network) | n/a (removed) |
| Remote config, app icons/categories, FCM | ⚠️ untested | n/a |
| Premium / Play Billing | ⚠️ untested, may fail after re-signing | ⚠️ same |
| Google Sign-In | ❌ only used by the StayFresh e-mail module, which is blocked; would also fail after re-signing | ❌ |
| Real phone | ⚠️ not tested | ⚠️ not tested |

¹ Tested on a build from the same code and tools just before the final one. Builds are not byte-identical (timestamps).

The box emulator had no hardware acceleration (software CPU only), so Android itself kept showing
"not responding" dialogs. That was enough to prove the app starts, but not to click through it. Test
on your phone: open the app, finish onboarding, grant Usage access, add one app limit and see that the
block screen appears, then pair a second device (`sync`).

> Found while testing: an earlier build pipeline (APKEditor 1.4.1 merge + apktool) silently
> **renumbered 34 resources** and the app crashed on launch (`Resources$NotFoundException`).
> The build now pins APKEditor 1.4.5 and the smoke test fails the build if any resource ID moves.

### Honest limits of a re-signed APK

- **Google Sign-In:** the only Google sign-in in StayFree is in the StayFresh e-mail module (Flutter
  `google_sign_in`, OAuth clients bound to StayFree's signing-cert SHA-1). A re-signed APK *cannot*
  use it (`DEVELOPER_ERROR 10`) and there is no way around that without StayFree's Google Cloud project.
  Both presets block that module on purpose. **Sync does not use Google sign-in** — it pairs devices
  with a pairing code tied to the app's install ID, so it is not affected by re-signing.
- **Premium / Play Billing:** Google Play may refuse billing for an APK whose signature differs from
  the Play listing. Buying or restoring premium in the patched app is **not verified**. If you need
  premium, test it; otherwise assume it may not work.
- Installing requires **uninstalling the Play version first** (different signature), which wipes its
  local data. Re-pair devices afterwards.
- Firebase API keys may be restricted to StayFree's cert; if so, Remote Config/FCM fail closed in
  `sync` and the app falls back to bundled defaults.

## Feature toggles

Each patch has an id and finds its target by content (strings, Retrofit annotations, method
signatures, manifest names), not by obfuscated class names, so it keeps working across releases.

```bash
python3 patches/stayfree_patch.py list                                  # all patch ids per preset
STAYFREE_DISABLE=tracker-hosts scripts/build.sh --variant sync          # drop a patch
STAYFREE_ENABLE=webview-scripts,fcm-topics scripts/build.sh --variant sync   # add patches from max
python3 patches/stayfree_patch.py apply work/decoded --preset sync --disable email-backend --strict
```

Every run prints a per-patch summary (`OK` / `WARN` / `MISS`, with counts) and writes `report-<preset>.json`.
A missing non-critical target is a warning; a missing **critical** target stops the build with `--strict`.

## Quick start (Linux / macOS / WSL)

```bash
git clone https://github.com/mykolavoronin/stayfree-private && cd stayfree-private
scripts/setup_tools.sh                 # pinned apktool 2.10.0, APKEditor 1.4.5, uber-apk-signer 1.3.0 (+JDK 17 if missing), SHA-256 checked
scripts/build.sh                       # latest release, both presets  (--variant sync|max|both)
ls dist/                               # StayFree-<ver>-sync.apk, StayFree-<ver>-max.apk, SHA256SUMS, report-*.json, smoke-*.json
```

Other options:

```bash
scripts/build.sh --scan-only                         # detect-only: does this release still match every critical patch?
scripts/build.sh --input ~/Downloads/StayFree.xapk   # use a file you downloaded yourself
python3 scripts/fetch_latest.py --check              # just print the latest version
python3 patches/stayfree_patch.py scan <apktool-dir> --preset all --strict
```

What `build.sh` does: download (APKPure, APKMirror fallback) → **verify the original signer cert
SHA-256 = `5b4aa54dc2514c272e0a005e4c69d87fbc67ff74746763aad709e7814c617593`** (abort otherwise) →
merge splits (APKEditor) → apktool decode → patch (strict) → build → zipalign + sign → apksigner verify →
static smoke test → `SHA256SUMS`.

**Signing:** set `KEYSTORE_PATH` (or `KEYSTORE_BASE64`) + `KEYSTORE_PASSWORD`, `KEY_ALIAS`, `KEY_PASSWORD`.
If none are set, a key is generated once in `keys/` (git-ignored). **Back it up** — future updates must be
signed with the same key or Android will refuse to update (you'd have to uninstall and lose data).

Requirements: bash, python3 ≥ 3.9, curl, unzip, Java 17+.

## Install on Android

1. Uninstall Play-Store StayFree (and any other patched build signed with a different key).
2. Copy `StayFree-<ver>-sync.apk` (or `-max`) to the phone and install it (allow "install unknown apps").
   The merged APK is arm64-v8a, Android 12L+ (minSdk 32).
3. Grant **Usage access** and **Display over other apps**. Enable **Accessibility** only if you need
   website/keyword blocking — it can still read screen content locally even though uploads are dead.
4. Optional: in a firewall (NetGuard, RethinkDNS) deny everything for `max`, or allow only
   `api.stayfreeapps.com` + `config.stayfreeapps.com` + Google for `sync`.
5. Don't use StayFresh / e-mail features.

## Automation (GitHub Actions)

| Workflow | Trigger | What it does |
|---|---|---|
| `check-update.yml` | every 6 h + manual | `fetch_latest.py --check` (HEAD request only, no download) and compares with `state/last_version.json`. If new → calls `build.yml`; on success commits the new version to `state/last_version.json`. |
| `build.yml` | called by check-update, manual, weekly safety net | setup → fetch + signer check → **`--scan-only`** → build `sync` + `max` → sign → smoke test → upload APKs, `report-*.json`, `smoke-*.json`, `SHA256SUMS` as a **workflow artifact** (30 days). Optional emulator launch job (`emulator_test` input). |

**Stale-patch guard:** if the scan finds that any **critical** patch target is missing in a new release
(e.g. the panel endpoints, the opt-out switch, the upload gate, accessibility screenshots, the e-mail scripts),
the workflow **fails and opens an issue "Patch needs update for vX"** (one per version) instead of shipping a
half-patched APK. `state/last_version.json` is not updated, so it retries every 6 h until the patch is fixed.

Secrets (Settings → Secrets → Actions), all optional:

| Secret | |
|---|---|
| `KEYSTORE_BASE64` | `base64 -w0 keys/stayfree-private.jks` |
| `KEYSTORE_PASSWORD`, `KEY_ALIAS`, `KEY_PASSWORD` | from `keys/keystore.env` |

Without them the APKs are built **unsigned** with a warning. Only `GITHUB_TOKEN` is used otherwise.

**No public Releases by default** — that would redistribute StayFree. If you really want them on a
*private* repo, add a `softprops/action-gh-release` step yourself; artifacts are usually enough.

Note: APKPure/APKMirror sometimes block datacenter IPs. If fetching fails in CI, build locally.

## Repo layout

```
patches/engine.py         pattern-based patch engine (scan/apply, warnings, JSON report)
patches/presets.py        the sync and max patch lists
patches/stayfree_patch.py CLI: scan | apply --preset sync|max
patches/sync.py, max.py   thin wrappers
scripts/fetch_latest.py   resolve/download latest XAPK, verify Play signer, record version + SHA-256
scripts/build.sh          end-to-end build (--variant, --scan-only, --input, --no-sign)
scripts/setup_tools.sh    pinned, checksum-verified tools
scripts/smoke_check.py    static checks on the built APK (blocked hosts gone, sync endpoints present, manifest)
scripts/emulator_smoke.sh install + launch on an emulator, screenshot + logcat
state/last_version.json   last version built by CI
docs/AUDIT.md, VARIANTS.md
```

License: MIT for the patcher code only ([LICENSE](LICENSE)).
