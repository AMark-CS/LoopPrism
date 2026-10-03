"""Logging configuration for loopprism."""

import logging
import sys

# Module-level logger
logger = logging.getLogger("loopprism")


def setup_logging(verbose: bool = False) -> None:
    """Configure loopprism logging.

    Args:
        verbose: If True, set level to DEBUG. Otherwise INFO.
    """
    level = logging.DEBUG if verbose else logging.INFO

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ),
    )

    logger.setLevel(level)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False
