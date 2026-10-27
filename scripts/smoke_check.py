#!/usr/bin/env python3
"""Static smoke test of a built APK (no device needed).

Checks that blocked hosts / permissions / components are gone and that what a
preset promises to keep (sync endpoints, Firebase Installations, ...) is still
there. Exit 1 on any failure.  Usage: smoke_check.py APK --variant sync|max
"""
import argparse
import glob
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile

COMMON_ABSENT_DEX = ['sdk-api-v1.singular.net', 'api2.amplitude.com', 'notify.bugsnag.com',
                     'sessions.bugsnag.com', 'app-measurement.com', 'adbl0ck.com']
COMMON_ABSENT_MANIFEST = ['com.google.android.gms.permission.AD_ID',
                          'android.permission.ACCESS_ADSERVICES_AD_ID',
                          'android.permission.ACCESS_ADSERVICES_TOPICS']
CHECKS = {
    'sync': {
        'dex_absent': COMMON_ABSENT_DEX,
        'dex_present': [  # what sync / remote config / Google services need
            'sync/pairing/generate', 'sync/pairing/validate', 'sync/config', 'sync/devices',
            'sync/friend/add_friend', 'https://api.stayfreeapps.com/', 'https://config.stayfreeapps.com/',
            'firebaseinstallations.googleapis.com', 'firebaseremoteconfig.googleapis.com',
            'https://127.0.0.1/blocked/web/upload', 'https://127.0.0.1/blocked/analytics/encrypted',
            'https://127.0.0.1/blocked/v1/debug/accessibility_dump',
        ],
        'so_absent': ['purchases.stayfreeapps.com', 'https://api.stayfreeapps.com/staywise'],
        'manifest_absent': COMMON_ABSENT_MANIFEST,
        'manifest_present': ['com.google.firebase.messaging.FirebaseMessagingService',
                             'com.burockgames.timeclocker.accessibility.StayFreeAccessibilityService'],
    },
    'max': {
        'dex_absent': COMMON_ABSENT_DEX + ['stayfreeapps.com', 'amplitude.com', 'singular.net',
                                           'bugsnag.com', 'helpscout.net', 'stayfresh.email'],
        'dex_present': ['stayfree.invalid', 'com/burockgames/timeclocker'],
        'so_absent': ['stayfreeapps.com', 'stayfresh.email', 'sensortower.com'],
        'manifest_absent': COMMON_ABSENT_MANIFEST + [
            'com.sensortower.usage.sdk.upload.DataUploadJob',
            'com.google.android.c2dm.permission.RECEIVE',
            'com.google.android.gms.measurement.AppMeasurementService'],
        'manifest_present': ['com.burockgames.timeclocker.accessibility.StayFreeAccessibilityService'],
    },
}


def axml_strings(data: bytes):
    """String pool of a compiled Android XML (enough for presence checks)."""
    off = 8
    _, hsize, size = struct.unpack_from('<HHI', data, off)
    cnt, _, flags, sstart, _ = struct.unpack_from('<IIIII', data, off + 8)
    utf8 = flags & (1 << 8)
    offs = struct.unpack_from(f'<{cnt}I', data, off + hsize)
    base = off + sstart
    out = []
    for o in offs:
        p = base + o
        if utf8:
            n = data[p]; p += 2 if n & 0x80 else 1
            n = data[p]; ln = n
            if n & 0x80:
                ln = ((n & 0x7f) << 8) | data[p + 1]; p += 2
            else:
                p += 1
            out.append(data[p:p + ln].decode('utf-8', 'replace'))
        else:
            ln = struct.unpack_from('<H', data, p)[0]; p += 2
            if ln & 0x8000:
                ln = ((ln & 0x7fff) << 16) | struct.unpack_from('<H', data, p)[0]; p += 2
            out.append(data[p:p + ln * 2].decode('utf-16le', 'replace'))
    return out


def find_aapt2():
    p = shutil.which('aapt2')
    if p:
        return p
    for home in (os.environ.get('ANDROID_HOME'), os.environ.get('ANDROID_SDK_ROOT')):
        if home:
            c = sorted(glob.glob(os.path.join(home, 'build-tools', '*', 'aapt2')))
            if c:
                return c[-1]
    return None


def resource_ids(aapt2, apk):
    out = subprocess.run([aapt2, 'dump', 'resources', apk], capture_output=True, text=True).stdout
    return dict((m.group(2), m.group(1)) for m in
                re.finditer(r'^\s+resource (0x[0-9a-f]{8}) ([\w.$/-]+)', out, re.M))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('apk'); ap.add_argument('--variant', required=True, choices=CHECKS)
    ap.add_argument('--report')
    ap.add_argument('--reference', help='unpatched merged APK: resource IDs must be unchanged (needs aapt2)')
    a = ap.parse_args()
    c = CHECKS[a.variant]
    z = zipfile.ZipFile(a.apk)
    dex = b''.join(z.read(n) for n in z.namelist() if re.fullmatch(r'classes\d*\.dex', n))
    sos = b''.join(z.read(n) for n in z.namelist() if n.startswith('lib/') and n.endswith('libapp.so'))
    man = set(axml_strings(z.read('AndroidManifest.xml')))
    man_blob = '\n'.join(man)
    a11y = [n for n in z.namelist() if n.startswith('res/') and 'accessibility' in n and n.endswith('.xml')]
    fails, passes = [], []

    def chk(ok, msg):
        (passes if ok else fails).append(msg)
    for s in c['dex_absent']:
        chk(s.encode() not in dex, f'dex has no "{s}"')
    for s in c['dex_present']:
        chk(s.encode() in dex, f'dex keeps "{s}"')
    if sos:
        for s in c['so_absent']:
            chk(s.encode() not in sos, f'libapp.so has no "{s}"')
    else:
        fails.append('libapp.so not found (wrong ABI merge?)')
    for s in c['manifest_absent']:
        chk(s not in man_blob, f'manifest has no {s}')
    for s in c['manifest_present']:
        chk(s in man_blob, f'manifest keeps {s}')
    chk('canTakeScreenshot' not in ''.join(  # attribute name lives in the string pool when set
        '\n'.join(axml_strings(z.read(n))) for n in a11y), 'accessibility config has no canTakeScreenshot')
    if a.reference:
        aapt2 = find_aapt2()
        if not aapt2:
            print('  [smoke warn] aapt2 not found (set ANDROID_HOME): resource-ID check skipped')
        else:
            ref, new = resource_ids(aapt2, a.reference), resource_ids(aapt2, a.apk)
            moved = [k for k, v in ref.items() if new.get(k) != v]
            chk(bool(ref) and not moved,
                f'resource IDs preserved ({len(ref)} checked' + (f', {len(moved)} moved e.g. {moved[:3]})' if moved else ')'))
    for p in passes:
        print(f'  [smoke ok ] {p}')
    for f in fails:
        print(f'  [smoke FAIL] {f}')
    print(f'== smoke {a.variant}: {len(passes)} passed, {len(fails)} failed')
    if a.report:
        json.dump({'variant': a.variant, 'passed': passes, 'failed': fails}, open(a.report, 'w'), indent=1)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
