import logging


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Third-party libraries are chatty at INFO.
    for noisy in ("httpx", "httpx2", "httpcore", "fastembed", "pypdf", "alembic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
