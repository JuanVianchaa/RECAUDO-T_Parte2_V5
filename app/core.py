from __future__ import annotations

import csv
import json
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import PriorityQueue, Empty, Queue
from typing import Any, Callable, Dict, Optional, Tuple

# ============ CONSTANTES Y CONFIGURACIÓN ============
BASE = Path(__file__).resolve().parent.parent
STATE_DIR = BASE / "runtime"
EVIDENCE_DIR = BASE / "evidence"
STATE_DIR.mkdir(exist_ok=True)
EVIDENCE_DIR.mkdir(exist_ok=True)
PRIMARY_STATE = STATE_DIR / "primary_state.json"
STANDBY_STATE = STATE_DIR / "standby_state.json"
LEASE_FILE = STATE_DIR / "primary_lease.json"
AUDIT_FILE = EVIDENCE_DIR / "audit_security.csv"

INITIAL_CARDS = {
    "T100": {"owner": "U001", "balance": 200000},
    "T200": {"owner": "U002", "balance": 180000},
    "T300": {"owner": "U003", "balance": 150000},
}
TOKENS = {"token-u001": "U001", "token-u002": "U002", "token-u003": "U003"}

# ============ CLASES ESPECIALIZADAS ============

class SecurityManager:
    """Gestiona la táctica S2: Autorización de actores + bloqueo por umbral."""

    def __init__(self):
        self.state_lock = threading.RLock()
        self.attempts: Dict[str, list[float]] = defaultdict(list)
        self.blocked_until: Dict[str, float] = {}
        self.audit_lock = threading.Lock()
        self.audit_queue: Queue[Dict[str, Any]] = Queue()

        # Iniciar worker de auditoría
        threading.Thread(target=self._audit_worker, daemon=True).start()

    def _audit_worker(self) -> None:
        """Worker dedicado para escritura asíncrona de auditoría."""
        while True:
            event = self.audit_queue.get()
            try:
                fields = ["ts", "token", "user", "card", "action", "allowed", "reason"]
                with self.audit_lock:
                    exists = AUDIT_FILE.exists()
                    with AUDIT_FILE.open("a", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=fields)
                        if not exists:
                            writer.writeheader()
                        writer.writerow({k: event.get(k, "") for k in fields})
            finally:
                self.audit_queue.task_done()

    def check_security(self, token: str, card: str) -> Tuple[bool, str, str]:
        """
        Ejecuta la verificación de seguridad S2.
        Retorna: (allowed, user, reason)
        """
        user = TOKENS.get(token, "")
        now = time.time()

        # Verificar bloqueo temporal y limpiar intentos expirados
        with self.state_lock:
            if token in self.blocked_until and self.blocked_until[token] > now:
                return False, user, "token_bloqueado_temporalmente"

            if token in self.blocked_until and self.blocked_until[token] <= now:
                del self.blocked_until[token]
                self.attempts[token].clear()

        # Validar credenciales (no necesita lock ya que TOKENS e INITIAL_CARDS son constantes)
        owner = None
        if card in INITIAL_CARDS:
            owner = INITIAL_CARDS[card]["owner"]

        if not user:
            reason = "credencial_invalida"
            self._audit_event(now, token, "", card, "balance", 0, reason)
            return False, "", reason

        if owner != user:
            # Registrar intento fallido - necesita lock para acceder a attempts y blocked_until
            with self.state_lock:
                self.attempts[token].append(now)
                cutoff = now - 60
                self.attempts[token] = [t for t in self.attempts[token] if t >= cutoff]

                if len(self.attempts[token]) >= 10:
                    self.blocked_until[token] = now + 60
                    reason = "umbral_10_bloqueo"
                    self._audit_event(now, token, user, card, "balance", 0, reason)
                    return False, user, reason

            reason = "tarjeta_ajena"
            self._audit_event(now, token, user, card, "balance", 0, reason)
            return False, user, reason

        # Credenciales válidas
        self._audit_event(now, token, user, card, "balance", 1, "propiedad_valida")
        return True, user, "ok"

    def _audit_event(self, ts: float, token: str, user: str, card: str,
                     action: str, allowed: int, reason: str) -> None:
        """Agrega un evento a la cola de auditoría."""
        self.audit_queue.put({
            "ts": ts, "token": token, "user": user, "card": card,
            "action": action, "allowed": allowed, "reason": reason
        })


