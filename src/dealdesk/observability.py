"""Structured JSON logging and in-process Prometheus-style metrics."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import threading
import time
from collections import defaultdict

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id.get(),
        }
        payload.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def log_event(logger: logging.Logger, msg: str, **fields) -> None:
    logger.info(msg, extra={"extra_fields": fields})


class Metrics:
    """Minimal thread-safe counters and summaries exposed in Prometheus text format."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: dict[tuple, float] = defaultdict(float)
        self.sums: dict[tuple, float] = defaultdict(float)
        self.counts: dict[tuple, int] = defaultdict(int)

    def inc(self, name: str, value: float = 1.0, **labels) -> None:
        with self._lock:
            self.counters[(name, tuple(sorted(labels.items())))] += value

    def observe(self, name: str, value: float, **labels) -> None:
        key = (name, tuple(sorted(labels.items())))
        with self._lock:
            self.sums[key] += value
            self.counts[key] += 1

    def render(self) -> str:
        def fmt(labels):
            return "{" + ",".join(f'{k}="{v}"' for k, v in labels) + "}" if labels else ""
        lines = []
        with self._lock:
            for (name, labels), v in sorted(self.counters.items()):
                lines.append(f"{name}{fmt(labels)} {v}")
            for (name, labels), v in sorted(self.sums.items()):
                lines.append(f"{name}_sum{fmt(labels)} {v:.6f}")
                lines.append(f"{name}_count{fmt(labels)} {self.counts[(name, labels)]}")
        return "\n".join(lines) + "\n"


METRICS = Metrics()
