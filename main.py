"""Entry point for the Retro Rewind Character Manager desktop app."""
if __name__ == '__main__':
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == '--self-check':
        from wcm.selfcheck import run
        raise SystemExit(run(sys.argv[2]))
    try:
        from wcm.gui import launch
    except ImportError as exc:
        if 'PySide6' in str(exc):
            raise SystemExit('PySide6 is not installed. Run: python -m pip install -r requirements.txt') from exc
        raise
    raise SystemExit(launch())
