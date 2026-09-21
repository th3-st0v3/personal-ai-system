#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 2_000_000
IGNORED_PARTS = {'.git', '.runtime', '.venv', 'node_modules', '__pycache__'}
PATTERNS = {
    'private_key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'aws_access_key': re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    'github_token': re.compile(r'\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b'),
    'openai_key': re.compile(r'\bsk-(?!ant-)[A-Za-z0-9_-]{20,}\b'),
    'anthropic_key': re.compile(r'\bsk-ant-[A-Za-z0-9_-]{20,}\b'),
    'google_ai_key': re.compile(r'\bAIza[0-9A-Za-z_-]{30,}\b'),
    'groq_key': re.compile(r'\bgsk_[A-Za-z0-9_-]{20,}\b'),
    'perplexity_key': re.compile(r'\bpplx-[A-Za-z0-9_-]{20,}\b'),
    'generic_secret_assignment': re.compile(r'''(?i)\b(?:api[_-]?key|secret|access[_-]?token|password)\s*[:=]\s*[\'\"](?!\s*(?:<|YOUR_|CHANGE_ME|EXAMPLE))[^\'\"]{20,}[\'\"]'''),
}

def tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'], check=True, capture_output=True, text=False, timeout=30)
    values = [Path(item.decode('utf-8', 'surrogateescape')) for item in result.stdout.split(b'\0') if item]
    return [root / value for value in values]

def scan_file(path: Path) -> list[tuple[str, int, str]]:
    try:
        if path.stat().st_size > MAX_FILE_BYTES: return []
        raw = path.read_bytes()
        if b'\0' in raw: return []
        text = raw.decode('utf-8', 'ignore')
    except OSError: return []
    findings = []
    for line_number, line in enumerate(text.splitlines(), 1):
        for name, pattern in PATTERNS.items():
            if pattern.search(line): findings.append((name, line_number, line[:240]))
    return findings

def scan(root: Path) -> list[dict[str, object]]:
    findings = []
    for path in tracked_files(root):
        if any(part in IGNORED_PARTS for part in path.relative_to(root).parts): continue
        for kind, line, excerpt in scan_file(path):
            findings.append({'type': kind, 'path': str(path.relative_to(root)), 'line': line, 'excerpt': excerpt})
    return findings

def main() -> int:
    parser = argparse.ArgumentParser(description='Scan tracked PASI files for high-confidence secret patterns.')
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    findings = scan(args.root.resolve())
    if findings:
        for item in findings: print(f"SECRET_SCAN_FINDING {item['type']} {item['path']}:{item['line']} {item['excerpt']}")
        return 1
    print('PASI secret scan: PASS')
    return 0

if __name__ == '__main__': raise SystemExit(main())
