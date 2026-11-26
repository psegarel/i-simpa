# Intel macOS runtime validation

The Intel workflow targets macOS 14.0 and packages the pinned python.org
Python 3.14.7 framework inside `isimpa.app/Contents/Frameworks`. The installer
SHA-256 is checked before extraction. Homebrew Python is a build tool only;
users of the resulting Intel app do not need a separate Python installation.
The Apple Silicon build is unchanged.

`bundle-macos-python.py` preserves the framework's standard library, extension
modules, Tcl/Tk runtime, and license files; removes Tcl/Tk build configuration
scripts and static build objects/archives; keeps only x86_64 code; rewrites Python framework dependencies relative
to each loader; and ad-hoc signs nested code before the application. The app
remains unnotarized.

`check-macos-compat.py` follows actual load commands without substituting any
build-time library. Each executable has its own `@executable_path` context.
Loader-relative run paths are expanded where declared and inherited by child
images. Dynamically loaded extensions are also scanned. With
`--contained-in APP`, all non-system dependencies must resolve inside APP.
All inspected images must provide x86_64 code targeting macOS 14.0 or earlier.
Relocatable build objects and optional dangling header symlinks are not runtime
images; missing dependencies referenced by runtime images still fail validation.

Run on macOS with the command-line developer tools installed:

```sh
python3 .github/scripts/test-macos-compat.py
python3 .github/scripts/check-macos-compat.py --contained-in /path/isimpa.app /path/isimpa.app
python3 .github/scripts/check-bundled-python.py /path/isimpa.app
```

The five native regressions cover nested `@executable_path`, inherited `@rpath`,
missing libraries, a runtime dependency with a newer deployment target, and
external dependencies in a standalone package. The embedded runtime smoke test
uses the same `PyConfig` initialization as I-Simpa, removes Python/DYLD environment overrides,
and imports SSL, SQLite, ctypes, Tkinter, and zstd while checking `sys.prefix`.
macOS initialization disables bytecode writes so imports cannot invalidate the
signed framework by creating cache files inside it.
The workflow checks both the build tree and the mounted DMG before upload.

These checks do not replace running I-Simpa and acoustic simulations on a real
Intel Mac running Sonoma. In particular, code signing and native deployment
metadata alone do not establish end-to-end application compatibility.
