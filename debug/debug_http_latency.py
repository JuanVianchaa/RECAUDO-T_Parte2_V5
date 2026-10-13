#!/usr/bin/env python3
"""Debug script to test HTTP latency mimicking the experimental setup."""
import time
import threading
import subprocess
import sys
from pathlib import Path
import os
sys.path.insert(0, str(Path(__file__).parent / "app"))
from client import post
from statistics import quantiles

def start_server(security=False, priority=True, port=5101):
    """Start the HTTP server."""
    from app.core import serve
    import threading

    # We'll start the server in a subprocess like the experiment does
    args = [sys.executable, str(Path(__file__).parent / "app" / "core.py"),
            "--role", "primary", "--port", str(port)]
    if not security:
        args.append("--no-security")
    if priority:
        args.append("--priority")
    else:
        args.append("--no-priority")

    import os
    log_file = open(f"server_debug_{port}.log", "w")
    proc = subprocess.Popen(args, stdout=log_file, stderr=log_file)
    time.sleep(1.5)  # Give server time to start
    return proc, log_file

def stop_server(proc, log_file):
    """Stop the HTTP server."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1)
    log_file.close()

def make_validate_requests(num_requests, num_threads):
    """Make validate requests using multiple threads."""
    results = []

    def worker(thread_id, num_requests_per_thread):
        thread_results = []
        for i in range(num_requests_per_thread):
            start = time.perf_counter()
            try:
                status, body, latency = post(
                    "http://127.0.0.1:5101/validate",
                    {"token":"token-u001","card":"T100","fare":0}
                )
                end = time.perf_counter()
                thread_results.append(((end - start) * 1000, status, body.get("ok", False)))
            except Exception as e:
                end = time.perf_counter()
                thread_results.append(((end - start) * 1000, 599, False))
        results.extend(thread_results)

    # Create and start threads
    threads = []
    requests_per_thread = num_requests // num_threads
    for i in range(num_threads):
        t = threading.Thread(target=worker, args=(i, requests_per_thread))
        threads.append(t)
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join()

    return results

def run_test():
    """Run a test mimicking the experimental setup."""
    security = True
    priority = True
    print(f"Starting HTTP server with security={security}, priority={priority}...")
    proc, log_file = start_server(security=security, priority=priority, port=5101)

    try:
        print("Making concurrent validate requests...")
        # Similar to experiment: 5000 validation requests with some concurrency
        results = make_validate_requests(num_requests=100, num_threads=10)  # Smaller set for quick test

        if results:
            latencies = [r[0] for r in results]
            success_count = sum(1 for r in results if r[2])  # r[2] is the 'ok' flag
            total_count = len(results)

            if latencies:
                p95 = quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)
                p99 = quantiles(latencies, n=100)[98] if len(latencies) >= 100 else max(latencies)
                avg = sum(latencies) / len(latencies)

                print(f"\nResults ({total_count} requests):")
                print(f"  Successful: {success_count}/{total_count} ({100*success_count/total_count:.1f}%)")
                print(f"  Average latency: {avg:.2f} ms")
                print(f"  p95 latency: {p95:.2f} ms")
                print(f"  p99 latency: {p99:.2f} ms")
                print(f"  Min latency: {min(latencies):.2f} ms")
                print(f"  Max latency: {max(latencies):.2f} ms")

    finally:
        print("Stopping server...")
        stop_server(proc, log_file)

if __name__ == "__main__":
    run_test()