#!/usr/bin/env python3
"""Reject private assets and obvious credentials in the public source tree."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BLOCKED = {'.zip', '.rar', '.ssf', '.so', '.deb', '.png', '.jpg', '.jpeg', '.gif', '.log', '.key', '.pem'}
PATTERNS = (
    rb'gh[pousr]_[A-Za-z0-9]{20,}',
    rb'github_pat_[A-Za-z0-9_]{20,}',
    rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----',
    rb'/home/[a-zA-Z0-9_.-]+/',
    rb'wxid_[a-zA-Z0-9_]+',
)


def main():
    git = subprocess.run(['git', 'ls-files', '-z'], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    paths = [ROOT / n.decode() for n in git.stdout.split(b'\0') if n] if git.returncode == 0 else [p for p in ROOT.rglob('*') if p.is_file() and not ({'.git', '__pycache__', 'build', 'dist', 'private'} & set(p.relative_to(ROOT).parts))]
    errors = []
    for path in paths:
        rel = path.relative_to(ROOT)
        if path.suffix.lower() in BLOCKED or {'private', 'build', 'dist'} & set(rel.parts):
            errors.append(str(rel) + ': private/generated file type')
        data = path.read_bytes()
        if any(re.search(p, data) for p in PATTERNS):
            errors.append(str(rel) + ': possible secret or personal machine identifier')
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print('Public source checks passed: {} files; no bundled raster artwork, vendor archives or obvious credentials.'.format(len(paths)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
