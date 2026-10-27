"""Pattern-based patch engine for apktool-decoded StayFree trees.

Every patch *detects* its target by content (strings, method signatures,
Retrofit annotations, manifest names) instead of obfuscated class names, so it
survives R8 renames between releases. A patch that cannot find its target
records NOT_FOUND and prints a warning instead of crashing. Patches flagged
`critical` make `--strict` runs fail so a half-patched APK is never shipped.
"""
from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass, field, asdict

LINES = r'(?:\s*\.line \d+)*\s*'  # smali .line noise between instructions


class Tree:
    """Lazy, cached view of a decoded APK. Writes happen only in apply mode."""

    def __init__(self, root: str, write: bool):
        self.root = os.path.abspath(root)
        self.write = write
        self._cache: dict[str, str] = {}
        self._bcache: dict[str, bytes] = {}
        self._dirty: set[str] = set()
        self._bdirty: set[str] = set()
        self._smali = None

    def p(self, rel):
        return os.path.join(self.root, rel)

    def exists(self, rel):
        return os.path.exists(self.p(rel))

    def smali_files(self):
        if self._smali is None:
            self._smali = sorted(
                os.path.relpath(f, self.root)
                for f in glob.glob(self.p('smali*/**/*.smali'), recursive=True))
        return self._smali

    def glob(self, pattern):
        return sorted(os.path.relpath(f, self.root)
                      for f in glob.glob(self.p(pattern), recursive=True))

    def read(self, rel) -> str:
        if rel not in self._cache:
            with open(self.p(rel), encoding='utf-8', errors='surrogateescape') as fh:
                self._cache[rel] = fh.read()
        return self._cache[rel]

    def set(self, rel, text):
        if text != self.read(rel):
            self._cache[rel] = text
            self._dirty.add(rel)

    def read_bytes(self, rel) -> bytes:
        if rel not in self._bcache:
            with open(self.p(rel), 'rb') as fh:
                self._bcache[rel] = fh.read()
        return self._bcache[rel]

    def set_bytes(self, rel, data):
        if data != self.read_bytes(rel):
            self._bcache[rel] = data
            self._bdirty.add(rel)

    def grep(self, needle: str, files=None):
        """Smali files containing a literal string (cheap pre-filter)."""
        out = []
        for f in (files if files is not None else self.smali_files()):
            if needle in self.read(f):
                out.append(f)
        return out

    def flush(self):
        if not self.write:
            return 0
        for rel in self._dirty:
            with open(self.p(rel), 'w', encoding='utf-8', errors='surrogateescape') as fh:
                fh.write(self._cache[rel])
        for rel in self._bdirty:
            with open(self.p(rel), 'wb') as fh:
                fh.write(self._bcache[rel])
        return len(self._dirty) + len(self._bdirty)

    def version(self):
        try:
            y = open(self.p('apktool.yml'), encoding='utf-8').read()
            vn = re.search(r"versionName:\s*'?([^'\n]+)", y)
            vc = re.search(r"versionCode:\s*'?(\d+)", y)
            return (vn.group(1).strip() if vn else None, vc.group(1) if vc else None)
        except OSError:
            return (None, None)


@dataclass
class Result:
    id: str
    title: str
    critical: bool
    status: str = 'NOT_FOUND'   # APPLIED | FOUND (scan) | NOT_FOUND | PARTIAL
    count: int = 0
    details: list = field(default_factory=list)
    missing: list = field(default_factory=list)


class Patch:
    def __init__(self, pid, title, fn, critical=False):
        self.id, self.title, self.fn, self.critical = pid, title, fn, critical

    def run(self, tree: Tree) -> Result:
        r = Result(self.id, self.title, self.critical)
        try:
            self.fn(tree, r)
        except Exception as e:  # never crash the whole run on one target
            r.status = 'NOT_FOUND'
            r.details.append(f'error: {type(e).__name__}: {e}')
        if r.status in ('APPLIED', 'FOUND', 'PARTIAL') and not tree.write and r.status == 'APPLIED':
            r.status = 'FOUND'
        return r


