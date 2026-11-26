#!/usr/bin/env python3
"""Native regressions for the dependency checker; run on macOS with clang."""
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


class NativeDependencies(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / 'Fixture.app'
        self.bin = self.app / 'Contents' / 'MacOS'
        self.libs = self.app / 'Contents' / 'Frameworks'
        self.plugins = self.app / 'Contents' / 'Resources' / 'plugins'
        for path in (self.bin, self.libs, self.plugins):
            path.mkdir(parents=True, exist_ok=True)
        with (self.app / 'Contents' / 'Info.plist').open('wb') as stream:
            plistlib.dump({'CFBundleExecutable': 'app'}, stream)
        (self.root / 'b.c').write_text('int fixture_b(void) { return 7; }\n')
        (self.root / 'a.c').write_text('extern int fixture_b(void); int fixture_a(void) { return fixture_b(); }\n')
        (self.root / 'main.c').write_text('extern int fixture_a(void); int main(void) { return fixture_a() == 7 ? 0 : 1; }\n')

    def compile(self, *args, target='14.0'):
        subprocess.run(['clang', '-arch', 'x86_64', '-mmacosx-version-min=' + target, *map(str, args)], check=True, capture_output=True)

    def chain(self, rpath=False):
        b = self.libs / 'libB.dylib'
        a = self.plugins / 'libA.dylib'
        b_id = '@rpath/libB.dylib' if rpath else '@executable_path/../Frameworks/libB.dylib'
        a_id = '@rpath/libA.dylib' if rpath else '@executable_path/../Resources/plugins/libA.dylib'
        self.compile('-dynamiclib', self.root / 'b.c', '-Wl,-install_name,' + b_id, '-o', b)
        self.compile('-dynamiclib', self.root / 'a.c', b, '-Wl,-install_name,' + a_id, '-o', a)
        flags = ['-Wl,-rpath,@executable_path/../Frameworks', '-Wl,-rpath,@executable_path/../Resources/plugins'] if rpath else []
        exe = self.bin / 'app'
        self.compile(self.root / 'main.c', a, *flags, '-o', exe)
        subprocess.run([str(exe)], check=True)
        return b

    def check(self, expected, env=None, contained=False):
        args = [sys.executable, str(SCRIPTS / 'check-macos-compat.py')]
        if contained:
            args += ['--contained-in', str(self.app)]
        result = subprocess.run([*args, str(self.app)], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_nested_executable_path(self):
        self.chain()
        self.check(0, contained=True)

    def test_inherited_rpath(self):
        self.chain(rpath=True)
        self.check(0, contained=True)

    def test_missing_dependency(self):
        self.chain().unlink()
        self.assertIn('Missing dependency', self.check(1).stderr)

    def test_actual_dependency_target(self):
        b = self.chain()
        # Replace the runtime dependency after linking with a newer-OS build.
        self.compile('-dynamiclib', self.root / 'b.c', '-Wl,-install_name,@executable_path/../Frameworks/libB.dylib', '-o', b, target='15.0')
        compatible = self.root / 'compatible.dylib'
        self.compile('-dynamiclib', self.root / 'b.c', '-o', compatible)
        result = self.check(1, env=dict(os.environ, SONOMA_PYTHON_LIBRARY=str(compatible)))
        self.assertIn('minimum macOS 15.0', result.stderr)

    def test_external_dependency_rejected_for_standalone_bundle(self):
        self.chain()
        external = self.root / 'external.dylib'
        self.compile('-dynamiclib', self.root / 'b.c', '-Wl,-install_name,' + str(external), '-o', external)
        self.compile('-dynamiclib', self.root / 'a.c', external, '-Wl,-install_name,@executable_path/../Resources/plugins/libA.dylib', '-o', self.plugins / 'libA.dylib')
        self.assertIn('outside bundle', self.check(1, contained=True).stderr)


if __name__ == '__main__':
    unittest.main()
