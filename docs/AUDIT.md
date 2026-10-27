# StayFree privacy & security audit

**Date:** 2026-10-27 (Europe/Madrid)  
**Method:** static analysis of the Play-signed release (decompiled locally, never committed)  
**Goal:** Identify personal-data exfiltration and produce a private hardened APK.

## App identity

| Field | Value |
|---|---|
| Play Store name | StayFree - Screen Time |
| Package | `com.burockgames.timeclocker` |
| Developer (Play) | ST Pulse (Sensor Tower) |
| Version name | 20.18.2 |
| Version code | 201802502 |
| Min / target SDK | 32 / 36 |
| Website | https://stayfreeapps.com |
| Play listing | https://play.google.com/store/apps/details?id=com.burockgames.timeclocker |

This is the well-known screen-time / focus / app-blocker app. Sensor Tower acquired / rebrands it; the code embeds a large **Sensor Tower “usage / accessibility / ad” research panel SDK** (`com.sensortower.*`) that collects far more than local screen-time limits.

## Source & checksums

| Artifact | Source | SHA-256 |
|---|---|---|
| `StayFree_20.18.2_APKPure.xapk` | APKPure latest XAPK for `com.burockgames.timeclocker` (`https://d.apkpure.net/b/XAPK/com.burockgames.timeclocker?version=latest` → `data.winudf.com/...StayFree+-+Screen+Time_20.18.2_APKPure.xapk`) | `77ddfc4ebe0367f1123709de6ab3170063f820f94bc0809359c57bc22f543e9b` |
| base APK | inside XAPK | `859ad64d6fdb07bbb03be897a4b37242b4857529237a95d4941046080ee1f03b` |
| `config.arm64_v8a.apk` | inside XAPK | `5a95304d403fb09356840bfa5659fdcdd4f2c1a6a6aa597d1bd7dae1431be850` |
| `config.xxhdpi.apk` | inside XAPK | `c6fb984b07a999d62c15d39862a4b1fe827c4e78637e4a691ef106315ebe97bd` |
| Play signing cert (v3) | CN=Android, OU=Android, O=Google Inc. (Play App Signing) | cert SHA-256 `5b4aa54dc2514c272e0a005e4c69d87fbc67ff74746763aad709e7814c617593` |

Method: XAPK unzipped → base + ABI/density splits merged with APKEditor → apktool + jadx decompile. No dynamic execution.

---

## Permissions

| Permission | Risk | Notes |
|---|---|---|
| `PACKAGE_USAGE_STATS` | High (expected) | Core screen-time feature |
| `QUERY_ALL_PACKAGES` | High | Enumerates installed apps (also uploaded in panel payloads) |
| `SYSTEM_ALERT_WINDOW` | High (expected) | Overlay for blocking UI / floating timer |
| Accessibility (`BIND_ACCESSIBILITY_SERVICE`) | **Critical** | See dedicated section |
| `BIND_NOTIFICATION_LISTENER_SERVICE` | High | Reads notification keys + package; used for local limit enforcement and Sensor Tower paths |
| `FOREGROUND_SERVICE` / `…_SPECIAL_USE` / `…_DATA_SYNC` | Medium | Always-on usage assistant + upload jobs |
| `INTERNET` / `ACCESS_NETWORK_STATE` | Required for sync / panel | |
| `POST_NOTIFICATIONS`, `VIBRATE`, `WAKE_LOCK`, `RECEIVE_BOOT_COMPLETED` | Low–medium | |
| `USE_BIOMETRIC` / `USE_FINGERPRINT` | Low | App lock |
| `GET_ACCOUNTS` (maxSdk 22) | Low on modern | |
| `AD_ID` + `ACCESS_ADSERVICES_*` (AD_ID / ATTRIBUTION / CUSTOM_AUDIENCE / TOPICS) | High (tracking) | Advertising ID / Topics API — despite “ad-free” marketing |
| `BIND_GET_INSTALL_REFERRER_SERVICE` | Medium | Install attribution (Singular / Play) |
| `c2dm.RECEIVE` | Medium | FCM push (incl. remote preference updates) |
| `CHECK_LICENSE` | Low | Play licensing |

`android:usesCleartextTraffic="true"` and `android:allowBackup="true"` were set on the stock app.

---

## Accessibility service (detailed)

**Service:** `com.burockgames.timeclocker.accessibility.StayFreeAccessibilityService`  
**Config** (`res/xml/stayfree_accessibility_service.xml`):

```xml
accessibilityEventTypes="typeAllMask"
accessibilityFeedbackType="feedbackGeneric"
notificationTimeout="300"
accessibilityFlags="flagReportViewIds|flagRetrieveInteractiveWindows"
canRetrieveWindowContent="true"
canTakeScreenshot="true"
isAccessibilityTool="false"
```

