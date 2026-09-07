"""CLI entry point: `python -m sidekick --port 47821 --parent-pid 1234`."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
import threading
import time

from . import __version__


def _parent_watchdog(parent_pid: int) -> None:
    import psutil

    while True:
        time.sleep(2)
        if not psutil.pid_exists(parent_pid):
            logging.getLogger(__name__).warning("parent %s gone, exiting", parent_pid)
            os._exit(0)


def _setup_logging(level: str) -> None:
    from .paths import log_dir

    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    try:
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_dir() / "sidecar.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
            )
        )
    except OSError:
        pass
    logging.basicConfig(level=level.upper(), format=fmt, handlers=handlers)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sidekick", description="Sidekick sidecar")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--parent-pid", type=int, default=None)
    parser.add_argument("--log-level", default="info")
    parser.add_argument("--fake", action="store_true", help="use fake hardware backends")
    parser.add_argument("--config", default=None, help="path to config.toml (default: app data)")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    _setup_logging(args.log_level)
    log = logging.getLogger("sidekick")

    from pathlib import Path

    from .paths import config_path, db_path
    from .services import build_services

    cfg = Path(args.config) if args.config else config_path()
    services = build_services(cfg, db_path(), fake=args.fake)
    host = args.host or services.settings.server.host
    port = args.port or services.settings.server.port
    # keep the in-memory settings consistent with the port we actually bind (hook URLs depend on it)
    services.settings.server.host = host
    services.settings.server.port = port

    if args.parent_pid:
        threading.Thread(target=_parent_watchdog, args=(args.parent_pid,), daemon=True).start()

    from .app import create_app

    app = create_app(services)
    log.info("sidekick sidecar %s listening on http://%s:%s (fake=%s)", __version__, host, port, args.fake)

    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level=args.log_level.lower(), access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
