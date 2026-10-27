"""The two privacy presets.

sync : "milder". Blocks the Sensor Tower research-panel uploads and third-party
       trackers but KEEPS StayFree device sync / pairing / friends, remote
       config, Firebase/FCM, Google sign-in and Play billing.
max  : "strict". Rewrites every StayFree / Sensor Tower / tracker / Firebase /
       support host to *.invalid, stubs the SDK initialisers, removes upload,
       measurement and push components. Cloud sync, friends, push, premium
       email and support chat stop working; local limits keep working.
"""
import re
from engine import (Patch, ok, LINES, same_len_invalid, block_retrofit_paths,
                    rewrite_hosts_smali_strings, rewrite_hosts_text, rewrite_hosts_native,
                    stub_bool_methods_using_string, stub_method, remove_permissions,
                    remove_components, add_meta, merged_apk_manifest_fixups,
                    a11y_no_screenshots, empty_webview_scripts, MANIFEST)

# ----------------------------------------------------------------- shared data
# Retrofit paths of the Sensor Tower panel (api.stayfreeapps.com, ad api, adbl0ck.com)
PANEL_UPLOAD_PATHS = [
    "ads/activity", "analytics/ai_collection", "ai/analytics", "analytics/activities",
    "analytics/background", "analytics/inapp/encrypted", "analytics/encrypted",
    "analytics/avg_usage", "analytics/avg_web_usage", "brand/mentions", "brands",
    "experimental/miscellaneous", "analytics/uninstalls", "page_views/upload",
    "/v1/shopping/purchases/android", "iap/accessibility_encrypted", "iap/encrypted",
    "iap/accessibility", "iap/upload", "subscriptions/status", "inapp/youtube_skip",
    "inapp/store_impressions", "query_params/upload", "/v2/shopping/events/android",
    "shopping/sessions/android", "web/upload", "characteristics/badges",
    "v1/ads/encrypted", "v2/ads/image", "v1/ads/upload", "v1/ads/fullscreen",
    "v1/ads/sponsor", "v1/ads/sdk",
    "v1/debug/accessibility_dump", "android-install", "v1/ai/analyze_screen", "v1/ai/query",
]
# Minimum share of panel endpoints that must be found, otherwise the API moved
PANEL_MIN_HIT = 0.6
DEAD_URL = "https://127.0.0.1/blocked/"

AD_PERMS = [
    "com.google.android.gms.permission.AD_ID",
    "android.permission.ACCESS_ADSERVICES_AD_ID",
    "android.permission.ACCESS_ADSERVICES_ATTRIBUTION",
    "android.permission.ACCESS_ADSERVICES_CUSTOM_AUDIENCE",
    "android.permission.ACCESS_ADSERVICES_TOPICS",
]

KILL_SWITCHES = {
    "firebase_analytics_collection_deactivated": "true",
    "google_analytics_adid_collection_enabled": "false",
    "google_analytics_ssaid_collection_enabled": "false",
    "google_analytics_default_allow_ad_personalization_signals": "false",
    "google_analytics_default_allow_ad_user_data": "false",
    "google_analytics_default_allow_analytics_storage": "false",
    "google_analytics_default_allow_ad_storage": "false",
    "firebase_crashlytics_collection_enabled": "false",
    "firebase_performance_collection_deactivated": "true",
    "firebase_sessions_enabled": "false",
    "com.facebook.sdk.AutoLogAppEventsEnabled": "false",
    "com.facebook.sdk.AdvertiserIDCollectionEnabled": "false",
    "com.facebook.sdk.AutoInitEnabled": "false",
    "com.facebook.sdk.MonitorEnabled": "false",
}
MAX_EXTRA_KILL = {
    "firebase_analytics_collection_enabled": "false",
    "firebase_performance_collection_enabled": "false",
    "firebase_messaging_auto_init_enabled": "false",
    "firebase_inapp_messaging_auto_data_collection_enabled": "false",
}

SYNC_TRACKER_HOSTS = [
    "sdk-api-v1.singular.net", "exceptions.singular.net", "api2.amplitude.com",
    "api.eu.amplitude.com", "regionconfig.amplitude.com", "regionconfig.eu.amplitude.com",
    "notify.bugsnag.com", "sessions.bugsnag.com", "notify.insighthub.smartbear.com",
    "sessions.insighthub.smartbear.com", "app-measurement.com",
    "firebase-settings.crashlytics.com", "adbl0ck.com",
]

