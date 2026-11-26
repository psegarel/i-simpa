#!/usr/bin/env python3
"""Inspect actual x86_64 dependencies with dyld executable and loader context."""
import argparse
import os
import plistlib
import re
import subprocess
from pathlib import Path

MAGIC = {bytes.fromhex(x) for x in ('feedface', 'cefaedfe', 'feedfacf', 'cffaedfe', 'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca')}


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT)


def macho_files(root):
    root = Path(root)
    paths = [root] if root.is_file() else (Path(p) / n for p, _, files in os.walk(root) for n in files)
    for path in paths:
        # Installer frameworks can contain optional dangling header symlinks.
        # Any missing library actually loaded is still rejected by visit().
        if path.is_symlink() and not path.exists():
            continue
        with path.open('rb') as stream:
            if stream.read(4) in MAGIC:
                # Relocatable build objects are not images loaded by dyld.
                if not re.search(r'\bOBJECT\b', run('otool', '-arch', 'x86_64', '-hv', str(path))):
                    yield path.resolve()


def expand(value, loader, executable):
    value = value.replace('@loader_path', str(loader.parent))
    if executable is not None:
        value = value.replace('@executable_path', str(executable.parent))
    return value


class Inspector:
    def __init__(self, target=(14, 0), contained_in=None):
        self.target = target
        self.contained_in = Path(contained_in).resolve() if contained_in else None
        self.images = {}
        self.visited = set()
        self.checked = set()
        self.errors = []

    def image(self, path):
        if path not in self.images:
            run('lipo', str(path), '-verify_arch', 'x86_64')
            loads = run('otool', '-arch', 'x86_64', '-l', str(path))
            version = re.search(r'cmd LC_BUILD_VERSION\s+cmdsize \d+\s+platform (?:1|MACOS)\s+minos ([\d.]+)', loads)
            if not version:
                version = re.search(r'cmd LC_VERSION_MIN_MACOSX\s+cmdsize \d+\s+version ([\d.]+)', loads)
            if not version:
                raise ValueError('no macOS deployment target found')
            minimum = version.group(1)
            parts = tuple(map(int, minimum.split('.')))
            width = max(len(parts), len(self.target))
            if parts + (0,) * (width - len(parts)) > self.target + (0,) * (width - len(self.target)):
                raise ValueError(f'minimum macOS {minimum} exceeds {self.target}')
            own_id = re.search(r'cmd LC_ID_DYLIB\s+cmdsize \d+\s+name (.+?) \(offset \d+\)', loads)
            links = re.findall(r'^\s*(.*?) \(compatibility version ', run('otool', '-arch', 'x86_64', '-L', str(path)), re.MULTILINE)
            self.images[path] = (
                re.findall(r'cmd LC_RPATH\s+cmdsize \d+\s+path (.+?) \(offset \d+\)', loads),
                [link for link in links if not own_id or link != own_id.group(1)],
                bool(re.search(r'\bEXECUTE\b', run('otool', '-arch', 'x86_64', '-hv', str(path)))),
            )
            print(f'{path}: x86_64, macOS {minimum}', flush=True)
        return self.images[path]

    def visit(self, path, executable, inherited=()):
        path = Path(path).resolve()
        if not path.exists():
            self.errors.append(f'Missing dependency: {path}')
            return
        if self.contained_in and not path.is_relative_to(self.contained_in):
            self.errors.append(f'Non-system dependency outside bundle: {path}')
            return
        try:
            own_paths, dependencies, _ = self.image(path)
            # Resolve LC_RPATH relative to its declaring loader, then retain it
            # for children. The nearest loader takes precedence over ancestors.
            paths = tuple(dict.fromkeys([expand(r, path, executable) for r in own_paths] + list(inherited)))
            key = (path, executable, paths)
            if key in self.visited:
                return
            self.visited.add(key)
            self.checked.add(path)
            for dep in dependencies:
                if dep.startswith(('/usr/lib/', '/System/Library/')):
                    continue
                if dep.startswith('@rpath/'):
                    candidates = [Path(r) / dep[len('@rpath/'):] for r in paths if not r.startswith('@')]
                    found = next((p for p in candidates if p.exists()), None)
                    if found is None:
                        raise ValueError(f'unresolved {dep}; rpaths={paths}')
                    self.visit(found, executable, paths)
                else:
                    resolved = expand(dep, path, executable)
                    if not resolved.startswith('/'):
                        raise ValueError(f'unresolved dependency {dep}')
                    self.visit(resolved, executable, paths)
        except (subprocess.CalledProcessError, OSError, ValueError) as exc:
            self.errors.append(f'{path}: {exc}')

    def inspect(self, root):
        root = Path(root).resolve()
        files = list(dict.fromkeys(macho_files(root)))
        if not files:
            self.errors.append(f'No Mach-O files found: {root}')
            return
        main = None
        plist = root / 'Contents' / 'Info.plist'
        if plist.is_file():
            with plist.open('rb') as stream:
                name = plistlib.load(stream)['CFBundleExecutable']
            main = (root / 'Contents' / 'MacOS' / name).resolve()
            self.visit(main, main)
        # Each helper executable starts its own dyld context.
        for path in files:
            try:
                if self.image(path)[2]:
                    self.visit(path, path)
                    if main is None:
                        main = path
            except (subprocess.CalledProcessError, OSError, ValueError) as exc:
                self.errors.append(f'{path}: {exc}')
        # Also inspect extensions loaded dynamically instead of through LC_LOAD.
        inherited = ()
        if main in self.images:
            inherited = tuple(expand(r, main, main) for r in self.images[main][0])
        for path in files:
            if path not in self.checked:
                self.visit(path, main, inherited)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contained-in', type=Path, help='Reject external non-system dependencies')
    parser.add_argument('roots', nargs='+', type=Path)
    args = parser.parse_args()
    inspector = Inspector(contained_in=args.contained_in)
    for root in args.roots:
        inspector.inspect(root)
    print(f'Inspected {len(inspector.checked)} Mach-O files', flush=True)
    if inspector.errors:
        parser.exit(1, '\n'.join(inspector.errors) + '\n')


if __name__ == '__main__':
    main()
