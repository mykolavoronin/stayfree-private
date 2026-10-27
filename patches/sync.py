#!/usr/bin/env python3
"""Apply the 'sync' preset: python3 patches/sync.py <decoded_dir> [--report r.json] [--strict]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stayfree_patch import main
if __name__ == '__main__':
    sys.exit(main(['apply', *sys.argv[1:2], '--preset', 'sync', *sys.argv[2:]]))
