"""Trade Copilot entry point.

Usage:
    .venv/bin/python run.py                 # simulated feed (no credentials needed)
    .venv/bin/python run.py --feed schwab   # live MNQ via Schwab
    .venv/bin/python run.py --port 8000
"""
from __future__ import annotations

import argparse
import asyncio
import logging

import uvicorn

from app.runtime import Runtime
from app.server.api import create_app

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Trade Copilot - MNQ signal advisor")
    parser.add_argument("--feed", choices=["sim", "schwab"], default="sim")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    runtime = Runtime(feed_mode=args.feed)
    feed = runtime.build_feed()
    app = create_app(runtime)

    config = uvicorn.Config(app, host="127.0.0.1", port=args.port,
                            log_level="warning", loop="asyncio")
    server = uvicorn.Server(config)

    log.info("Dashboard: http://127.0.0.1:%d  (feed: %s, symbol: %s)",
             args.port, args.feed, runtime.symbol)
    feed_task = asyncio.create_task(feed.run(runtime.on_quote))
    server_task = asyncio.create_task(server.serve())
    done, pending = await asyncio.wait({feed_task, server_task},
                                       return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in done:
        exc = task.exception()
        if exc:
            raise exc


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