### What this means in practice

| Capability | Declared? | Observed in code / remote config |
|---|---|---|
| Receive **all** accessibility event types (`typeAllMask`) | Yes | `onAccessibilityEvent` handles clicks (`TYPE_VIEW_CLICKED=1`), window changes (`TYPE_WINDOWS_CHANGED=8388608`), notifications (`TYPE_NOTIFICATION_STATE_CHANGED=64`), and more |
| Read interactive window content / view IDs | Yes (`canRetrieveWindowContent`, `flagRetrieveInteractiveWindows`, `flagReportViewIds`) | Node trees walked; `getText()`, view IDs, package names extracted |
| Take screenshots of other apps | Yes (`canTakeScreenshot="true"`) | `takeScreenshot(...)` called from accessibility SDK helpers (`defpackage/ie`, `defpackage/y47`); remote config lists screenshot-active apps (IG, FB, Snapchat, LinkedIn, TikTok, Uber, YouTube, Truth Social) for countries including US/GB/CA/AU/…/ES |
| Filter password fields | **No dedicated filter found** | Manifest/config does **not** set `flagIncludeNotImportantViews` / password-filtering flags. Code that touches `isPassword()` only appears in accessibility *debug/dump helpers* (`a7`, `dw3`) — there is **no** clear policy that drops password-field text before upload. Stock Android already blanks password field *text* for most a11y clients, but **screenshots still show whatever is on screen** (incl. password dots / visible passwords). |
| Keystroke logging of every character | Not as a classic keylogger | No continuous `TYPE_VIEW_TEXT_CHANGED` keystroke buffer found for all apps. However, **search-box / form text is scraped** via view-ID and keyword parsers (YouTube/Instagram/Reddit/Pinterest/Snapchat/TikTok/Facebook search fields, Cash App transfers, Coinbase/Robinhood/Fidelity orders, Walmart AI prompts, Chrome Gemini overview, etc.). |
| ChatGPT / AI prompt text | Yes (when country flags enable) | Upload entity `PromptData` fields: `service`, `type`, `conversationId`, `conversationOrder`, **`text`**, `timestamp` → `ai/analytics`. Remote config currently has empty `chatgpt_prompt_parsers` / countries, but infrastructure + prompts remain in the app. |
| Shopping / ride receipts | Yes | AI screen analysis (`v1/ai/analyze_screen`) with hardcoded API key; `shopping_purchase_ai_prompt` asks the model for product, store, price, currency, quantity from **screen text**. |
| Full screen text dumps | Yes | `UploadAccessibilityScreenContentWorker` posts `APP_ID` + **`SCREEN_DUMP`** + `METADATA` → `v1/debug/accessibility_dump` (`ScreenDumpBody.screenText`). |
| Banking / finance UI | Parsers present | Chase (`com.chase.sig.android` account balances / Zelle tiles), Coinbase, Robinhood, Cash App, Fidelity — scrapers match view IDs / keywords for order confirmation and balances. |

### Local vs panel use of accessibility

- **Local (user-facing):** website URL detection for site blocking, keyword blocking, improved usage-limit reliability (as claimed in Play listing).
- **Panel (Sensor Tower research, opt-in UX):** remote-config-driven parsers scrape other apps’ UI, optionally screenshot, optionally send screen text to AI endpoints, upload usage/ad/IAP/shopping/AI sessions to `api.stayfreeapps.com`. Consent is tracked via prefs (`data-consent-accept-time`, `usage-sdk-opt-out`, `opt_out_data_collection`, age gate). **MainActivity auto-writes `data-consent-accept-time` if missing** on first launch paths that skip some onboarding branches — treat consent UX carefully.

**Bottom line for the user:** Enabling StayFree’s Accessibility service grants Sensor Tower’s SDK the ability to observe (and, when panel features fire, upload) **on-screen text and screenshots from many third-party apps**, including social, shopping, rideshare, and some finance apps. It is **not** a pure local blocker. Password fields are not explicitly filtered in app logic; screenshots are the bigger password/screen-content risk.

---

## Network destinations

Primary first-party / Sensor Tower backends use host `api.stayfreeapps.com` (and related). Third-party analytics/attribution/crash/support SDKs are listed separately.

