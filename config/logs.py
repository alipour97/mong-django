"""
One log file a day in LOGS_DIR (`app-2026-11-03.log`), shared by the web workers and the cron commands.

Each line is appended with its own write, so several processes can write the same file without a lock;
the name is picked again on every line, which is the rotation. Files older than KEEP_DAYS are removed.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from pathlib import Path

KEEP_DAYS = 30


class DailyFileHandler(logging.Handler):
    def __init__(self, directory: str, prefix: str = "app"):
        super().__init__()
        self.directory = Path(directory)
        self.prefix = prefix
        self._day = None

    def _path(self, day: dt.date) -> Path:
        return self.directory / f"{self.prefix}-{day.isoformat()}.log"

    def _new_day(self, day: dt.date) -> None:
        self._day = day
        self.directory.mkdir(parents=True, exist_ok=True)
        oldest = day - dt.timedelta(days=KEEP_DAYS)
        for old in self.directory.glob(f"{self.prefix}-*.log"):
            try:
                if dt.date.fromisoformat(old.stem[len(self.prefix) + 1:]) < oldest:
                    old.unlink()
            except (ValueError, OSError):
                pass

    def emit(self, record: logging.LogRecord) -> None:
        try:
            day = dt.date.today()
            if day != self._day:
                self._new_day(day)
            line = (self.format(record) + "\n").encode("utf-8")
            fd = os.open(self._path(day), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                os.write(fd, line)
            finally:
                os.close(fd)
        except Exception:
            self.handleError(record)