# Order matters: longer / more specific first.
MAX_HOSTS = [
    'firebaseremoteconfigrealtime.googleapis.com', 'firebaseremoteconfig.googleapis.com',
    'firebaseinstallations.googleapis.com', 'firebasestorage.googleapis.com',
    'fcmregistrations.googleapis.com', 'firebaselogging-pa.googleapis.com',
    'firebaselogging.googleapis.com', 'crashlyticsreports-pa.googleapis.com',
    'firebase-settings.crashlytics.com', 'googlesyndication.com', 'googleadservices.com',
    'app-measurement.com', 'stayfreeapps.com', 'stayfresh.email', 'sensortower.com',
    'amplitude.com', 'singular.net', 'bugsnag.com', 'smartbear.com', 'helpscout.net',
    'pusherapp.com', 'pusher.com', 'adbl0ck.com', 'icons.bitwarden.net',
    'c.1password.com', 'gravatar.com',
]
# project-specific hosts are discovered at patch time (firebaseio / cloudfront)
DYNAMIC_HOST_PATTERNS = [
    r'[a-z0-9-]+\.firebaseio\.com', r'[a-z0-9-]+\.firebasestorage\.app',
]


# ----------------------------------------------------------------- patches
def p_panel_endpoints(tree, r):
    block_retrofit_paths(tree, r, PANEL_UPLOAD_PATHS, DEAD_URL,
                         scope_glob='smali*/com/sensortower/**/*.smali')
    hit = len(PANEL_UPLOAD_PATHS) - len(r.missing)
    if hit < PANEL_MIN_HIT * len(PANEL_UPLOAD_PATHS):
        r.details.append(f'only {hit} endpoints found (< {int(PANEL_MIN_HIT*100)}%): API moved, update patch')
        r.status = 'NOT_FOUND'


def p_optout(tree, r):
    # The Sensor Tower usage-SDK prefs class is the one that opens the
    # "usage-sdk-preferences" store; its ()Z getters reading "usage-sdk-opt-out"
    # are "opted out" and "decision made". Force both to true.
    stub_bool_methods_using_string(tree, r, 'usage-sdk-opt-out', True,
                                   cls_marker='"usage-sdk-preferences"')


def p_upload_gate(tree, r):
    # DataUploadJob worker: `if (!ageGate(ctx)) { log("Upload aborted: user under 18"); return }`
    # Force the gate to false so every scheduled upload aborts.
    rx = re.compile(r'invoke-virtual \{(v\d+), [vp]\d+\}, L[\w/$]+;->\w+\(Landroid/content/Context;\)Z'
                    r'(' + LINES + r')move-result \1(?=' + LINES + r'if-nez \1, :cond_\w+' + LINES
                    + r'const-string [vp]\d+, "Upload aborted: user under 18")')
    for f in tree.grep('Upload aborted: user under 18'):
        s = tree.read(f)
        s2, n = rx.subn(lambda m: f'const/4 {m.group(1)}, 0x0{m.group(2)}nop', s)
        if n:
            tree.set(f, s2); ok(r, n, f'{f}: upload age-gate forced false')
        elif 'const/4' in s and 'Upload aborted: user under 18' in s and '0x0' in s and r.status == 'NOT_FOUND':
            pass


def p_tracker_hosts_loopback(tree, r):
    rewrite_hosts_smali_strings(tree, r, {h: '127.0.0.1' for h in SYNC_TRACKER_HOSTS})
    if r.count:
        r.status = 'APPLIED'  # some hosts legitimately absent in some versions


def p_ad_perms(tree, r):
    remove_permissions(tree, r, AD_PERMS)
    s = tree.read(MANIFEST)
    s2 = re.sub(r'\s*<property android:name="android\.adservices[^>]*/>', '', s)
    tree.set(MANIFEST, s2)


def p_kill_sync(tree, r):
    add_meta(tree, r, KILL_SWITCHES)


def p_kill_max(tree, r):
    add_meta(tree, r, {**KILL_SWITCHES, **MAX_EXTRA_KILL})


def p_a11y(tree, r):
    a11y_no_screenshots(tree, r)


def p_email_backend_native(tree, r):
    # StayFresh / StayWise (email reading, breach lookup) backend lives in Flutter's libapp.so
    # and the StayWise e-mail breach lookup that sends your address to api.stayfreeapps.com.
    # Exact same-length byte strings only, so the sync API host stays intact.
    rewrite_hosts_native(tree, r, {
        'purchases.stayfreeapps.com': 'purchases-blocked0.invalid',
        'https://api.stayfreeapps.com/staywise': 'https://api-blocked0.invalid/staywise',
    }, lib_glob='lib/*/libapp.so')


