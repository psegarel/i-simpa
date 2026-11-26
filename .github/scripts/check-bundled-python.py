#!/usr/bin/env python3
"""Exercise embedded Python without PYTHONHOME, PYTHONPATH or DYLD overrides."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

app = Path(sys.argv[1]).resolve()
framework = app / 'Contents/Frameworks/Python.framework/Versions/3.14'
env = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'DYLD_'))}
# Use the same PyConfig initialization as I-Simpa, rather than relying only
# on the framework's command-line interpreter startup behaviour.
code = ('import sys, ssl, sqlite3, ctypes, _tkinter, compression.zstd; '
        f'assert sys.prefix == {str(framework)!r}, sys.prefix; '
        'assert sys.dont_write_bytecode; '
        'print("Bundled embedded Python:", sys.version, sys.prefix)')
import json
with tempfile.TemporaryDirectory() as temp:
    source = Path(temp) / 'embed.c'
    executable = Path(temp) / 'embed'
    source.write_text('#include <Python.h>\nint main(void) { PyConfig config; '
                      'PyConfig_InitPythonConfig(&config); config.write_bytecode = 0; '
                      'PyStatus status = Py_InitializeFromConfig(&config); '
                      'PyConfig_Clear(&config); if (PyStatus_Exception(status)) return 1; '
                      'int result = PyRun_SimpleString(' + json.dumps(code) + '); '
                      'Py_Finalize(); return result; }\n')
    subprocess.run(['clang', '-arch', 'x86_64', '-mmacosx-version-min=14.0', '-Wl,-headerpad_max_install_names',
                    '-I', str(framework / 'include/python3.14'), str(source),
                    str(framework / 'Python'), '-o', str(executable)], check=True)
    # The framework's install ID is relocatable. Point this temporary test
    # executable at the bundled framework; the application is already relocated.
    subprocess.run(['install_name_tool', '-change', '@rpath/Python.framework/Versions/3.14/Python',
                    str(framework / 'Python'), str(executable)], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', str(executable)], check=True)
    subprocess.run([str(executable)], check=True, env=env, cwd=temp)
