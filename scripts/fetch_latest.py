#!/usr/bin/env python3
"""Resolve / download the latest StayFree (com.burockgames.timeclocker) and verify it.

  fetch_latest.py --check                 # print latest version as JSON, no download
  fetch_latest.py --out work/src          # download + extract + verify signer
  fetch_latest.py --input file.xapk --out work/src   # use a local XAPK/APKS/APK

Sources: APKPure (primary), APKMirror (best-effort fallback; often behind
Cloudflare). The original signer certificate SHA-256 MUST equal the pinned
Play App Signing cert, otherwise we abort: never patch a tampered upload.
"""
import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile

PKG = 'com.burockgames.timeclocker'
PINNED_CERT_SHA256 = '5b4aa54dc2514c272e0a005e4c69d87fbc67ff74746763aad709e7814c617593'
APKPURE_URL = f'https://d.apkpure.net/b/XAPK/{PKG}?version=latest'
APKPURE_APK_URL = f'https://d.apkpure.net/b/APK/{PKG}?version=latest'
APKMIRROR_SEARCH = f'https://www.apkmirror.com/?post_type=app_release&searchtype=apk&s={PKG}'
UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/124.0 Safari/537.36')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.environ.get('TOOLS_DIR', os.path.join(ROOT, 'tools'))


def log(*a):
    print('[fetch]', *a, file=sys.stderr)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def head_location(url):
    op = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': UA})
    try:
        op.open(req, timeout=30)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            return e.headers.get('Location')
        raise
    return None


def version_from_filename(loc):
    q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
    name = (q.get('filename') or [''])[0] or urllib.parse.unquote(loc)
    m = re.search(r'_(\d+(?:\.\d+)+)_APKPure', name)
    return (m.group(1) if m else None), name


def resolve_apkpure():
    loc = head_location(APKPURE_URL)
    if not loc:
        raise RuntimeError('APKPure did not redirect to a file')
    ver, name = version_from_filename(loc)
    if not ver:
        raise RuntimeError(f'could not parse version from {name!r}')
    return {'source': 'apkpure', 'version': ver, 'url': loc, 'filename': name}


def http_get(url, dest=None, referer=None):
    req = urllib.request.Request(url, headers={'User-Agent': UA, **({'Referer': referer} if referer else {})})
    with urllib.request.urlopen(req, timeout=120) as r:
        if dest is None:
            return r.read().decode('utf-8', 'replace')
        with open(dest + '.part', 'wb') as fh:
            shutil.copyfileobj(r, fh, 1 << 20)
    os.replace(dest + '.part', dest)
    return dest


def resolve_apkmirror():
    """Best effort: newest release -> first variant -> download page -> file."""
    base = 'https://www.apkmirror.com'
    page = http_get(APKMIRROR_SEARCH)
    rels = re.findall(r'href="(/apk/[^"]+/[^"]+-(\d+(?:-\d+)+)-release/)"', page)
    if not rels:
        raise RuntimeError('APKMirror: no releases found')

    def key(v):
        return tuple(int(x) for x in v.split('-'))
    rel, ver = max(rels, key=lambda x: key(x[1]))
    rp = http_get(base + rel)
    var = re.search(r'href="(' + re.escape(rel) + r'[^"#]+-download/)"', rp)
    if not var:
        raise RuntimeError('APKMirror: no variant link')
    vp = http_get(base + var.group(1))
    dl = re.search(r'href="(' + re.escape(var.group(1)) + r'download/[^"]*)"', vp) or \
        re.search(r'href="([^"]+/download/\?key=[^"]+)"', vp)
    if not dl:
        raise RuntimeError('APKMirror: no download button (Cloudflare?)')
    dp = http_get(base + html.unescape(dl.group(1)))
    f = re.search(r'href="(/wp-content/themes/APKMirror/download\.php\?[^"]+)"', dp)
    if not f:
        raise RuntimeError('APKMirror: no final download link')
    return {'source': 'apkmirror', 'version': ver.replace('-', '.'),
            'url': base + html.unescape(f.group(1)), 'filename': f'{PKG}_{ver}.apkm',
            'referer': base + dl.group(1)}


def resolve():
    errs = []
    for fn in (resolve_apkpure, resolve_apkmirror):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            errs.append(f'{fn.__name__}: {e}')
            log('warning:', errs[-1])
    raise SystemExit('could not resolve latest StayFree version:\n  ' + '\n  '.join(errs))


def apksigner_certs(apk):
    jar = os.path.join(TOOLS, 'apksigner.jar')
    out = subprocess.run(['java', '-jar', jar, 'verify', '--print-certs', apk],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f'apksigner verify failed for {apk}:\n{out.stderr or out.stdout}')
    return re.findall(r'Signer #\d+ certificate SHA-256 digest: ([0-9a-f]{64})', out.stdout)


def extract(pkg_file, out_dir):
    """XAPK / APKM / APKS are zips of APKs; a plain APK is used as-is."""
    splits = os.path.join(out_dir, 'splits')
    shutil.rmtree(splits, ignore_errors=True)
    os.makedirs(splits)
    with zipfile.ZipFile(pkg_file) as z:
        names = z.namelist()
        if 'AndroidManifest.xml' in names:  # plain APK
            shutil.copy(pkg_file, os.path.join(splits, 'base.apk'))
            return splits, {}
        meta = {}
        if 'manifest.json' in names:
            meta = json.loads(z.read('manifest.json'))
        for n in names:
            if n.endswith('.apk') and '/' not in n:
                z.extract(n, splits)
    if not os.listdir(splits):
        raise SystemExit('archive contained no APKs')
    return splits, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='only print the latest version (no download)')
    ap.add_argument('--input', help='local XAPK/APKM/APKS/APK instead of downloading')
    ap.add_argument('--out', default=os.path.join(ROOT, 'work', 'src'))
    a = ap.parse_args()

    if a.check:
        info = resolve()
        info.pop('url', None); info.pop('referer', None)
        print(json.dumps(info))
        return
    os.makedirs(a.out, exist_ok=True)
    if a.input:
        info = {'source': 'local', 'filename': os.path.basename(a.input), 'version': None}
        pkg_file = a.input
    else:
        info = resolve()
        pkg_file = os.path.join(a.out, re.sub(r'[^\w.+-]', '_', info['filename']))
        if not os.path.exists(pkg_file):
            log('downloading', info['source'], info['version'])
            http_get(info['url'], pkg_file, info.get('referer'))
    splits, meta = extract(pkg_file, a.out)

    files = {}
    for f in sorted(os.listdir(splits)):
        p = os.path.join(splits, f)
        certs = apksigner_certs(p)
        if certs != [PINNED_CERT_SHA256]:
            raise SystemExit(f'SIGNER MISMATCH in {f}: {certs} != {PINNED_CERT_SHA256}. Aborting.')
        files[f] = sha256(p)
    if meta.get('package_name') and meta['package_name'] != PKG:
        raise SystemExit(f'unexpected package {meta["package_name"]}')
    info.update({
        'package': PKG,
        'version': meta.get('version_name') or info.get('version'),
        'version_code': meta.get('version_code'),
        'archive_sha256': sha256(pkg_file),
        'splits_sha256': files,
        'signer_cert_sha256': PINNED_CERT_SHA256,
        'signer_verified': True,
    })
    info.pop('url', None); info.pop('referer', None)
    with open(os.path.join(a.out, 'source.json'), 'w') as fh:
        json.dump(info, fh, indent=1)
    log(f'OK {info["version"]} ({len(files)} APKs, signer verified)')
    print(json.dumps(info))


if __name__ == '__main__':
    main()