class ReplicationManager:
    """Gestiona la táctica D1: Standby pasivo con replicación de estado + lease TTL."""

    def __init__(self):
        self.state_lock = threading.RLock()
        self.stop_replication = False

    def primary_sync(self, state: Dict[str, Any]) -> None:
        """Ejecuta una ciclo de sincronización para nodo primario."""
        try:
            # Primario: replica estado al standby y actualiza lease
            self._write_state(STANDBY_STATE, state)
            self._touch_lease()
        except Exception:
            pass  # Continuar si hay error en sincronización

    def standby_sync(self) -> Optional[Dict[str, Any]]:
        """
        Intenta sincronizar estado para nodo standby.
        Retorna el estado leído o None si hay error.
        """
        try:
            # Standby: lee estado desde standby_state.json
            return self._read_state(STANDBY_STATE, {})
        except Exception:
            return None

    def check_lease_stale(self, max_age: float = 2.0) -> bool:
        """
        Verifica si el lease está vencido (indicando fallo del primario).
        Retorna True si el lease está stale (> max_age segundos).
        """
        try:
            lease_data = json.loads(LEASE_FILE.read_text())
            lease_age = time.time() - lease_data.get("ts", 0)
            return lease_age > max_age
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            return True  # Si no podemos leer el lease, asumimos fallo

    # Métodos de utilidad para operaciones de estado
    def _write_state(self, path: Path, state: Dict[str, Any]) -> None:
        """Escribe estado de forma atómica."""
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)

    def _read_state(self, path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
        """Lee estado con valor por defecto."""
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return json.loads(json.dumps(default))

    def _touch_lease(self) -> None:
        """Actualiza el timestamp del lease (indicando que el primario está vivo)."""
        self._write_state(LEASE_FILE, {"ts": time.time(), "pid": os.getpid()})


@dataclass(order=True)
class WorkItem:
    """Elemento de trabajo para la cola de prioridad (táctica P1)."""
    priority: int
    seq: int
    kind: str = field(compare=False)
    fn: Callable[[], Tuple[int, Dict[str, Any]]] = field(compare=False)
    received_ms: float = field(compare=False)
    done: threading.Event = field(compare=False, default_factory=threading.Event)
    result: Tuple[int, Dict[str, Any]] | None = field(compare=False, default=None)


class PriorityEngine:
    """Táctica P1: Prioriza validaciones frente a eventos secundarios."""

    def __init__(self, enabled: bool, workers: int | None = None) -> None:
        self.enabled = enabled
        self.queue: PriorityQueue[WorkItem] = PriorityQueue()
        self.seq = 0
        self.seq_lock = threading.Lock()
        self.stop = False
        self.metrics_lock = threading.Lock()
        self.latencies: list[float] = []
        worker_count = workers or 128
        self.workers: list[threading.Thread] = []

        for _ in range(worker_count):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            self.workers.append(t)

    def submit_and_wait(self, kind: str, fn: Callable[[], Tuple[int, Dict[str, Any]]],
                       priority: int) -> Tuple[int, Dict[str, Any]]:
        """Envía trabajo a la cola y espera el resultado."""
        received_ms = time.time() * 1000

        with self.seq_lock:
            self.seq += 1
            seq = self.seq

        effective_priority = priority if self.enabled else seq
        item = WorkItem(effective_priority, seq, kind, fn, received_ms)
        self.queue.put(item)
        item.done.wait(timeout=5)

        if item.result is None:
            return HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "reason": "cola_timeout"}

        status, body = item.result
        body["queue_latency_ms"] = (time.time() * 1000) - received_ms
        return status, body

    def _worker(self) -> None:
        """Worker que procesa elementos de la cola de prioridad."""
        while not self.stop:
            try:
                item = self.queue.get(timeout=0.2)
            except Empty:
                continue

            try:
                item.result = item.fn()
            except Exception as exc:
                item.result = (HTTPStatus.INTERNAL_SERVER_ERROR,
                             {"ok": False, "error": str(exc)})
            finally:
                with self.metrics_lock:
                    self.latencies.append((time.time() * 1000) - item.received_ms)
                item.done.set()
                self.queue.task_done()

    def stats(self) -> Dict[str, float]:
        """Retorna estadísticas de latencia (p95, p99)."""
        with self.metrics_lock:
            vals = sorted(self.latencies)

        if not vals:
            return {"count": 0.0, "p95": 0.0, "p99": 0.0}

        def pct(p: float) -> float:
            idx = min(len(vals) - 1, int(round((p / 100) * (len(vals) - 1))))
            return vals[idx]

        return {"count": float(len(vals)), "p95": pct(95), "p99": pct(99)}