| Host / path pattern | Purpose | Data likely sent | Removable? |
|---|---|---|---|
| `api.stayfreeapps.com` — `analytics/*`, `web/upload`, `iap/*`, `page_views/upload`, `query_params/upload`, `ads/*`, `shopping/*`, `ai/analytics`, `analytics/ai_collection`, `brand/mentions`, `inapp/*` | **Sensor Tower panel uploads** | Device: installId, birthYear, gender/ethnicity/income (if set), country, carrier, device name/type, Android version, app list / per-app sessions, website URLs + UTM, ad creatives text/URLs, IAP events, shopping purchases, AI prompts/screen-derived entries, encrypted blobs | **Yes — strip for private build** |
| `api.stayfreeapps.com` — `sync/*` (pairing, devices, friend, config limits) | Cross-device sync of limits / friends | Device group configs, session summaries, pairing codes | Prefer remove (user wants local-only) |
| `api.stayfreeapps.com/v1/` + `adbl0ck.com` (`v1/ai/analyze_screen`, `v1/ai/query`, `v1/debug/accessibility_dump`, `v1/ads/*`) | Accessibility AI + ad scrape API | Screen text / dumps, device info (`udid`, birthYear, phoneModel…), hardcoded API-KEY header | **Yes** |
| `config.stayfreeapps.com` | Remote parser / feature flags (Featurevisor + JSON configs) | Downloads massive parser lists controlling *what* accessibility scrapes | Strip (stops live parser updates; local blocking still uses onboard logic) |
| `purchases.stayfreeapps.com` | Premium / StayFresh email-processing / OAuth | Auth tokens, email processing rules, breach lookups (`/staywise/v1/breach?email=`), Gmail readonly OAuth scope in Flutter binary | Strip cloud; local screen-time can work without |
| `app-measurement.com`, Firebase Analytics / Crashlytics / Perf / Installations / Remote Config / FCM | Google analytics + crash + push | App events, AD_ID, crashes, FCM tokens; topic `update_prefs_remotely` | Yes |
| `api2.amplitude.com` / `regionconfig.amplitude.com` | Amplitude product analytics | Events + device id | Yes |
| `sdk-api-v1.singular.net` | Singular MMP / attribution | Install referrer, AD_ID, custom user id = usage-sdk device id | Yes |
| `notify.bugsnag.com` / `sessions.bugsnag.com` (+ InsightHub) | Crash reporting | Stack traces, device metadata; API key in manifest | Yes |
| Facebook Graph (`graph.facebook.com` etc.), FB SDK | Facebook SDK (login/events) | App id `<redacted>`, client token in resources | Yes for tracking; social login may break |
| `beaconapi.helpscout.net` / `chatapi.helpscout.net` / Pusher | In-app support chat | Support messages, attachments | Optional (support UI) |
| `clients3.google.com/generate_204` | Connectivity check | Empty probe | Benign |
| Icon CDNs (`icons.bitwarden.net`, `c.1password.com`, …) | Favicons for blocked sites | Would leak visited hostnames | Prefer block |
| Play / Google account / Yahoo login URLs | StayFresh IMAP onboarding WebViews | **App passwords / email extracted via injected JS** (see Critical) | Disable scripts |

Example panel payload fields (from decompiled upload entities):  
`UploadData` (usage): `installId`, `birthYear`, `gender`, `ethnicity`, `income`, `deviceName`, `deviceType`, `phoneCarrier`, `countryCode`, `apps` (sessions)…  
`PromptData`: **full prompt `text`**.  
`ScreenDumpBody`: **`screenText`**.  
`AdEvent`: headline, text, URL, advertiser, location…

Hardcoded secrets found (treat as compromised / rotatable by vendor):

- Bugsnag API key: `<redacted>`
- Facebook app id / client token in `strings.xml`
- Singular SDK key/secret in `SingularInitializer`
- Adblock/AI API-KEY header: `<redacted>`
- Firebase `google_api_key` / `google_app_id` / project `<redacted>`
- AdMob APPLICATION_ID `<redacted>` (despite “ad-free” copy)
- Static AES key/IV in app crypto helper (`<redacted>` / `<redacted>`) — **weak hardcoded AES/CBC** for some “encrypted” upload paths

---

## Critical issues

1. **Sensor Tower research panel baked into a “self-control” app** — continuous / scheduled upload of app usage, websites, ads, purchases, and accessibility-derived screen content to StayFree/Sensor Tower APIs, gated by consent prefs that are easy to miss and remotely configurable via `config.stayfreeapps.com`.
2. **Accessibility + screenshots + AI screen analysis** — can observe third-party UI (incl. social, shopping, rideshare, some banking). Screenshots enabled in service config; remote config enables for many countries (incl. Spain `ES`).
3. **StayFresh / IMAP WebView scripts harvest Google/Yahoo app passwords** — `assets/flutter_assets/assets/scripts/google/login_injection.js` and Yahoo equivalents intercept XHR, extract generated app passwords, and send `{email, password}` to Flutter bridges (`AuthCredentialsBridge` / `PasswordBridge`). Also includes Yahoo anti-detection fingerprint spoofing. Extremely sensitive if that feature is used.
4. **Hardcoded API keys / AES key** in client (see above).
5. **Advertising / attribution stack** despite “Totally ad-free” marketing: Singular, AD_ID / Topics permissions, AdMob app id meta-data, Facebook SDK auto events possible.
6. **FCM topic `update_prefs_remotely`** — push channel that can alter prefs remotely.
7. **Cleartext traffic allowed** (`usesCleartextTraffic=true`).

