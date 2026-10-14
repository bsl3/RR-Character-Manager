"""Build, check and package a release on its native operating system."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wcm import __version__
from wcm.updates import platform_key


def build_command(root=ROOT):
    return [sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
            str(root / 'RR Character Manager.spec')]


def build_environment():
    env = os.environ.copy()
    for name in ('QT_PLUGIN_PATH', 'QML2_IMPORT_PATH', 'PYTHONPATH'):
        env.pop(name, None)
    if sys.platform == 'win32':
        python = Path(sys.executable).parent
        base = Path(sys.base_prefix)
        system = Path(env.get('SystemRoot', r'C:\Windows'))
        env['PATH'] = os.pathsep.join(map(str, (python, base, base/'Scripts', system/'System32', system)))
    return env


def check_dependencies():
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError('Release builds use Python 3.11. See README.md for setup.')
    for line in (ROOT/'requirements-release.txt').read_text().splitlines():
        if '==' not in line or line.startswith('#'):
            continue
        name, wanted = line.split('==', 1)
        if importlib.metadata.version(name) != wanted:
            raise RuntimeError('Install requirements-release.txt in a clean environment first.')


def package(output, target, binary=None):
    tag = 'RRCharacterManager-v' + __version__ + '-' + target
    name = 'RR character manager ' + __version__
    if binary is None:
        if sys.platform == 'win32':
            binary = ROOT/'dist'/(name+'.exe')
        elif sys.platform == 'darwin':
            binary = ROOT/'dist/RR Character Manager.app'
        else:
            binary = ROOT/'dist'/name
    if not binary.exists():
        raise FileNotFoundError(binary)
    with tempfile.TemporaryDirectory(prefix='rrcm-package-') as temporary:
        staging = Path(temporary)/tag;staging.mkdir()
        if binary.is_dir():
            shutil.copytree(binary, staging/binary.name, symlinks=True)
        else:
            shutil.copy2(binary, staging/binary.name)
        shutil.copy2(ROOT/'README.md', staging/'README.md')
        for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
            if (ROOT/name).is_file():shutil.copy2(ROOT/name, staging/name)
        shutil.copytree(ROOT/'THIRD_PARTY_NOTICES', staging/'THIRD_PARTY_NOTICES')
        if sys.platform == 'darwin':
            artifact = output/(tag+'.zip')
            subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(staging), str(artifact)], check=True)
        elif sys.platform == 'win32':
            artifact = output/(tag+'.zip')
            with zipfile.ZipFile(artifact, 'w', zipfile.ZIP_DEFLATED) as archive:
                for file in staging.rglob('*'):
                    if file.is_file():archive.write(file, file.relative_to(staging.parent))
        else:
            artifact = output/(tag+'.tar.gz')
            with tarfile.open(artifact, 'w:gz', dereference=False) as archive:archive.add(staging, arcname=tag)
    files = list(binary.rglob('*')) if binary.is_dir() else [binary]
    raw_size = sum(p.stat().st_size for p in files if p.is_file() and not p.is_symlink())
    report = {'version':__version__, 'platform':target, 'python':sys.version.split()[0],
              'payload_bytes':raw_size, 'archive_bytes':artifact.stat().st_size,
              'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()}
    (output/(tag+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
    (output/(tag+'.sha256')).write_text(report['sha256']+'  '+artifact.name+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
    return artifact


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'release')
    parser.add_argument('--package-only',action='store_true')
    args = parser.parse_args(argv)
    target = platform_key()
    if not target:raise RuntimeError('Unsupported release platform/architecture')
    output = args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    if not args.package_only:
        check_dependencies()
        subprocess.run([sys.executable, str(ROOT/'tools/collect_runtime_notices.py')], check=True)
        build = ROOT/'build';build.mkdir(exist_ok=True)
        if sys.platform == 'darwin':
            from PIL import Image
            with Image.open(ROOT/'full-motorcycle-helmet.png') as icon:icon.save(build/'release-icon.icns',format='ICNS')
        subprocess.run(build_command(),cwd=ROOT,env=build_environment(),check=True)
        name = 'RR character manager '+__version__
        executable = ROOT/'dist'/(name+'.exe') if sys.platform=='win32' else ROOT/'dist'/name/name
        if sys.platform=='darwin':executable=ROOT/'dist/RR Character Manager.app/Contents/MacOS'/name
        env = os.environ.copy();env['QT_QPA_PLATFORM']='offscreen'
        subprocess.run([str(executable),'--self-check',str(output/(target+'-self-check.json'))],env=env,check=True,timeout=60)
    return package(output,target)


if __name__ == '__main__':main()
