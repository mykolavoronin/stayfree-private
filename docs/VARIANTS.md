# Presets

Both presets patch the **same** upstream APK (signer verified against the Play App Signing cert
`5b4aa54d…617593`). Every patch locates its target by content (strings, Retrofit annotations,
method signatures, manifest names), so it survives R8 renames. Patches marked **critical**
must find their target or the build stops (`--strict`, used by `build.sh` and CI).

## `sync` — milder, keeps the app working like the original

Block **only** tracking, the Sensor Tower research panel, ads/attribution and the e-mail harvest.

| Patch | Critical | What it does |
|---|---|---|
| `panel-endpoints` | yes | 37 Retrofit upload endpoints (usage demographics, websites, query params, AI prompts, shopping, IAP, ad creatives/screenshots, brand mentions, accessibility screen dumps, AI screen analysis, uninstall/install pings, avg-usage comparisons, badges) → `https://127.0.0.1/blocked/…`. Per endpoint, **not** per host: `api.stayfreeapps.com/sync/*` keeps working. Fails if < 60 % of the list is found (API moved). |
| `usage-sdk-optout` | yes | Sensor Tower usage SDK's `()Z` getters that read `usage-sdk-opt-out` return `true` — the same state as the app's own "opt out of data collection" toggle. |
| `tracker-hosts` | | Singular, Amplitude, Bugsnag/InsightHub, `app-measurement.com`, Crashlytics settings, `adbl0ck.com` → `127.0.0.1` (only in string constants). |
| `ad-id-perms` | | Removes `AD_ID` + 4 `ACCESS_ADSERVICES_*` permissions. |
| `sdk-kill-switches` | | Firebase Analytics/Crashlytics/Perf/Sessions + Facebook auto-events/AAID off via `<meta-data>`. |
| `a11y-no-screenshot` | yes | Removes `canTakeScreenshot` from the accessibility service config. Website blocking (reads URL bar text) still works. |
| `email-backend` | | Flutter `libapp.so`: `purchases.stayfreeapps.com` (StayFresh e-mail reading / OAuth) and the `api.stayfreeapps.com/staywise` breach lookup → `.invalid` (same-length byte patch). |
| `split-fixups` | | Needed because we ship one merged APK instead of Play split APKs. |

**Kept on purpose:** `api.stayfreeapps.com` (sync, pairing, friends, devices, limits), `config.stayfreeapps.com`
(remote parser/feature config used by website/keyword blocking), app categories & icons, Firebase
Installations / Remote Config / FCM, Google Play services, Play Billing.

## `max` — strict, local-only

Everything StayFree/Sensor Tower/tracker/Firebase/support-related is rewritten to `*.invalid`
(same length, also inside `libapp.so`), SDK initialisers stubbed, upload/measurement/push components removed.

| Patch | Critical |
|---|---|
| `host-rewrite` (smali + resources), `host-rewrite-native` (libapp.so) | yes / |
| `usage-sdk-optout`, `upload-gate` (DataUploadJob aborts) | yes |
| `panel-endpoints` (belt and braces) | |
| `fb-domains`, `sdk-initializers` (Singular, Amplitude), `fcm-topics` (`update_prefs_remotely`) | |
| `a11y-no-screenshot`, `webview-scripts` (empties the StayFresh JS that captures Google/Yahoo app passwords) | yes |
| `permissions` (AD_ID, AdServices, install referrer, C2DM, GET_ACCOUNTS), `components`, `sdk-kill-switches`, `hardening` (no cleartext, no backup), `split-fixups` | |

**Breaks by design:** cloud sync, pairing, friends, push, remote config updates (bundled defaults are used),
StayFresh e-mail, Help Scout chat, crash reports. **Local features** (usage stats, limits, overlays,
focus/sleep modes, widgets, app lock, website blocking via accessibility) do not need the network.

## Feature matrix

See the README for what was actually verified on an emulator versus what is expected but untested.
