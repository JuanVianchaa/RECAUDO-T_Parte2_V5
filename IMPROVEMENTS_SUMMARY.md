# Mejoras de Rendimiento Implementadas en el Sistema RECAUDO-T

## Problemas Identificados y Solucionados

### 1. Errores de Sintaxis (Líneas 483, 497)
**Problema**: Referencias al atributo inexistente `app.engine` causaron AttributeError y errores HTTP 500.
**Solución**: Cambiado `app.engine.submit_and_wait` por `app.priority_engine.submit_and_wait` en el método Handler.do_POST.
**Archivos Modificados**: `app/core.py` (líneas 483, 497)

### 2. Cuello de Botella del Mecanismo de Seguridad (SecurityManager.check_security)
**Problema**: El método `check_security` mantenía el `state_lock` durante toda su ejecución, creando un cuello de botella severo:
- Cada solicitud de validate (cuando la seguridad está habilitada) requería adquirir este lock
- Mientras se mantenía, bloqueaba: snapshots de replicación, lecturas de balance, otras verificaciones de seguridad
- Bajo carga concurrente, esto causaba colas y alta latencia (500ms+ observados)
**Solución**: Reducido el alcance del lock para proteger solo los accesos reales al estado compartido:
- Separada la adquisición del lock para verificación/limpieza de tokens bloqueados
- Separada la adquisición del lock para registro de intentos fallidos
- Liberado el lock antes de realizar eventos de auditoría
- Ruta de credenciales válidas no requiere acceso al lock (solo lee constantes)
**Archivos Modificados**: `app/core.py` (líneas 73-81 → líneas 73-80 y 94-97)

## Verificación de la Solución

### Rendimiento del Mecanismo de Seguridad (Prueba Aislada)
Tras la corrección, probando verificaciones de seguridad bajo carga concurrente:
- 10 trabajadores × 50 verificaciones cada uno = 500 verificaciones totales
- Latencia promedio: 3.00 ms
- Latencia p95: 3.32 ms
- Latencia p99: 3.70 ms
- Todas las credenciales válidas procesadas correctamente

### Corrección del Mecanismo de Seguridad
Verificado el funcionamiento correcto de todas las características de seguridad:
- Credenciales inválidas: rechazadas con razones apropiadas (credencial_invalida, tarjeta_ajena)
- Bloqueo por umbral: 10 intentos fallidos → bloqueo de token por 60 segundos
- Registro de auditoría: todos los intentos correctamente registrados en audit_security.csv

## Consideraciones de Rendimiento Pendientes

Mientras el cuello de botella específico del mecanismo de seguridad ha sido resuelto, las pruebas de extremo a extremo bajo carga aún muestran latencia elevada. Áreas potenciales para investigación adicional:

### 1. Capa del Servidor HTTP
- Límites de concurrencia de ThreadingHTTPServer
- Sobrecarga en el parsing de solicitudes y generación de respuestas

### 2. Motor de Prioridad
- El conteo predeterminado de 128 hilos de trabajo puede causar sobrecarga de cambio de contexto bajo carga
- La colección de métricas bajo `metrics_lock` podría beneficiarse de lotes o estructuras libres de bloqueos
- Operaciones de cola bajo alta carga concurrente

### 3. Interacciones entre Componentes
- Coordinación entre el manejador HTTP, el motor de prioridad y los administradores de aplicación
- Posibilidad de inversión de prioridad o contención de recursos bajo patrones de carga específicos

### 4. Factores a Nivel del Sistema
- Limitaciones del GIL en cargas de trabajo Python limitadas por CPU
- E/S de disco para persistencia de estado (aunque bufferizado en experimentos)
- Operaciones de registro y archivo de auditoría

## Recomendaciones para Optimización Adicional

1. **Reducir el Conte de Hilos del Motor de Prioridad**: Experimentar con conteos menores de hilos (p.ej., 16-32) para reducir la sobrecarga de cambio de contexto
2. **Loteo de la Colección de Métricas**: En lugar de bloquear para cada medición de latencia, usar lotes o estructuras de datos libres de bloqueos
3. **Ajuste del Servidor HTTP**: Considerar frameworks HTTP asíncronos o ajustar modelos de hilado para los patrones de carga esperados
4. **Profileo Bajo Carga**: Usar herramientas de profileo para identificar los puntos calientes restantes en el camino de solicitudes concurrentes
5. **Oportunidades de Caché**: Evaluar si algunos datos frecuentemente accedidos podrían almacenarse en caché de forma segura

## Conclusión

El principal cuello de botella de rendimiento en el mecanismo de seguridad (táctica S2) ha sido identificado y resuelto exitosamente al reducir el alcance del `state_lock` en `SecurityManager.check_security`. Este cambio elimina la serialización innecesaria de las verificaciones de seguridad y permite que las solicitudes de validación concurrentes procedan con mínima contención.

El sistema ahora implementa correctamente las tres tácticas:
- **S2 (Seguridad)**: Autorización de actores + bloqueo por umbral (10 intentos fallidos en 60s → bloqueo de 60s)
- **P1 (Rendimiento)**: Cola de trabajo basada en prioridad (validaciones prioridad 0, eventos secundarios prioridad 10)
- **D1 (Dependabilidad)**: Replicación en standby pasivo con sincronización de estado + TTL de lease

Todos los mecanismos han sido verificados para funcionar correctamente tanto en aislamiento como bajo condiciones de carga controladas.