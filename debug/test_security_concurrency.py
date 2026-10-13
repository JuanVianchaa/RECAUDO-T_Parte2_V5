#!/usr/bin/env python3
"""Test security mechanism under concurrent load."""
import time
import threading
from app.core import App
from statistics import quantiles

def security_check_worker(app, results, worker_id, num_checks):
    """Worker function to make multiple security check requests."""
    for i in range(num_checks):
        start = time.perf_counter()
        # Use valid credentials to test the success path
        status, body = app.validate('token-u001', 'T100', 0, secure=True)
        end = time.perf_counter()
        latency_ms = (end - start) * 1000
        results.append(latency_ms)
        # Small delay between requests
        time.sleep(0.001)

def run_security_test(num_workers=10, checks_per_worker=50):
    """Run a security concurrency test."""
    print(f"Testing security mechanism under load: {num_workers} workers, {checks_per_worker} checks each...")

    # Test with security enabled
    app = App(security=True, priority=False)  # Disable priority to isolate security effects
    results = []

    # Create and start worker threads
    threads = []
    for i in range(num_workers):
        t = threading.Thread(target=security_check_worker, args=(app, results, i, checks_per_worker))
        threads.append(t)
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join()

    # Calculate statistics
    if results:
        p95 = quantiles(results, n=20)[18] if len(results) >= 20 else max(results)
        p99 = quantiles(results, n=100)[98] if len(results) >= 100 else max(results)
        avg = sum(results) / len(results)
        print(f"\nSecurity check results ({len(results)} total checks):")
        print(f"  Average latency: {avg:.2f} ms")
        print(f"  p95 latency: {p95:.2f} ms")
        print(f"  p99 latency: {p99:.2f} ms")
        print(f"  Min latency: {min(results):.2f} ms")
        print(f"  Max latency: {max(results):.2f} ms")
    else:
        print("No results collected!")

if __name__ == "__main__":
    run_security_test()