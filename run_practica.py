from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = Path(__file__).resolve().parent
APP = BASE / "app"
EVID = BASE / "evidence"
RUNTIME = BASE / "runtime"
EVID.mkdir(exist_ok=True); RUNTIME.mkdir(exist_ok=True)
sys.path.insert(0, str(APP))
from client import post 


def reset_runtime() -> None:
    for name in ["primary_state.json", "standby_state.json", "primary_lease.json"]:
        p = RUNTIME / name
        if p.exists(): p.unlink()
    for name in ["audit_security.csv"]:
        p = EVID / name
        if p.exists(): p.unlink()


def start(port: int, role: str = "primary", security: bool = True, priority: bool = True):
    args = [sys.executable, str(APP / "core.py"), "--role", role, "--port", str(port),
            "--security" if security else "--no-security", "--priority" if priority else "--no-priority"]
    log_path = EVID / f"server_{role}_{port}.log"
    log = log_path.open("w", encoding="utf-8")
    p = subprocess.Popen(args, stdout=log, stderr=log)
    time.sleep(1.0)
    return p, log


def stop(p):
    if p.poll() is None:
        p.terminate()
        try: p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            p.kill(); p.wait(timeout=2)


def write_csv(path: Path, rows: list[dict]):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader(); w.writerows(rows)


def experiment_s2() -> dict:
    reset_runtime(); p, log = start(5101, "primary", True, True)
    rows=[]
    try:
        for i in range(20):
            status, body, latency = post("http://127.0.0.1:5101/balance",
                {"token":"token-u001","card":"T200"})
            rows.append({"attempt":i+1,"status":status,"blocked":int(status==403),
                         "latency_ms":round(latency,3),"reason":body.get("reason","")})
        time.sleep(0.3)
    finally:
        stop(p); log.close()
    out=EVID/"s2_security.csv"; write_csv(out,rows)
    block_attempt=next((r["attempt"] for r in rows if r["reason"]=="umbral_10_bloqueo"), None)
    return {"scenario":"S2","requests":len(rows),"rejected_pct":100*sum(r["blocked"] for r in rows)/len(rows),
            "block_attempt":block_attempt or "NO","csv":str(out)}


def experiment_p1(duration: int, rps: int, priority: bool, security: bool = True, label: str | None = None) -> dict:
    reset_runtime(); p, log = start(5101, "primary", security, priority)
    rows=[]; futures=[]
    start_t=time.perf_counter(); end_t=start_t+duration
    executor=ThreadPoolExecutor(max_workers=64)
    next_validate=start_t
    next_summary=start_t
    try:
        while time.perf_counter() < end_t:
            now=time.perf_counter()
            while next_validate <= now:
                futures.append(("validate", executor.submit(post, "http://127.0.0.1:5101/validate",
                    {"token":"token-u001","card":"T100","fare":0})))
                next_validate += 1.0/rps
            while next_summary <= now:
                futures.append(("summary", executor.submit(post, "http://127.0.0.1:5101/summary", {"report":"monthly"})))
                next_summary += 1.0/20
            time.sleep(0.001)
        for kind, fut in futures:
            try:
                status, body, latency = fut.result(timeout=5)
            except Exception as exc:
                status, body, latency = 599, {"ok":False,"error":str(exc)}, 5000
            rows.append({"kind":kind,"status":status,"latency_ms":round(latency,3),
                         "server_ok":int(body.get("ok",False))})
    finally:
        executor.shutdown(wait=True)
        stop(p); log.close()
    stem = label or ("p1_with_priority" if priority else "p1_baseline")
    out=EVID/(stem+".csv"); write_csv(out,rows)
    vals=sorted(r["latency_ms"] for r in rows if r["kind"]=="validate")
    def percentile(pct: float)->float:
        if not vals: return 0.0
        idx=min(len(vals)-1,int(round((pct/100)*(len(vals)-1))))
        return vals[idx]
    ok=sum(r["server_ok"] for r in rows if r["kind"]=="validate")
    n=max(1,len(vals))
    return {"scenario":"P1","priority":priority,"requests":len(rows),"validations":len(vals),
            "p95_ms":percentile(95),"p99_ms":percentile(99),"success_pct":100*ok/n,"csv":str(out)}


def experiment_d1() -> dict:
    reset_runtime(); primary, log1=start(5101,"primary",True,True); standby, log2=start(5102,"standby",True,True)
    rows=[]
    try:
        post("http://127.0.0.1:5101/validate",{"token":"token-u001","card":"T100","fare":1})
        time.sleep(0.8)
        t_fail=time.time(); stop(primary); log1.close()
        # Lease TTL: no ping/echo. Detectamos que el timestamp dejo de renovarse.
        last_ts=None
        for _ in range(80):
            if (RUNTIME/"primary_lease.json").exists():
                current=json.loads((RUNTIME/"primary_lease.json").read_text()).get("ts",0)
                if last_ts is None: last_ts=current
                age=time.time()-current
                if age>=2.0: break
            time.sleep(0.1)
        detected=time.time(); detection=detected-t_fail
        status,body,latency=post("http://127.0.0.1:5102/balance",{"token":"token-u001","card":"T100"})
        rows.append({"event":"failover","detection_s":round(detection,3),"standby_status":status,
                     "standby_ok":int(body.get("ok",False)),"latency_ms":round(latency,3)})
    finally:
        stop(primary); stop(standby)
        if not log1.closed: log1.close()
        log2.close()
    out=EVID/"d1_failover.csv"; write_csv(out,rows)
    return {"scenario":"D1","detection_s":rows[0]["detection_s"],
            "confirmed_requests_lost":0 if rows[0]["standby_ok"] else 1,"csv":str(out)}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--full",action="store_true"); ap.add_argument("--seconds",type=int,default=10); ap.add_argument("--rps",type=int,default=500)
    args=ap.parse_args(); duration=600 if args.full else args.seconds
    s2=experiment_s2()
    p1_no_security=experiment_p1(duration,args.rps,True,False,"p1_no_security")
    p1_security_base=experiment_p1(duration,args.rps,False,True,"p1_security_baseline")
    p1_security_priority=experiment_p1(duration,args.rps,True,True,"p1_security_priority")
    d1=experiment_d1()
    overhead = ((p1_security_priority["p95_ms"] / p1_no_security["p95_ms"]) - 1) * 100 if p1_no_security["p95_ms"] else 0
    result={"S2":s2,"P1_no_security":p1_no_security,"P1_security_baseline":p1_security_base,"P1_security_priority":p1_security_priority,"security_overhead_p95_pct":round(overhead,2),"D1":d1}
    (EVID/"summary_results.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))

if __name__=="__main__": main()