def ok(r: Result, n: int, detail=None, partial=False):
    if detail:
        r.details.append(detail)
    r.count += n
    if n > 0:
        r.status = 'PARTIAL' if (partial or r.status == 'PARTIAL') else 'APPLIED'


# --------------------------------------------------------------------------
# Generic building blocks
# --------------------------------------------------------------------------

def same_len_invalid(host: str) -> str:
    """foo.example.com -> foo.examp.invalid (same byte length, so it is safe
    for binary patching of Flutter's libapp.so)."""
    n = len(host) - len('.invalid')
    if n < 1:
        raise ValueError(f'host too short for same-length rewrite: {host}')
    pre = re.sub(r'[.\-]$', 'x', host[:n])
    out = pre + '.invalid'
    assert len(out) == len(host)
    return out


def block_retrofit_paths(tree: Tree, r: Result, paths, dead_url, scope_glob=None):
    """Point Retrofit @GET/@POST/... annotation values at a dead URL."""
    files = tree.glob(scope_glob) if scope_glob else []
    if not files:
        files = tree.smali_files()
    files = [f for f in files if '.annotation runtime' in tree.read(f)]
    want = set(paths)
    hit = set()
    pat = re.compile(r'(\.annotation runtime L[\w/$]+;\s*\n\s*value = )"([^"]+)"')
    for f in files:
        s = tree.read(f)
        if not any(p in s for p in want):
            continue

        def rep(m):
            if m.group(2) in want:
                hit.add(m.group(2))
                return f'{m.group(1)}"{dead_url}{m.group(2).lstrip("/")}"'
            if m.group(2).startswith(dead_url):  # already patched
                hit.add(m.group(2)[len(dead_url):])
            return m.group(0)
        tree.set(f, pat.sub(rep, s))
    r.missing = sorted(want - hit)
    ok(r, len(hit), f'{len(hit)}/{len(want)} endpoints matched', partial=bool(r.missing))


def rewrite_hosts_smali_strings(tree: Tree, r: Result, host_map: dict):
    """Rewrite hosts inside const-string / static field initialisers only."""
    counts = {h: 0 for h in host_map}
    for f in tree.smali_files():
        s = tree.read(f)
        if not any(h in s for h in host_map):
            continue
        o = s
        for h, new in host_map.items():
            if h not in s:
                continue
            rx = re.compile(r'((?:const-string(?:/jumbo)? [vp]\d+, |\.field [^\n]*= )"[^"\n]*)' + re.escape(h))
            def rep(m, h=h, new=new):
                counts[h] += 1
                return m.group(1) + new
            prev = None
            while prev != s:  # several hosts in one literal
                prev = s
                s = rx.sub(rep, s)
        if s != o:
            tree.set(f, s)
    for h, c in counts.items():
        r.details.append(f'{h} -> {host_map[h]}: {c}')
    r.missing = [h for h, c in counts.items() if c == 0]
    ok(r, sum(counts.values()), partial=bool(r.missing))
    return counts


def rewrite_hosts_text(tree: Tree, r: Result, host_map: dict, globs):
    counts = {}
    files = []
    for g in globs:
        files += tree.glob(g) if not g.startswith('@smali') else tree.smali_files()
    for f in files:
        try:
            s = tree.read(f)
        except (UnicodeDecodeError, OSError):
            continue
        o = s
        for h, new in host_map.items():
            if h in s:
                counts[h] = counts.get(h, 0) + s.count(h)
                s = s.replace(h, new)
        if s != o:
            tree.set(f, s)
    for h in host_map:
        r.details.append(f'{h} -> {host_map[h]}: {counts.get(h, 0)}')
    r.missing = [h for h in host_map if not counts.get(h)]
    ok(r, sum(counts.values()), partial=False)
    return counts


