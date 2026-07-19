"""Fail-fast launcher for the dedicated client-app RQ worker."""
from __future__ import annotations

import os

import config
from client_tasks import validate_worker_config


def main() -> None:
    validate_worker_config()
    queue_name = config.CLIENT_QUEUE_NAME
    os.execvp(
        "rq",
        [
            "rq",
            "worker",
            queue_name,
            "--url",
            config.REDIS_URL,
        ],
    )


if __name__ == "__main__":
    main()