# ============ CLASE PRINCIPAL REFACTORIZADA ============

class App:
    """Aplicación principal que orquesta las tres tácticas (S2, P1, D1)."""

    def __init__(self, role: str = "primary", port: int = 5101,
                 security: bool = True, priority: bool = True):
        self.role = role
        self.port = port
        self.security_enabled = security
        self.priority_enabled = priority

        # Inicializar managers especializados
        self.security_manager = SecurityManager() if security else None
        self.replication_manager = ReplicationManager()
        self.priority_engine = PriorityEngine(priority, workers=16)

        # Estado de la aplicación
        self.state = {"version": 1, "cards": dict(INITIAL_CARDS)}
        self.state_lock = threading.RLock()

        # Inicializar estado persistente
        self._initialize_state()

        # Iniciar hilo de replicación
        self.sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.sync_thread.start()

    def _initialize_state(self) -> None:
        """Inicializa los archivos de estado si no existen."""
        if not PRIMARY_STATE.exists():
            self._write_state(PRIMARY_STATE, self.state)
        if not STANDBY_STATE.exists():
            self._write_state(STANDBY_STATE, self.state)
        if not LEASE_FILE.exists():
            self._touch_lease()

    def _write_state(self, path: Path, state: Dict[str, Any]) -> None:
        """Escribe estado de forma atómica."""
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)

    def _read_state(self, path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
        """Lee estado con valor por defecto."""
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return json.loads(json.dumps(default))

    def _touch_lease(self) -> None:
        """Actualiza el timestamp del lease (indicando que el primario está vivo)."""
        self._write_state(LEASE_FILE, {"ts": time.time(), "pid": os.getpid()})

    def _sync_loop(self) -> None:
        """Bucle principal de replicación D1 (standby pasivo)."""
        while not self.replication_manager.stop_replication:
            try:
                if self.role == "primary":
                    # Primario: replica estado al standby y actualiza lease
                    with self.state_lock:
                        snapshot = json.loads(json.dumps(self.state))
                    self.replication_manager.primary_sync(snapshot)
                else:
                    # Standby: sincroniza estado desde standby_state.json
                    standby_state = self.replication_manager.standby_sync()
                    if standby_state is not None:
                        with self.state_lock:
                            self.state = standby_state
                time.sleep(0.2)
            except Exception:
                # En caso de error, continuamos el bucle para evitar bloqueo
                pass

    # ============ MÉTODOS DE NEGOCIO (EXPUESTOS VIA HTTP) ============

    def balance(self, token: str, card: str, secure: bool = True) -> Tuple[int, Dict[str, Any]]:
        """
        Método para el endpoint /balance.
        Implementa táctica S2 si secure=True.
        """
        t0 = time.time() * 1000

        if secure and self.security_manager:
            allowed, user, reason = self.security_manager.check_security(token, card)
            if not allowed:
                return HTTPStatus.FORBIDDEN, {
                    "ok": False, "reason": reason, "latency_ms": (time.time() * 1000) - t0
                }
        else:
            user = TOKENS.get(token, "baseline")

        with self.state_lock:
            card_data = self.state.get("cards", {}).get(card)
            if not card_data:
                return HTTPStatus.NOT_FOUND, {
                    "ok": False, "reason": "tarjeta_no_existe"
                }
            balance = int(card_data["balance"])

        return HTTPStatus.OK, {
            "ok": True, "user": user, "card": card,
            "balance": balance, "latency_ms": (time.time() * 1000) - t0
        }

    def validate(self, token: str, card: str, fare: int, secure: bool = True) -> Tuple[int, Dict[str, Any]]:
        """
        Método para el endpoint /validate.
        Usa táctica P1 (priorización) y opcionalmente S2.
        """
        # Simular costo pequeño de acceso a política/tarifa
        if secure and self.security_manager:
            status, payload = self.balance(token, card, secure=True)
            if status != HTTPStatus.OK:
                return status, payload
        else:
            status, payload = self.balance(token, card, secure=False)
            if status != HTTPStatus.OK:
                return status, payload

        time.sleep(0.002)  # Simular acceso a política/tarifa

        if self.role == "standby":
            return HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "reason": "standby_pasivo"}

        with self.state_lock:
            data = self.state["cards"][card]
            if fare > 0:
                if data["balance"] < fare:
                    return HTTPStatus.PAYMENT_REQUIRED, {"ok": False, "reason": "saldo_insuficiente"}
                data["balance"] -= fare
                self.state["version"] = int(self.state.get("version", 0)) + 1
                self._write_state(PRIMARY_STATE, self.state)

        return HTTPStatus.OK, {
            "ok": True, "card": card, "fare": fare, "balance": data["balance"]
        }

    def summary(self) -> Tuple[int, Dict[str, Any]]:
        """
        Método para el endpoint /summary.
        Táctica secundaria para demostrar priorización P1.
        """
        time.sleep(0.030)  # Trabajo deliberadamente secundario
        return HTTPStatus.OK, {"ok": True, "summary": "queued_processed"}

    def stats(self) -> Dict[str, Any]:
        """Retorna estadísticas del servidor incluyendo información de lease y P1."""
        try:
            lease_age = max(0.0, time.time() -
                          self._read_state(LEASE_FILE, {"ts": 0}).get("ts", 0))
        except Exception:
            lease_age = 999.0

        return {
            "role": self.role,
            "port": self.port,
            "lease_age_s": lease_age,
            "engine": self.priority_engine.stats(),
            "priority_enabled": self.priority_enabled
        }

    def stop(self) -> None:
        """Detiene todos los componentes y hilos."""
        self.replication_manager.stop_replication = True
        self.priority_engine.stop = True
        if hasattr(self, 'sync_thread') and self.sync_thread.is_alive():
            self.sync_thread.join(timeout=2.0)


