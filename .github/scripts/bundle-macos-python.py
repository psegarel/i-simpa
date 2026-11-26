#!/usr/bin/env python3
"""Bundle the pinned python.org framework and relocate its native dependencies."""
import argparse
import importlib.util
import os
import re
import shutil
import subprocess
from pathlib import Path

spec = importlib.util.spec_from_file_location('macos_compat', Path(__file__).with_name('check-macos-compat.py'))
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)


def bundle(app, framework):
    app = app.resolve()
    frameworks = app / 'Contents' / 'Frameworks'
    destination = frameworks / 'Python.framework'
    # The caller supplies the verified installer payload, not a Homebrew tree.
    shutil.copytree(framework, destination, symlinks=True)
    # Tcl/Tk development configuration scripts are not runtime resources and
    # otherwise appear as unsigned nested code when signing their frameworks.
    for pattern in ('*Config.sh', '*.a', '*.o'):
        for config in destination.rglob(pattern):
            config.unlink()
    prefixes = ('/Library/Frameworks/Python.framework/',
                '/usr/local/opt/python@3.14/Frameworks/Python.framework/')
    images = list(dict.fromkeys(compat.macho_files(app)))
    for path in images:
        # Ship only the architecture we validate, including framework extensions.
        if len(compat.run('lipo', '-archs', str(path)).split()) > 1:
            temporary = path.with_name(path.name + '.x86_64')
            subprocess.run(['lipo', str(path), '-thin', 'x86_64', '-output', str(temporary)], check=True)
            temporary.chmod(path.stat().st_mode)
            temporary.replace(path)
        # Keep the existing signature allocation while editing load commands.
        # Xcode 16 install_name_tool can reject the __LINKEDIT layout left by
        # codesign --remove-signature. Every edited image is re-signed below.
        loads = compat.run('otool', '-arch', 'x86_64', '-l', str(path))
        own_id = re.search(r'cmd LC_ID_DYLIB\s+cmdsize \d+\s+name (.+?) \(offset \d+\)', loads)
        changes = []
        if own_id and path.is_relative_to(destination):
            changes += ['-id', '@rpath/Python.framework/' + path.relative_to(destination).as_posix()]
        links = re.findall(r'^\s*(.*?) \(compatibility version ', compat.run('otool', '-arch', 'x86_64', '-L', str(path)), re.MULTILINE)
        for link in links:
            if own_id and link == own_id.group(1):
                continue
            for prefix in prefixes:
                if link.startswith(prefix):
                    target = destination / link[len(prefix):]
                    changes += ['-change', link, '@loader_path/' + os.path.relpath(target, path.parent)]
                    break
        if changes:
            subprocess.run(['install_name_tool', *changes, str(path)], check=True)
    # Sign nested images before the framework binaries that seal them.
    for path in sorted(images, key=lambda p: (-len(p.parts), p.name in ('Python', 'Tcl', 'Tk'))):
        subprocess.run(['codesign', '--force', '--sign', '-', str(path)], check=True)
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', type=Path)
    parser.add_argument('framework', type=Path)
    args = parser.parse_args()
    bundle(args.app, args.framework)
