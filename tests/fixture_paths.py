"""Optional private fixtures; set RRCM_FIXTURES to a folder of supplied archives."""
import os
from pathlib import Path
import unittest

def fixture_path(name):
    root=Path(os.environ.get('RRCM_FIXTURES','/mnt/data'))
    alias={'bikerwario-porko_v1(1).zip':'bikerwario-porko_v1.zip'}
    path=root/name
    if not path.exists(): path=root/alias.get(name,name)
    return path

def require_fixture(name):
    path=fixture_path(name)
    if not path.is_file(): raise unittest.SkipTest(f'Optional private fixture unavailable: {name}')
    return path
