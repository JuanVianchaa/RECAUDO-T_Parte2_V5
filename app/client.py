from __future__ import annotations
import json
import time
import urllib.error
import urllib.request
from statistics import quantiles
from typing import Any


def post(url: str, data: dict[str, Any], timeout: float = 2.0) -> tuple[int, dict[str, Any], float]:
    raw = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=raw, method="POST", headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return resp.status, body, (time.perf_counter() - t0) * 1000
    except urllib.error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8")
        return exc.code, json.loads(raw_body), (time.perf_counter() - t0) * 1000
    except Exception as exc:
        return 599, {"error": str(exc)}, (time.perf_counter() - t0) * 1000


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    idx = min(len(v) - 1, int(round((p / 100.0) * (len(v) - 1))))
    return v[idx]
