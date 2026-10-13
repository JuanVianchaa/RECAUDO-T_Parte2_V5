#!/usr/bin/env python3
"""Test worker thread latency with security enabled."""
import time
import threading
from app.core import App, PriorityEngine

def test_validate_direct_security():
    """Time validate calls directly with security enabled."""
    print("Timing direct validate calls with security enabled...")
    app = App(security=True, priority=False)  # Security on, priority off

    times = []
    for i in range(100):
        start = time.perf_counter()
        status, body = app.validate('token-u001', 'T100', 0, secure=True)
        end = time.perf_counter()
        times.append((end - start) * 1000)

    avg = sum(times) / len(times)
    p95 = sorted(times)[int(0.95 * len(times))] if times else 0
    print(f"  Direct validate (security on): avg={avg:.2f}ms, p95={p95:.2f}ms")

def test_priority_engine_with_validate_lambda_security():
    """Test priority engine with validate lambda, security enabled."""
    print("Testing priority engine with validate lambda (security enabled)...")
    app = App(security=True, priority=True)  # Security on, priority on

    times = []
    for i in range(100):
        start = time.perf_counter()
        status, body = app.validate('token-u001', 'T100', 0, secure=False)  # Note: secure=False in validate call
        end = time.perf_counter()
        times.append((end - start) * 1000)

    avg = sum(times) / len(times)
    p95 = sorted(times)[int(0.95 * len(times))] if times else 0
    print(f"  Priority engine (validate lambda, security on): avg={avg:.2f}ms, p95={p95:.2f}ms")

if __name__ == "__main__":
    test_validate_direct_security()
    test_priority_engine_with_validate_lambda_security()