## Medium issues

- `allowBackup=true` (ADB backup of app data).
- Notification listener reads notification keys/packages (local feature; also feeds analytics paths).
- Help Scout + Pusher support stack phones home when opened.
- No malware-style dynamic DEX loading found; no obvious `Runtime.exec` root exploits beyond Bugsnag root *detection*.
- Debuggable flag not set; most components correctly `exported=false`. Accessibility service is exported with `BIND_ACCESSIBILITY_SERVICE` (normal).
- Compose `PreviewActivity` exported (dev leftover; low risk).
- Split APKs required from Play; sideload needs merge (done for private build).

## Notes for patching / private APK

See [VARIANTS.md](VARIANTS.md). Strategy chosen for **maximum privacy**:

- Neutralize Sensor Tower upload job + force usage-sdk “opted out”.
- Same-length rewrite of first-party + tracker hosts to `*.invalid` in smali, resources, and Flutter `libapp.so`.
- Stub Amplitude / Singular initializers; strip FCM topic subscribe; remove upload / measurement / FCM components from manifest; kill-switch meta-data for Firebase/Facebook analytics.
- Remove `canTakeScreenshot` from accessibility XML (reduces screenshot capability; local URL blocking via view content still possible).
- Empty StayFresh WebView injection scripts (stops app-password harvesting).
- Drop AD_ID / Topics / install-referrer / C2DM permissions; disable cleartext + backup.
- Re-sign with your **own** keystore (Play signature will not match — uninstall the Play version first).

**Residual risk:** Heavily obfuscated code paths, WorkManager jobs, or future Flutter modules could still attempt network I/O to non-rewritten hosts (Google Play services libraries, icon CDNs partially addressed). Recommend firewall / NetGuard deny-all for this package if paranoid. Local blocking/limits that need only UsageStats + Accessibility for URL detection should still function offline; cloud sync, premium license checks, StayFresh email, Help Scout chat, and “panel” features will not.

---

## Tools used

Adoptium JDK 17 (portable), apktool 2.10.0, jadx 1.5.1, APKEditor 1.4.1, uber-apk-signer 1.3.0, unzip/strings/python3. Static only.

---

## Sign-in, sync and signature checks (follow-up for the re-signed builds)

Investigated because a re-signed APK has a different signing certificate than the Play build.

| Question | Finding (20.18.2, static) |
|---|---|
| How does **cross-device sync** authenticate? | Not with a Google account. `api.stayfreeapps.com/sync/*` (`sync/pairing/generate|check|validate`, `sync/devices`, `sync/config/*`, `sync/friend/*`) is keyed by the app's own `install_id` plus a **pairing code** shown on one device and typed on the other (`https://stayfreeapps.com/android-connect-device?pairingCode=`). No OAuth token, no signature-bound credential. |
| Where is **Google Sign-In** used? | Only inside the Flutter `email_apps_module` (StayFresh / StayWise / Mail Guardian e-mail cleaner): `google_sign_in` plugin, three Android OAuth client IDs in `libapp.so`, backend `purchases.stayfreeapps.com/api/v2/auth/*`, `/auth/callback/google`, Gmail scopes. There is **no Firebase Auth** and no Google account login for the screen-time / sync part of the app. |
| Does re-signing break that Google Sign-In? | Yes, it would. Android OAuth clients are bound to *package name + signing-cert SHA-1*; a different cert makes Google Play services return `DEVELOPER_ERROR (10)`. This cannot be fixed without StayFree's Google Cloud project. Both presets block this module anyway (it is the e-mail-reading / app-password-harvesting feature), so nothing that should keep working depends on it. |
| **Play Billing** (premium) | Play Billing library present (obfuscated). Purchases are handled by the Play Store app; Google Play may reject billing requests from an APK whose signature does not match the Play listing ("this version of the app is not configured for billing"). **Not verified** on a device. Existing premium may or may not be recognised. |
| Licence / signature checks | `CHECK_LICENSE` belongs to the **Singular** attribution SDK (install validation), not to a feature gate. No `PairIP`/Play Integrity, no app-side `PackageInfo.signatures` check found in `com.burockgames.*` / `com.sensortower.*`. So re-signing should not trigger an anti-tamper crash. |
| Firebase (sync preset) | Firebase Installations, Remote Config and FCM are left untouched in `sync`. They are keyed by API key + package name (API-key restrictions may include the cert SHA-1; if StayFree restricted the key, Remote Config/FCM would fail closed — app falls back to bundled defaults). |
