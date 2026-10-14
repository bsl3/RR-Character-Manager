"""Windows entry point for the shared release builder."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_release import main as build_release


def main():
    if sys.platform != 'win32':
        raise RuntimeError('Run tools/build_release.py on macOS or Linux.')
    return build_release([])


if __name__ == '__main__':main()