def p_webview_scripts(tree, r):
    empty_webview_scripts(tree, r)


def p_split_fixups(tree, r):
    merged_apk_manifest_fixups(tree, r)


def _max_map(tree):
    hosts = list(MAX_HOSTS)
    blob = '\n'.join(tree.read(f) for f in tree.glob('res/values*/strings.xml'))
    for f in tree.grep('firebaseio.com') + tree.grep('cloudfront.net'):
        blob += tree.read(f)
    for pat in DYNAMIC_HOST_PATTERNS:
        for h in sorted(set(re.findall(pat, blob))):
            if h not in hosts:
                hosts.insert(0, h)
    # StayFree's own CloudFront distributions (icons / config mirrors)
    for f in tree.grep('cloudfront.net', tree.glob('smali*/com/burockgames/**/*.smali')
                       + tree.glob('smali*/com/sensortower/**/*.smali')):
        for h in set(re.findall(r'[a-z0-9]{12,16}\.cloudfront\.net', tree.read(f))):
            if h not in hosts:
                hosts.insert(0, h)
    return {h: same_len_invalid(h) for h in hosts}


def p_max_hosts_text(tree, r):
    m = _max_map(tree)
    tree._maxmap = m
    rewrite_hosts_text(tree, r, m, ['@smali', 'res/values*/*.xml', 'res/xml/*.xml'])
    if 'stayfreeapps.com' in r.missing:
        r.status = 'NOT_FOUND'
        r.details.append('stayfreeapps.com not found in smali/res: backend moved')


def p_max_hosts_native(tree, r):
    m = getattr(tree, '_maxmap', None) or _max_map(tree)
    rewrite_hosts_native(tree, r, m)


def p_fb_domains(tree, r):
    rx = {d: re.compile(r'const-string (v\d+), "' + re.escape(d) + r'"(' + LINES
                        + r'sput-object \1, L[\w/$]+;->\w+:Ljava/lang/String;)')
          for d in ('facebook.com', 'instagram.com')}
    rep = {'facebook.com': 'face.invalid', 'instagram.com': 'insta.invalid'}
    for f in tree.grep('"instagram.com"', tree.grep('"facebook.com"')):
        s = tree.read(f)
        if not all(x.search(s) for x in rx.values()):
            continue
        for d, x in rx.items():
            s = x.sub(lambda m, d=d: f'const-string {m.group(1)}, "{rep[d]}"{m.group(2)}', s, count=1)
        tree.set(f, s); ok(r, 1, f'{f}: Facebook SDK graph domain constants -> .invalid')


RET_OBJ = ('    .locals 1\n    new-instance v0, Ljava/lang/Object;\n'
           '    invoke-direct {v0}, Ljava/lang/Object;-><init>()V\n    return-object v0')


def p_stub_initializers(tree, r):
    for n in ('SingularInitializer', 'AmplitudeInitializer'):
        stub_method(tree, r, f'smali*/com/burockgames/timeclocker/initializer/{n}.smali',
                    'b(Landroid/content/Context;)Ljava/lang/Object;', RET_OBJ, f'{n}.create -> no-op')
    s = tree.read(MANIFEST)
    for n in ('SingularInitializer', 'AmplitudeInitializer'):
        s = re.sub(r'\s*<meta-data android:name="[\w.]*initializer\.' + n + r'" android:value="androidx\.startup"/>', '', s)
    tree.set(MANIFEST, s)


def p_fcm_topics(tree, r):
    rx = re.compile(r'\n\s*invoke-virtual \{[^}]*\}, L[\w/$]+/FcmSubscriptionInitializer;->subscribeToTopics\([^)]*\)V')
    for f in tree.grep('FcmSubscriptionInitializer;->subscribeToTopics'):
        s = tree.read(f)
        s2, n = rx.subn('\n    # PRIVACY PATCH: removed FCM topic subscription', s)
        if n:
            tree.set(f, s2); ok(r, n, f'{f}: removed {n} subscribeToTopics call(s)')


