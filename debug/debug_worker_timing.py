#!/usr/bin/env python3
"""Debug script to time how long validate takes in worker context."""
import time
import threading
from app.core import App, PriorityEngine

def test_validate_direct():
    """Time validate calls directly."""
    print("Timing direct validate calls...")
    app = App(security=False, priority=False)

    times = []
    for i in range(100):
        start = time.perf_counter()
        status, body = app.validate('token-u001', 'T100', 0, secure=False)
        end = time.perf_counter()
        times.append((end - start) * 1000)

    avg = sum(times) / len(times)
    p95 = sorted(times)[int(0.95 * len(times))] if times else 0
    print(f"  Direct validate: avg={avg:.2f}ms, p95={p95:.2f}ms")

def test_validate_lambda():
    """Time the validate lambda directly."""
    print("Timing validate lambda directly...")
    app = App(security=False, priority=False)

    def validate_lambda():
        return app.validate('token-u001', 'T100', 0, secure=False)

    times = []
    for i in range(100):
        start = time.perf_counter()
        status, body = validate_lambda()
        end = time.perf_counter()
        times.append((end - start) * 1000)

    avg = sum(times) / len(times)
    p95 = sorted(times)[int(0.95 * len(times))] if times else 0
    print(f"  Validate lambda: avg={avg:.2f}ms, p95={p95:.2f}ms")

def test_priority_engine_with_fast_work():
    """Test priority engine with a fast simulated workload."""
    print("Testing priority engine with fast simulated work...")
    engine = PriorityEngine(enabled=True, workers=4)

    def fast_work():
        # Simulate the actual work done in validate when security=False
        time.sleep(0.002)  # 2ms for the simulated policy/tariff access
        # Simulate the state access (should be very fast)
        return (200, {"ok": True, "data": "test"})

    times = []
    for i in range(100):
        start = time.perf_counter()
        status, body = engine.submit_and_wait("test", fast_work, priority=0)
        end = time.perf_counter()
        times.append((end - start) * 1000)

    avg = sum(times) / len(times)
    p95 = sorted(times)[int(0.95 * len(times))] if times else 0
    print(f"  Priority engine (fast work): avg={avg:.2f}ms, p95={p95:.2f}ms")

    # Cleanup
    engine.stop = True
    for t in engine.workers:
        t.join(timeout=1)

def test_priority_engine_with_validate_lambda():
    """Test priority engine with the actual validate lambda."""
    print("Testing priority engine with validate lambda...")
    app = App(security=False, priority=True)  # This initializes the priority engine inside App

    times = []
    for i in range(100):
        start = time.perf_counter()
        status, body = app.validate('token-u001', 'T100', 0, secure=False)
        end = time.perf_counter()
        times.append((end - start) * 1000)

    avg = sum(times) / len(times)
    p95 = sorted(times)[int(0.95 * len(times))] if times else 0
    print(f"  Priority engine (validate lambda): avg={avg:.2f}ms, p95={p95:.2f}ms")

if __name__ == "__main__":
    test_validate_direct()
    test_validate_lambda()
    test_priority_engine_with_fast_work()
    test_priority_engine_with_validate_lambda()