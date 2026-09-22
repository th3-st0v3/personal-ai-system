from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

SEMVER = re.compile(r'^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$')

@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int
    def __str__(self) -> str:
        return f'{self.major}.{self.minor}.{self.patch}'

def parse_version(value: str) -> Version:
    match = SEMVER.fullmatch(value.strip().lstrip('v'))
    if not match:
        raise ValueError(f'invalid semantic version: {value}')
    return Version(int(match['major']), int(match['minor']), int(match['patch']))

def bump(version: Version, subjects: list[str]) -> Version:
    if any(re.match(r'^[a-z]+(?:\([^)]*\))?!:', item.strip()) for item in subjects):
        return Version(version.major + 1, 0, 0)
    if any(item.strip().startswith('feat') for item in subjects):
        return Version(version.major, version.minor + 1, 0)
    return Version(version.major, version.minor, version.patch + 1)

def changelog_entry(version: Version, subjects: list[str]) -> str:
    lines = [f'## {version}', '', *[f'- {item.strip()}' for item in subjects if item.strip()], '']
    return '\n'.join(lines)

def main() -> int:
    parser = argparse.ArgumentParser(description='Compute the next PASI SemVer from Conventional Commit subjects.')
    parser.add_argument('version')
    parser.add_argument('subjects', nargs='*')
    parser.add_argument('--changelog')
    args = parser.parse_args()
    current = parse_version(args.version)
    next_version = bump(current, args.subjects)
    print(next_version)
    if args.changelog:
        path = Path(args.changelog)
        existing = path.read_text(encoding='utf-8') if path.exists() else '# Changelog\n\n'
        marker = changelog_entry(next_version, args.subjects)
        prefix = existing.rstrip() + '\n\n' + marker.strip() + '\n'
        path.write_text(prefix, encoding='utf-8')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())