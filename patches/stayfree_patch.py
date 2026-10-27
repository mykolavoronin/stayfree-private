#!/usr/bin/env python3
"""StayFree privacy patcher CLI.

  stayfree_patch.py scan  <decoded_dir> [--preset sync|max|all] [--report r.json] [--strict]
  stayfree_patch.py apply <decoded_dir> --preset sync|max [--report r.json] [--strict]
                    [--disable id,id] [--enable id,id]
  stayfree_patch.py list                 # show every patch id per preset

Feature toggles: --disable drops patches from the preset (e.g. keep Facebook
login: --disable fb-domains); --enable adds patches from the other preset
(e.g. sync + no e-mail scripts: --preset sync --enable webview-scripts).
Same via env: STAYFREE_DISABLE / STAYFREE_ENABLE (comma separated).

`scan` is detect-only (nothing is written). With --strict the exit code is 2
if any CRITICAL patch cannot find its target in this StayFree version.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import Tree, run, dump_report  # noqa: E402
from presets import PRESETS  # noqa: E402


def select(preset, disable, enable):
    all_ids = {q.id: q for plist in PRESETS.values() for q in plist}
    dis = {x.strip() for x in disable.split(',') if x.strip()}
    en = [x.strip() for x in enable.split(',') if x.strip()]
    for x in dis | set(en):
        if x not in all_ids:
            raise SystemExit(f'unknown patch id {x!r}; see: stayfree_patch.py list')
    plist = [q for q in PRESETS[preset] if q.id not in dis]
    have = {q.id for q in plist}
    plist += [all_ids[x] for x in en if x not in have]
    if dis:
        print(f'[toggle] {preset}: disabled {sorted(dis)}')
    if en:
        print(f'[toggle] {preset}: enabled {en}')
    return plist


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode', choices=['scan', 'apply', 'list'])
    ap.add_argument('tree', nargs='?', help='apktool-decoded directory')
    ap.add_argument('--preset', default=None, choices=['sync', 'max', 'all'])
    ap.add_argument('--report', help='write JSON report here')
    ap.add_argument('--strict', action='store_true', help='exit 2 if a critical patch is NOT_FOUND')
    ap.add_argument('--disable', default=os.environ.get('STAYFREE_DISABLE', ''), help='comma-separated patch ids to skip')
    ap.add_argument('--enable', default=os.environ.get('STAYFREE_ENABLE', ''), help='comma-separated patch ids to add')
    a = ap.parse_args(argv)
    if a.mode == 'list':
        for name, plist in PRESETS.items():
            print(f'[{name}]')
            for p in plist:
                print(f'  {p.id:22} {"CRITICAL " if p.critical else "         "}{p.title}')
        return 0
    if not a.tree:
        ap.error('tree is required')
    if not os.path.exists(os.path.join(a.tree, 'AndroidManifest.xml')):
        ap.error(f'{a.tree} is not an apktool-decoded tree')
    if a.mode == 'apply' and a.preset in (None, 'all'):
        ap.error('apply needs --preset sync or --preset max')
    presets = ['sync', 'max'] if a.preset in (None, 'all') else [a.preset]
    reports = {}
    failed = False
    for p in presets:
        tree = Tree(a.tree, write=(a.mode == 'apply'))
        rep = run(tree, select(p, a.disable, a.enable), p, a.strict)
        reports[p] = rep
        failed |= not rep['ok']
    out = reports[presets[0]] if len(presets) == 1 else {'mode': a.mode, 'presets': reports,
                                                          'ok': not failed}
    dump_report(out, a.report)
    return 2 if (failed and a.strict) else 0


if __name__ == '__main__':
    sys.exit(main())
