"""PyInstaller entry point: the `lprism` CLI, frozen."""

import multiprocessing

from loopprism.cli.main import app

if __name__ == "__main__":
    multiprocessing.freeze_support()
    app()
