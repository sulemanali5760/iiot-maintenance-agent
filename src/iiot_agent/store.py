import math
import sqlite3
import threading
from datetime import datetime, timezone

from .model import Reading


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS readings (
                ts TEXT, asset TEXT, sensor TEXT, value REAL, unit TEXT, status INTEGER
            );
            CREATE INDEX IF NOT EXISTS readings_sensor_ts ON readings(asset, sensor, ts);
        """)

    def insert(self, reading: Reading) -> None:
        if not math.isfinite(reading.value) or not reading.asset or not reading.sensor:
            raise ValueError("Reading needs a finite value, asset and sensor")
        timestamp = datetime.fromisoformat(reading.ts)
        if timestamp.utcoffset() is None:
            raise ValueError("Reading timestamp needs a timezone")
        ts = timestamp.astimezone(timezone.utc).isoformat()
        with self._lock, self._db:
            self._db.execute("INSERT INTO readings VALUES (?, ?, ?, ?, ?, ?)",
                             (ts, reading.asset, reading.sensor, reading.value,
                              reading.unit, reading.status))

    def latest(self, asset: str, sensor: str, n: int) -> list[Reading]:
        with self._lock:
            rows = self._db.execute("""SELECT * FROM readings WHERE asset=? AND sensor=?
                ORDER BY ts DESC, rowid DESC LIMIT ?""", (asset, sensor, n)).fetchall()
        return [Reading(**dict(row)) for row in reversed(rows)]

    def window(self, asset: str, sensor: str, since_ts: str) -> list[Reading]:
        timestamp = datetime.fromisoformat(since_ts)
        if timestamp.utcoffset() is None:
            raise ValueError("Window timestamp needs a timezone")
        since_ts = timestamp.astimezone(timezone.utc).isoformat()
        with self._lock:
            rows = self._db.execute("""SELECT * FROM readings WHERE asset=? AND sensor=?
                AND ts>=? ORDER BY ts, rowid""", (asset, sensor, since_ts)).fetchall()
        return [Reading(**dict(row)) for row in rows]

    def stats(self, asset: str, sensor: str, n: int) -> dict:
        with self._lock:
            row = self._db.execute("""SELECT COUNT(*) AS count, MIN(value) AS min,
                MAX(value) AS max, AVG(value) AS avg FROM
                (SELECT value FROM readings WHERE asset=? AND sensor=?
                 ORDER BY ts DESC, rowid DESC LIMIT ?)""", (asset, sensor, n)).fetchone()
        return dict(row)

    def close(self) -> None:
        with self._lock:
            self._db.close()
