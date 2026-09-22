"""Launch the project venv through a local, microphone-declared macOS app bundle.

Copies the framework Python GUI launcher, never modifies the Python installation.
No microphone access is requested here. Run through run_gui.sh.
"""
import hashlib
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
USAGE = 'Gnosis uses the built-in microphone for investigator-controlled audio measurements and local recordings.'


def prepare_bundle(base_prefix, cache_root):
    source = Path(base_prefix) / 'Resources' / 'Python.app'
    info_path = source / 'Contents' / 'Info.plist'
    if not info_path.is_file():
        raise RuntimeError('A framework Python installation with Python.app is required for the macOS GUI launcher.')
    info = plistlib.loads(info_path.read_bytes())
    executable = info['CFBundleExecutable']
    binary = source / 'Contents' / 'MacOS' / executable
    info.update(CFBundleName='Gnosis', CFBundleIdentifier='local.gnosis.desktop',
                NSMicrophoneUsageDescription=USAGE,
                NSCameraUsageDescription='Gnosis uses the built-in camera for local investigator-controlled frame-change monitoring.')
    encoded = plistlib.dumps(info)
    digest = hashlib.sha256(encoded + binary.read_bytes() + str(source).encode()).hexdigest()[:16]
    cache_root = Path(cache_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    target = cache_root / digest
    launcher = target / 'Gnosis.app' / 'Contents' / 'MacOS' / executable
    if launcher.is_file():
        return launcher
    staging = Path(tempfile.mkdtemp(prefix='build-', dir=cache_root))
    try:
        bundle = staging / 'Gnosis.app'
        shutil.copytree(source, bundle, symlinks=True)
        (bundle / 'Contents' / 'Info.plist').write_bytes(encoded)
        subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(bundle)],
                       check=True, capture_output=True, text=True)
        staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return launcher


def main():
    entry = ROOT / 'webagent_gui.py'
    if sys.platform != 'darwin':
        os.execv(sys.executable, [sys.executable, str(entry), *sys.argv[1:]])
    try:
        launcher = prepare_bundle(sys.base_prefix, ROOT / '.gnosis-macos')
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'Gnosis macOS launcher unavailable: {exc}\n'
              'Starting the standard GUI; the Investigation Lab will report microphone permission limitations.', file=sys.stderr)
        os.execv(sys.executable, [sys.executable, str(entry), *sys.argv[1:]])
    # CPython uses this to retain the venv while the real Mach-O executable stays in our app bundle.
    env = dict(os.environ, __PYVENV_LAUNCHER__=sys.executable)
    os.execve(launcher, [str(launcher), str(entry), *sys.argv[1:]], env)


if __name__ == '__main__':
    main()