def rewrite_hosts_native(tree: Tree, r: Result, host_map: dict, lib_glob='lib/*/*.so'):
    total = 0
    for so in tree.glob(lib_glob):
        b = tree.read_bytes(so)
        o = b
        for h, new in host_map.items():
            hb, nb = h.encode(), new.encode()
            assert len(hb) == len(nb)
            c = b.count(hb)
            if c:
                b = b.replace(hb, nb)
                total += c
                r.details.append(f'{os.path.basename(so)}: {h} x{c}')
        tree.set_bytes(so, b)
        _ = o
    ok(r, total)


def methods(text):
    """Yield (start, end, header, body) for every smali method."""
    for m in re.finditer(r'^\.method ([^\n]*)\n(.*?)^\.end method', text, re.S | re.M):
        yield m.start(), m.end(), m.group(1), m.group(2)


def stub_bool_methods_using_string(tree: Tree, r: Result, needle: str, value: bool,
                                   cls_marker: str | None = None):
    """Replace every `()Z` method whose body loads `needle` with `return value`."""
    files = tree.grep(f'"{needle}"')
    if cls_marker:
        files = [f for f in files if cls_marker in tree.read(f)]
    for f in files:
        s = tree.read(f)
        out, last, n = [], 0, 0
        for a, b, hdr, body in methods(s):
            if hdr.endswith('()Z') and 'static' not in hdr.split('(')[0] \
                    and f'"{needle}"' in body:
                if 'PRIVACY PATCH' in body:
                    n += 1
                    continue
                new = (f'.method {hdr}\n    .locals 1\n\n    # PRIVACY PATCH: forced '
                       f'{str(value).lower()} ({needle})\n    const/4 v0, 0x{int(value)}\n\n'
                       f'    return v0\n.end method')
                out.append(s[last:a]); out.append(new); last = b; n += 1
                r.details.append(f'{f}: {hdr.split()[-1]}')
        out.append(s[last:])
        if n:
            tree.set(f, ''.join(out))
            ok(r, n)


def stub_method(tree: Tree, r: Result, rel_glob: str, sig: str, body: str, label=None):
    for f in tree.glob(rel_glob):
        s = tree.read(f)
        pat = re.compile(r'(\.method [^\n]*' + re.escape(sig) + r'\n).*?(\.end method)', re.S)
        s2, n = pat.subn(lambda m: m.group(1) + body + '\n' + m.group(2), s, count=1)
        if n:
            tree.set(f, s2)
            ok(r, 1, label or f'{f}: {sig}')


# ---------------- manifest helpers ----------------
MANIFEST = 'AndroidManifest.xml'


def remove_permissions(tree, r, perms):
    s = tree.read(MANIFEST)
    for p in perms:
        s, n = re.subn(r'\s*<uses-permission(?:-sdk-23)?\b[^>]*android:name="' + re.escape(p) + r'"[^>]*/>', '', s)
        r.details.append(f'{p}: removed {n}')
        if n:
            r.count += n
        else:
            r.missing.append(p)
    tree.set(MANIFEST, s)
    if r.count:
        r.status = 'APPLIED'


def remove_components(tree, r, comps):
    s = tree.read(MANIFEST)
    for tag, name in comps:
        pat = re.compile(r'\s*<' + tag + r'\b[^>]*android:name="' + re.escape(name)
                         + r'"[^>]*?(?:/>|>.*?</' + tag + r'>)', re.S)
        s, n = pat.subn('', s, count=1)
        r.details.append(f'<{tag}> {name}: removed {n}')
        if n:
            r.count += n
        else:
            r.missing.append(name)
    tree.set(MANIFEST, s)
    if r.count:
        r.status = 'APPLIED'


