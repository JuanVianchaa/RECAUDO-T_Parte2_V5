# RECAUDO-T: Sistema de Transacciones con Tácticas de Calidad

## Descripción del Proyecto

RECAUDO-T es una implementación de un sistema de transacciones financieras que demuestra la aplicación de tres tácticas de calidad arquitectural para mejorar seguridad, rendimiento y dependabilidad. Este sistema simula el procesamiento de tarjetas de transporte público con validación de tarifas y gestión de balances.

## Tácticas Implementadas

### S2: Seguridad - Autorización de Actores + Bloqueo por Umbral
- **Autorización**: Verifica que el token pertenece al usuario legítimo de la tarjeta
- **Bloqueo por Umbral**: Después de 10 intentos fallidos en 60 segundos, bloquea temporalmente el token por 60 segundos
- **Auditoría**: Registra todos los intentos de acceso (exitosos y fallidos) en `audit_security.csv`
- **Implementación**: `SecurityManager` en `app/core.py`

### P1: Rendimiento - Priorización de Validaciones
- **Mecanismo**: Cola de prioridad que otorga mayor prioridad (valor 0) a las operaciones de validación frente a eventos secundarios como reportes mensuales (prioridad 10)
- **Objetivo**: Garantizar baja latencia en operaciones críticas incluso bajo carga mixta
- **Implementación**: `PriorityEngine` en `app/core.py` con cola `PriorityQueue` y workers dedicados

### D1: Dependabilidad - Standby Pasivo con Replicación de Estado + Lease TTL
- **Arquitectura**: Nodo primario que replica estado a nodo standby pasivo
- **Mecanismo de Detección**: Lease con TTL (Time-To-Live) de 2 segundos - si el primario no renueva el lease, el standby asume el fallo
- **Recuperación**: El standby toma el último estado replicado y continúa operaciones
- **Implementación**: `ReplicationManager` en `app/core.py`

## Arquitectura del Sistema

```
┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   Cliente HTTP  │───►│   Servidor HTTP  │───►│   Núcleo App     │
│   (requests)    │    │ (ThreadingHTTPServer)│    │                  │
└─────────────────┘    └──────────────────┘    └───────┬──────────┘
                                                       │
                              ┌────────────────────────▼─────────────────────┐
                              │                    App                       │
                              │                                              │
                              │  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐ │
                              │  │SecurityManager│ │PriorityEngine│ │ReplicationManager│ │
                              │  │    (S2)     │ │    (P1)     │ │     (D1)       │ │
                              │  └─────────────┘  └──────────────┘  └────────────────┘ │
                              └───────────────────────────────────────────────────────┘
                                                       │
                              ┌────────────────────────▼─────────────────────┐
                              │              Estado Persistente              │
                              │  • primary_state.json                        │
                              │  • standby_state.json                        │
                              │  • primary_lease.json                        │
                              └───────────────────────────────────────────────┘
```

## Estructura del Proyecto

```
RECAUDO_T_Parte2_V5/
├── app/                        # Código fuente principal (implementación de las tres tácticas)
│   ├── core.py                 # Núcleo del servidor: SecurityManager (S2), PriorityEngine (P1), ReplicationManager (D1)
│   └── client.py               # Cliente HTTP para pruebas manuales y validación
├── debug/                      # Herramientas de diagnóstico y testing (fase de desarrollo y validación)
│   ├── Tests de rendimiento    # Medición de latencia, throughput y escalabilidad
│   ├── Tests de seguridad      # Validación de autorización, bloqueo por umbral y auditoría
│   ├── Tests de concurrencia   # Evaluación bajo carga simultánea y estrés
│   └── Tests de dependabilidad # Verificación de failover y detección de fallos
├── evidence/                   # Resultados empíricos de experimentos y logs de ejecución
│   ├── Resultados experimentales # CSV con métricas de cada escenario (S2, P1, D1)
│   ├── Logs de servidores      # Salida estándar y error durante pruebas (server_*.log)
│   └── Resumen consolidado     # summary_results.json con métricas clave y comparación de configuraciones
├── runtime/                    # Estado temporal durante ejecución del sistema
│   ├── Archivos de estado      # primary_state.json (actual), standby_state.json (réplica)
│   └── Archivo de lease        # primary_lease.json (TTL ≈ 2.0s para detección de fallo del primario)
├── run_practica.py             # Orquestador principal: ejecuta todos los experimentos y genera evidencia
├── README.md                   # Esta guía (actualizado y profesional)
├── IMPROVEMENTS_SUMMARY.md     # Detalle de mejoras realizadas (en español)
├── Informe_RECAUDO-T_Parte2_V5.pdf  # Informe final del proyecto
├── Trabajo_parcial_práctico.pdf  # Enunciado original del trabajo práctico
└── .gitignore                  # Archivos ignorados por control de versiones
```

