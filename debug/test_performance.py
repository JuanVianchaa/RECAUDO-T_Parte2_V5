#!/usr/bin/env python3
"""Simple performance test for the validate endpoint."""
import time
import threading
from app.core import App
from statistics import quantiles

def validate_worker(app, results, worker_id, num_requests):
    """Worker function to make multiple validate requests."""
    for i in range(num_requests):
        start = time.perf_counter()
        status, body = app.validate('token-u001', 'T100', 0, secure=True)
        end = time.perf_counter()
        latency_ms = (end - start) * 1000
        results.append(latency_ms)
        # Small delay between requests to avoid overwhelming
        time.sleep(0.001)

def run_test(num_workers=10, requests_per_worker=50):
    """Run a performance test with multiple workers."""
    print(f"Starting performance test with {num_workers} workers, {requests_per_worker} requests each...")

    # Test with security enabled
    app = App(security=True, priority=False)
    results = []

    # Create and start worker threads
    threads = []
    for i in range(num_workers):
        t = threading.Thread(target=validate_worker, args=(app, results, i, requests_per_worker))
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
        print(f"\nResults ({len(results)} total requests):")
        print(f"  Average latency: {avg:.2f} ms")
        print(f"  p95 latency: {p95:.2f} ms")
        print(f"  p99 latency: {p99:.2f} ms")
        print(f"  Min latency: {min(results):.2f} ms")
        print(f"  Max latency: {max(results):.2f} ms")
    else:
        print("No results collected!")

if __name__ == "__main__":
    run_test()