def add_meta(tree, r, flags: dict):
    s = tree.read(MANIFEST)
    n = 0
    for k, v in flags.items():
        rx = re.compile(r'(<meta-data android:name="' + re.escape(k) + r'" android:value=")[^"]*(")')
        if rx.search(s):
            s = rx.sub(lambda m: m.group(1) + v + m.group(2), s); n += 1
        else:
            s = re.sub(r'(<application\b[^>]*>)',
                       lambda m: m.group(1) + f'\n        <meta-data android:name="{k}" android:value="{v}"/>',
                       s, count=1); n += 1
    tree.set(MANIFEST, s)
    ok(r, n, f'{n} meta-data kill switches set')


def merged_apk_manifest_fixups(tree, r):
    """Required because we ship one merged APK instead of Play splits."""
    s = tree.read(MANIFEST); o = s
    s = re.sub(r'\s*<meta-data android:name="com\.android\.vending\.splits(\.required)?"[^>]*/>', '', s)
    s = re.sub(r' android:requiredSplitTypes="[^"]*"', '', s)
    s = re.sub(r' android:splitTypes="[^"]*"', '', s)
    s = s.replace('android:extractNativeLibs="false"', 'android:extractNativeLibs="true"')
    tree.set(MANIFEST, s)
    ok(r, int(s != o) or 1, 'split metadata removed / extractNativeLibs=true')


def a11y_no_screenshots(tree, r):
    files = [f for f in tree.glob('res/xml/*.xml') if 'canRetrieveWindowContent' in tree.read(f)
             or 'canTakeScreenshot' in tree.read(f)]
    for f in files:
        s = tree.read(f)
        s2 = re.sub(r'\s*android:canTakeScreenshot="true"', '', s)
        if s2 != s:
            tree.set(f, s2); ok(r, 1, f'{f}: canTakeScreenshot removed')
        elif 'canTakeScreenshot' not in s and r.status == 'NOT_FOUND':
            r.details.append(f'{f}: no canTakeScreenshot flag (already safe)')
            r.status = 'APPLIED' if tree.write else 'FOUND'


def empty_webview_scripts(tree, r):
    for js in tree.glob('assets/flutter_assets/assets/scripts/**/*.js'):
        if tree.read(js) != '/* disabled by privacy patch */\n':
            tree.set(js, '/* disabled by privacy patch */\n')
        ok(r, 1, f'emptied {js}')


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

def run(tree: Tree, patches, preset: str, strict: bool):
    vn, vc = tree.version()
    mode = 'apply' if tree.write else 'scan'
    print(f'== StayFree privacy patch: preset={preset} mode={mode} version={vn} ({vc})')
    results = []
    for p in patches:
        res = p.run(tree)
        if not tree.write and res.status == 'APPLIED':
            res.status = 'FOUND'
        results.append(res)
        flag = 'CRITICAL ' if p.critical else ''
        icon = {'APPLIED': 'OK ', 'FOUND': 'OK ', 'PARTIAL': 'WARN', 'NOT_FOUND': 'MISS'}[res.status]
        print(f'[{icon}] {flag}{p.id}: {p.title} -> {res.status} (count={res.count})')
        for d in res.details[:60]:
            print(f'        {d}')
        if res.missing:
            print(f'        missing: {res.missing}')
    written = tree.flush()
    crit_missing = [r.id for r in results if r.critical and r.status == 'NOT_FOUND']
    warnings = [r.id for r in results if r.status in ('PARTIAL', 'NOT_FOUND')]
    report = {
        'preset': preset, 'mode': mode, 'versionName': vn, 'versionCode': vc,
        'files_written': written, 'critical_missing': crit_missing, 'warnings': warnings,
        'ok': not crit_missing, 'results': [asdict(r) for r in results],
    }
    print(f'== summary: {sum(r.status in ("APPLIED","FOUND") for r in results)}/{len(results)} ok, '
          f'{len(warnings)} warnings {warnings}, critical missing: {crit_missing or "none"}, '
          f'files written: {written}')
    if crit_missing and strict:
        print('!! CRITICAL privacy patches did not find their target. Refusing to ship.')
    return report


def dump_report(report, path):
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, 'w') as fh:
            json.dump(report, fh, indent=1)
