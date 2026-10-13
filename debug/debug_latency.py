#!/usr/bin/env python3
"""Debug script to isolate where latency is coming from."""
import time
import threading
from app.core import App, PriorityEngine

def test_direct_validate():
    """Test calling validate directly without priority engine."""
    print("Testing direct validate calls (no priority engine)...")
    app = App(security=False, priority=False)  # Don't even initialize priority engine

    latencies = []
    for i in range(100):
        start = time.perf_counter()
        status, body = app.validate('token-u001', 'T100', 0, secure=False)
        end = time.perf_counter()
        latencies.append((end - start) * 1000)

    avg = sum(latencies) / len(latencies)
    p95 = sorted(latencies)[int(0.95 * len(latencies))] if latencies else 0
    print(f"  Direct validate: avg={avg:.2f}ms, p95={p95:.2f}ms")

def test_priority_engine_overhead():
    """Test priority engine overhead with a simple function."""
    print("Testing priority engine overhead...")
    engine = PriorityEngine(enabled=True, workers=4)  # Fewer workers for testing

    def simple_fn():
        time.sleep(0.002)  # 2ms sleep to simulate work
        return (200, {"ok": True})

    latencies = []
    for i in range(100):
        start = time.perf_counter()
        status, body = engine.submit_and_wait("test", simple_fn, priority=0)
        end = time.perf_counter()
        latencies.append((end - start) * 1000)

    avg = sum(latencies) / len(latencies)
    p95 = sorted(latencies)[int(0.95 * len(latencies))] if latencies else 0
    print(f"  Priority engine (simple 2ms work): avg={avg:.2f}ms, p95={p95:.2f}ms")

    # Clean up
    engine.stop = True
    for t in engine.workers:
        t.join(timeout=1)

def test_validate_via_priority_engine():
    """Test validate calls going through priority engine."""
    print("Testing validate via priority engine...")
    app = App(security=False, priority=True)  # Security off, priority on

    latencies = []
    for i in range(100):
        start = time.perf_counter()
        status, body = app.validate('token-u001', 'T100', 0, secure=False)
        end = time.perf_counter()
        latencies.append((end - start) * 1000)

    avg = sum(latencies) / len(latencies)
    p95 = sorted(latencies)[int(0.95 * len(latencies))] if latencies else 0
    print(f"  Validate via priority engine: avg={avg:.2f}ms, p95={p95:.2f}ms")

if __name__ == "__main__":
    test_direct_validate()
    test_priority_engine_overhead()
    test_validate_via_priority_engine()