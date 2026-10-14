"""Optional GitHub Releases checks."""
import json
import re
import ssl
import platform
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

DEFAULT_REPOSITORY = 'https://github.com/bsl3/RR-Character-Manager'


def repository(value):
    value = value.strip().rstrip('/')
    if not value:
        return ''
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or parsed.netloc != 'github.com'
            or parsed.query or parsed.fragment
            or not re.fullmatch(r'/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', parsed.path)):
        raise ValueError('Use https://github.com/OWNER/REPOSITORY')
    return parsed.path.strip('/').removesuffix('.git')


def version(tag):
    match = re.fullmatch(r'[vV]?(\d+)\.(\d+)(?:\.(\d+))?', str(tag))
    if not match:
        raise ValueError('Release tags must use vMAJOR.MINOR or vMAJOR.MINOR.PATCH')
    return tuple(int(part or 0) for part in match.groups())


def release_url(url, owner, kind):
    parsed = urlsplit(url)
    return (parsed.scheme == 'https' and parsed.netloc == 'github.com'
            and parsed.path.casefold().startswith('/' + owner.casefold() + '/releases/' + kind + '/'))


def open_release(request, timeout):
    import certifi
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    return urlopen(request, timeout=timeout, context=context)


def platform_key(system=None, machine=None):
    system = system or sys.platform
    machine = (machine or platform.machine()).lower()
    os_name = {'win32': 'windows', 'darwin': 'macos'}.get(system, 'linux' if system.startswith('linux') else '')
    arch = {'amd64': 'x86_64', 'x64': 'x86_64', 'x86_64': 'x86_64',
            'arm64': 'arm64', 'aarch64': 'arm64'}.get(machine, '')
    return os_name + '-' + arch if os_name and arch else ''


def latest(repo, current, opener=None):
    owner = repository(repo)
    opener = opener or open_release
    if not owner:
        return None
    request = Request('https://api.github.com/repos/' + owner + '/releases/latest', headers={
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'RRCharacterManager/' + current,
        'X-GitHub-Api-Version': '2022-11-28',
    })
    try:
        with opener(request, timeout=8) as response:
            raw = response.read(1024 * 1024 + 1)
    except HTTPError as error:
        if error.code == 404:
            raise ValueError('Repository has no published release yet, or is unavailable') from error
        raise
    if len(raw) > 1024 * 1024:
        raise ValueError('Release response is too large')
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('Invalid release response')
    if data.get('draft') or data.get('prerelease') or version(data.get('tag_name')) <= version(current):
        return None
    page = data.get('html_url', '')
    if not release_url(page, owner, 'tag'):
        raise ValueError('Unexpected release URL')
    downloads = [asset for asset in data.get('assets', [])
                 if asset.get('state') == 'uploaded'
                 and release_url(asset.get('browser_download_url', ''), owner, 'download')
                 and str(asset.get('name', '')).lower().endswith(('.zip', '.exe', '.tar.gz'))
                 and platform_key()
                 and ('-' + platform_key() + '.') in str(asset.get('name', '')).lower()]
    # Let the user choose on GitHub when a release has several assets.
    download = downloads[0]['browser_download_url'] if len(downloads) == 1 else page
    return {'version': data['tag_name'], 'page': page, 'download': download}