MAX_PERMS = AD_PERMS + [
    'com.google.android.finsky.permission.BIND_GET_INSTALL_REFERRER_SERVICE',
    'com.google.android.c2dm.permission.RECEIVE', 'android.permission.GET_ACCOUNTS',
]
MAX_COMPONENTS = [
    ('receiver', 'com.google.firebase.iid.FirebaseInstanceIdReceiver'),
    ('service', 'com.sensortower.util.utilkit.background.service.UsageFirebaseMessagingService'),
    ('service', 'com.helpscout.beacon.internal.presentation.push.fcm.BeaconFirebaseMessagingService'),
    ('service', 'com.google.firebase.messaging.FirebaseMessagingService'),
    ('receiver', 'com.sensortower.usage.sdk.upload.scheduler.BootCompletedAndUpdateReceiver'),
    ('receiver', 'com.sensortower.usage.sdk.upload.DataUploadJob'),
    ('receiver', 'com.google.android.gms.measurement.AppMeasurementReceiver'),
    ('service', 'com.google.android.gms.measurement.AppMeasurementService'),
    ('service', 'com.google.android.gms.measurement.AppMeasurementJobService'),
]


def p_max_perms(tree, r):
    remove_permissions(tree, r, MAX_PERMS)
    s = tree.read(MANIFEST)
    tree.set(MANIFEST, re.sub(r'\s*<property android:name="android\.adservices[^>]*/>', '', s))


def p_max_components(tree, r):
    remove_components(tree, r, MAX_COMPONENTS)


def p_hardening(tree, r):
    s = tree.read(MANIFEST); o = s
    s = s.replace('android:usesCleartextTraffic="true"', 'android:usesCleartextTraffic="false"')
    s = s.replace('android:allowBackup="true"', 'android:allowBackup="false"')
    tree.set(MANIFEST, s)
    ok(r, 1, 'usesCleartextTraffic=false, allowBackup=false' + ('' if s != o else ' (already)'))


# ----------------------------------------------------------------- presets
SYNC = [
    Patch('panel-endpoints', 'Sensor Tower panel upload endpoints -> dead URL', p_panel_endpoints, critical=True),
    Patch('usage-sdk-optout', 'Sensor Tower usage SDK forced "opted out"', p_optout, critical=True),
    Patch('tracker-hosts', 'Singular/Amplitude/Bugsnag/Firebase Analytics/adbl0ck hosts -> 127.0.0.1', p_tracker_hosts_loopback),
    Patch('ad-id-perms', 'Remove AD_ID / AdServices permissions', p_ad_perms),
    Patch('sdk-kill-switches', 'Firebase/Facebook collection kill-switch meta-data', p_kill_sync),
    Patch('a11y-no-screenshot', 'Accessibility service cannot take screenshots', p_a11y, critical=True),
    Patch('email-backend', 'Flutter libapp.so: purchases.stayfreeapps.com (email reading) -> .invalid', p_email_backend_native),
    Patch('split-fixups', 'Manifest fix-ups for a merged (non-split) APK', p_split_fixups),
]

MAX = [
    Patch('host-rewrite', 'All StayFree/Sensor Tower/tracker/Firebase hosts -> *.invalid (smali/res)', p_max_hosts_text, critical=True),
    Patch('host-rewrite-native', 'Same-length host rewrite in native libs (Flutter libapp.so)', p_max_hosts_native),
    Patch('usage-sdk-optout', 'Sensor Tower usage SDK forced "opted out"', p_optout, critical=True),
    Patch('upload-gate', 'DataUploadJob age gate forced to abort', p_upload_gate, critical=True),
    Patch('panel-endpoints', 'Sensor Tower panel upload endpoints -> dead URL (belt and braces)', p_panel_endpoints),
    Patch('fb-domains', 'Facebook SDK graph domain constants -> .invalid', p_fb_domains),
    Patch('sdk-initializers', 'Singular / Amplitude initialisers stubbed', p_stub_initializers),
    Patch('fcm-topics', 'Remove FCM topic subscriptions (update_prefs_remotely)', p_fcm_topics),
    Patch('a11y-no-screenshot', 'Accessibility service cannot take screenshots', p_a11y, critical=True),
    Patch('webview-scripts', 'Empty StayFresh WebView credential-harvest scripts', p_webview_scripts, critical=True),
    Patch('permissions', 'Remove AD_ID/AdServices/install-referrer/C2DM/GET_ACCOUNTS', p_max_perms),
    Patch('components', 'Remove upload / measurement / FCM components', p_max_components),
    Patch('sdk-kill-switches', 'Firebase/Facebook collection kill-switch meta-data', p_kill_max),
    Patch('hardening', 'Cleartext + backup off', p_hardening),
    Patch('split-fixups', 'Manifest fix-ups for a merged (non-split) APK', p_split_fixups),
]

PRESETS = {'sync': SYNC, 'max': MAX}