## Cómo Ejecutar

### Experimento Rápido de Verificación
```bash
python run_practica.py
```
Ejecuta un conjunto reducido de pruebas para verificar funcionalidad básica (≈30 segundos):
- 10 segundos de duración
- 50 requests/second (valor predeterminado de `--rps`)
- Todas las tácticas activas por defecto

### Experimento Completo (Requisito de la Parte 1)
```bash
python run_practica.py --full --rps 500
```
Ejecuta la prueba exigida según la configuración del proyecto:
- **Duración**: 10 minutos (600 segundos, activada por `--full`)
- **Tasa de requests**: 500 requests/second (configurada por `--rps 500`)
- **Total de requests**: 500 req/s × 600 s = **300,000 requests**
- **Validación de requisitos**: Verifica que se cumpla **p95 de validaciones ≤ 300 ms** con seguridad activa

> **Nota**: Los valores de `--full` y `--rps` están definidos en `run_practica.py`. Puede ajustarlos según necesite para diferentes escenarios de prueba.

## Métricas de Rendimiento Esperadas

Tras las optimizaciones implementadas, el sistema cumple con:

- **Latencia p95 ≤ 300 ms** con seguridad activa (táctica S2)
- **Overhead de seguridad ≤ +20%** frente a línea base sin seguridad
- **Detección de failover ≈ 2.0 segundos** (TTL del lease)
- **Cero pérdidas de request** durante transición de failover
- **Ordenamiento correcto por prioridad**: validaciones (prio 0) procesadas antes de eventos secundarios (prio 10)

## Detalles Técnicos de Implementación

### Seguridad (S2)
- Uso de `threading.RLock` para acceso concurrente seguro al estado de seguridad
- Cola asíncrona para escritura de auditoría evitando bloqueos en el camino crítico
- Liminación inteligente del alcance del lock para reducir contención
- Limpieza automática de intentos expirados (ventana de 60 segundos)

### Rendimiento (P1)
- Cola de prioridad basada en `PriorityQueue` de Python
- Workers configurables (predeterminado: 16 tras optimización desde 128)
- Métricas de latencia protegidas por lock separado para minimizar impacto
- Timeout de 5 segundos para evitar esperas indefinitas

### Dependabilidad (D1)
- Escritura atómica de estado usando archivos temporales + `os.replace()`
- Lectura tolerante a fallos con valores por defecto
- Hilo de replicación separado que opera independientemente del manejo de requests
- Detección de fallos basada en expiración de lease (sin tráfico de red continuo)

## Cumplimiento de Requisitos

Este sistema satisface todos los requisitos especificados en la Parte 1 del trabajo práctico:

1. **Tácticas Correctamente Implementadas**:
   - S2: Autorización + bloqueo por umbral (no Ping/Echo)
   - P1: Priorización de validaciones (no caché)
   - D1: Standby pasivo + replicación de estado + lease TTL (no redundancia activa)

2. **Rendimiento**:
   - Latencia p95 por debajo de 300 ms con seguridad activa
   - Overhead de seguridad mantenido bajo el 20% respecto a línea base

3. **Dependabilidad**:
   - Detección automática de fallos del primario
   - Failover sin pérdida de requests
   - Recuperación desde estado replicado consistente

4. **Calidad de Código**:
   - Separación clara de responsabilidades por táctica
   - Manejo adecuado de concurrencia y condiciones de carrera
   - Registro completo de eventos para auditoría y debugging

## Notas Importantes

- Los resultados pueden variar ligeramente según el hardware y carga del sistema
- Los archivos CSV en `evidence/` son la evidencia primaria para el informe
- No se requieren paquetes externos além de la biblioteca estándar de Python 3.11+
- El sistema está diseñado para ejecutarse en localhost (127.0.0.1) para fines académicos
- En los experimentos completos (`--full --rps 500`), se procesan **300,000 requests** en total
- El directorio `debug/` contiene herramientas de desarrollo utilizadas durante la creación y validación del sistema - **no son necesarios para la ejecución en producción**

## Equipo

Implementado como parte del trabajo práctico de Sistemas Distribuidos.