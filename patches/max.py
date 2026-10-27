#!/usr/bin/env python3
"""Apply the 'max' preset: python3 patches/max.py <decoded_dir> [--report r.json] [--strict]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stayfree_patch import main
if __name__ == '__main__':
    sys.exit(main(['apply', *sys.argv[1:2], '--preset', 'max', *sys.argv[2:]]))
