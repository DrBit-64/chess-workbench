from __future__ import annotations

import argparse
import json
import time
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def wait_for_health(url: str, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as response:  # noqa: S310 - URL is a CLI smoke target
                if response.status != 200:
                    raise RuntimeError(f"{url} returned HTTP {response.status}")
                payload = cast(dict[str, Any], json.load(response))
                if payload != {
                    "status": "ok",
                    "service": "chess-workbench-api",
                    "version": "0.1.0",
                    "database": "ok",
                }:
                    raise RuntimeError(f"{url} returned an unexpected payload: {payload!r}")
                return payload
        except (HTTPError, URLError, TimeoutError, RuntimeError) as error:
            last_error = error
            time.sleep(0.2)

    raise RuntimeError(f"health check timed out for {url}: {last_error}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wait for and validate health endpoints")
    parser.add_argument("urls", nargs="+", help="health URLs to validate")
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for url in args.urls:
        wait_for_health(url, args.timeout)
        print(f"healthy: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
