# Lead Qualification Bot

Bot de Telegram para cualificacion de leads usando LLMs de Hugging Face. Actua como una secretaria amable que evalua proyectos, registra resultados en Google Sheets y mantiene historial completo por hilo de conversacion.

Proyecto tecnico para **Orbyn** — empresa de automatizacion e IA.

## Arquitectura

```mermaid
flowchart LR
    User["Usuario Telegram"]
    API["Telegram Bot API"]
    Bot["main.py<br/>bot/handler.py"]
    LLM["qualifier/<br/>prompt.py + client.py"]
    Model["models/lead.py"]
    Sheets["sheets/client.py"]

    User -- mensaje --> API
    API -- polling --> Bot
    Bot --> LLM
    LLM --> Model
    Model --> Sheets
    Bot -- respuesta --> User
```

```mermaid
sequenceDiagram
    actor U as Usuario
    participant B as Bot
    participant L as LLM (HF)
    participant S as Google Sheets

    U->>B: "Me interesa automatizar procesos"
    B->>B: Busca contexto del chat
    B->>L: Envia prompt + historial
    L->>B: {accion: "needs_info", preguntas: [...]}
    B->>S: Append row (conv_id: a1b2)
    B->>U: "Necesito saber... empleados? ubicacion?"

    U->>B: "Somos 15 en Madrid, consultora"
    B->>L: Prompt + historial del hilo
    L->>B: {accion: "qualified"}
    B->>S: Append row (conv_id: a1b2)
    B->>U: "Encajan muy bien! Los contactamos"
```

## Stack Tecnologico

| Capa | Tecnologia |
|------|-----------|
| Bot | `python-telegram-bot` v21 (async, polling) |
| LLM | Hugging Face Chat Completions API (DeepSeek-V3.2) |
| Sheets | `gspread` + Google Service Account |
| Config | `python-dotenv` |
| Python | 3.11+ |

## Como Funciona

### Flujo de Evaluacion

1. El usuario envia datos del lead en texto libre
2. El bot evalua contra el ICP:
   - Empresa que **quiera automatizar** algo (cualquier rubro)
   - Minimo 5 empleados
   - Espana o Latinoamerica
   - Interes en automatizacion/IA
3. El bot determina una de tres acciones:
   - **qualified**: Responde cordial, se gestina el contacto
   - **needs_info**: Pide los datos faltantes de forma natural
   - **disqualified**: Rechazo educado, sin detalles
4. Cada mensaje se loguea como fila nueva en Google Sheets

### Historial por Conversacion

Cada hilo de conversacion tiene un **Conversacion ID** unico. Todas las filas con el mismo ID pertenecen al mismo hilo. Asi se puede filtrar en Sheets y ver la conversacion completa en orden cronologico.

```mermaid
flowchart TD
    subgraph Sheet [Google Sheet]
        H1["Fila 1: conv=abc | needs_info"]
        H2["Fila 2: conv=abc | qualified"]
        H3["Fila 3: conv=def | needs_info"]
        H4["Fila 4: conv=abc | disqualified"]
    end

    T1["Hilo abc: 3 mensajes"] --> H1
    T1 --> H2
    T1 --> H4
    T2["Hilo def: 1 mensaje"] --> H3
```

### Flujo por Mensaje

```mermaid
flowchart TD
    Msg["Mensaje entrante"] --> Ctx["Buscar contexto del chat"]
    Ctx --> HF["Llamar a HF Chat Completions<br/>con historial del hilo"]
    HF --> Parse["Parsear JSON de respuesta"]
    Parse --> Check{"accion?"}

    Check -->|qualified| R1["Reply: 'Encajan bien!'"]
    Check -->|needs_info| R2["Reply: preguntar datos faltantes"]
    Check -->|disqualified| R3["Reply: rechazo educado"]

    Check --> Log["Append row a Google Sheets<br/>(con conversacion ID + tokens)"]
    R1 --> Log
    R2 --> Log
    R3 --> Log

    Log --> Save["Guardar historial en memoria"]
    Save --> Done["Fin"]
```

### Ingenieria de Prompts

El prompt del sistema en `qualifier/prompt.py`:

- **Basado en rol**: El LLM actua como secretaria, no clasificador
- **Salida estructurada**: Fuerza JSON con `accion`, `razonamiento`, `campos_faltantes`, `preguntas`
- **Proteccion anti-injection**: Separacion estricta entre instrucciones sistema y datos usuario; reglas explicitas para ignorar instrucciones embedidas en el input
- **Preferir preguntar**: Ante la duda, pide mas info antes de descartar
- **No descartar por rubro**: Cualquier empresa puede automatizar algo

### Google Sheets

Cada mensaje se loguea como fila individual con:

| # | Columna | Contenido |
|---|---------|-----------|
| A | Fecha | Timestamp ISO del mensaje |
| B | Datos Recibidos | Texto crudo del usuario |
| C | Decision | Cualificado / Faltan datos / No cualificado |
| D | Motivo | Razonamiento interno del LLM |
| E | Campos Faltantes | Criterios que faltaban (si aplica) |
| F | Preguntas | Preguntas hechas al lead (si aplica) |
| G | Conversacion ID | Identificador unico del hilo |
| H | Tokens Input | Tokens de entrada consumidos |
| I | Tokens Output | Tokens de salida generados |
| J | Tokens Total | Formula =H+I (calcula automaticamente) |

Las filas se agregan en orden. Filtrando por **Conversacion ID** se ve el historial completo de cada hilo.

## Estructura del Proyecto

```
lead-qualifier/
  main.py               Punto de entrada — conecta bot, qualifier, sheets
  config.py             Configuracion desde env con validacion
  models/lead.py        Modelo LeadResult (accion, tokens, conv_id)
  qualifier/
    prompt.py           Prompt del sistema con proteccion anti-injection
    client.py           Cliente HF Chat Completions con reintentos
  bot/handler.py        Manejador de mensajes, contexto por chat
  sheets/client.py      Cliente Google Sheets (append + formula)
  .env.example          Variables de entorno requeridas
  requirements.txt      Dependencias Python
```

## Setup

```bash
git clone <repo-url> lead-qualifier
cd lead-qualifier

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Completar con tus tokens en .env
```

Compartir la Google Sheet con el email del service account.

```bash
python main.py
```

## Consideraciones para Produccion

### 1. Defensa contra Prompt Injection
Separacion estricta instrucciones/datos + reglas explicitas en el prompt. En produccion: sanitizar input (control chars, patrones de injection), validar esquema JSON de salida, rate limiting por usuario.

### 2. Gestion de Costos de API
512 tokens max por llamada, temperatura 0.3. En produccion: cache de consultas repetidas, rate limiting por chat, monitoreo de tokens (column H-I en sheet), modelo de respaldo mas economico para filtrado inicial.

### 3. Resiliencia ante Errores
Reintentos con timeout de 30s, logging sin crashear. En produccion: circuit breaker para HF API, cola asincronica para sheet logging, modelo fallback para cuando el principal no responde.