# ============ MANEJADOR HTTP ============

class Handler(BaseHTTPRequestHandler):
    server_version = "RECAUDO-T/2.0"

    def _json(self, status: int, body: Dict[str, Any]) -> None:
        """Envía respuesta JSON."""
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> Dict[str, Any]:
        """Extrae y decodifica el body JSON de la request."""
        n = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def do_GET(self) -> None:
        app: App = self.server.app  # type: ignore[attr-defined]
        if self.path == "/health":
            self._json(200, {"ok": True, **app.stats()})
            return
        if self.path == "/stats":
            self._json(200, app.stats())
            return
        self._json(404, {"ok": False})

    def do_POST(self) -> None:
        try:
            app: App = self.server.app  # type: ignore[attr-defined]
            data = self._body()

            # Handle HTTP POST requests for various endpoints
            if self.path == "/balance":
                secure = data.get("mode", "secure") != "baseline"
                status, body = app.balance(
                    str(data.get("token", "")),
                    str(data.get("card", "")),
                    secure
                )
                self._json(status, body)
                return

            if self.path == "/validate":
                secure = data.get("mode", "secure") != "baseline"
                status, body = app.priority_engine.submit_and_wait(
                    "validate",
                    lambda: app.validate(
                        str(data.get("token", "")),
                        str(data.get("card", "")),
                        int(data.get("fare", 0)),
                        secure
                    ),
                    priority=0
                )
                self._json(status, body)
                return

            if self.path == "/summary":
                status, body = app.priority_engine.submit_and_wait(
                    "summary",
                    app.summary,
                    priority=10
                )
                self._json(status, body)
                return

            self._json(404, {"ok": False})

        except Exception as exc:
            self._json(500, {"ok": False, "error": str(exc)})

    def log_message(self, fmt: str, *args: Any) -> None:
        """Suprime logs de acceso HTTP."""
        return

# ============ FUNCIÓN DE INICIO DEL SERVIDOR ============

def serve(role: str, port: int, security: bool, priority: bool) -> None:
    """Inicia el servidor HTTP con la configuración especificada."""
    app = App(role=role, port=port, security=security, priority=priority)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.app = app  # type: ignore[attr-defined]

    print(json.dumps({
        "event": "server_started",
        "role": role,
        "port": port,
        "security": security,
        "priority": priority
    }), flush=True)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
        httpd.server_close()

# ============ PUNTO DE ENTRADA PRINCIPAL ============

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["primary", "standby"], default="primary")
    parser.add_argument("--port", type=int, default=5101)
    parser.add_argument("--security", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--priority", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    serve(args.role, args.port, args.security, args.priority)
