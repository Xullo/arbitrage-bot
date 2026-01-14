# Arbitrage Bot Dashboard

Dashboard en tiempo real para monitorear el bot de arbitraje Kalshi-Polymarket.

## Características

- **Auto-refresh**: Actualización automática cada 3 segundos
- **Estado del Bot**: Visualización del estado actual (active/monitoring)
- **Métricas en Tiempo Real**:
  - Mercados monitoreados
  - Oportunidades detectadas (24h)
  - Trades ejecutados
  - Inversión total
- **Mercados Activos**: Grid con los mercados actualmente monitoreados (BTC, ETH, SOL)
- **Tabla de Oportunidades**: Historial de oportunidades de arbitraje detectadas
- **Tabla de Trades**: Historial de trades ejecutados con detalles de costos y ganancias
- **Logs en Vivo**: Visualización de logs del bot con niveles de color (INFO, WARNING, ERROR)

## Tecnologías

- **Frontend**: React + Vite
- **Backend**: Flask REST API
- **Styling**: CSS custom con tema oscuro
- **Data Source**: SQLite database + log files

## Instalación

### Prerrequisitos

- Node.js 20.19+ o 22.12+
- Python 3.12+
- Bot de arbitraje instalado y configurado

### Instalación de Dependencias

```bash
# Backend (desde el directorio raíz)
pip install flask flask-cors

# Frontend (desde el directorio dashboard)
cd dashboard
npm install
```

## Uso

### 1. Iniciar el Bot de Arbitraje

Desde el directorio raíz del proyecto:

```bash
python start_bot.py
```

El bot comenzará a monitorear mercados y ejecutar trades.

### 2. Iniciar el API Server

En una nueva terminal, desde el directorio raíz:

```bash
python api_server.py
```

El servidor Flask se iniciará en `http://localhost:5000`.

### 3. Iniciar el Dashboard

En otra terminal, desde el directorio dashboard:

```bash
cd dashboard
npm run dev
```

El dashboard estará disponible en `http://localhost:5173`.

### 4. Acceder al Dashboard

Abre tu navegador en `http://localhost:5173` y verás:

- **Header**: Estado del bot, modo de simulación, última actualización
- **Stats Cards**: 4 tarjetas con métricas principales
- **Mercado Activo**: Destacado si el bot está activamente monitoreando un mercado
- **Grid de Mercados**: Tarjetas con los mercados monitoreados
- **Tabla de Oportunidades**: Últimas 10 oportunidades detectadas
- **Tabla de Trades**: Últimos 10 trades ejecutados
- **Logs**: Últimos 50 logs en tiempo real

## API Endpoints

El API server expone los siguientes endpoints:

### GET `/api/status`
Obtiene el estado actual del bot.

**Response**:
```json
{
  "status": "active",
  "last_update": "2026-01-13 15:40:31",
  "active_market": "KXBTC15M-26JAN131045-45",
  "monitored_pairs": 3,
  "simulation_mode": true,
  "timestamp": "2026-01-13T15:40:31.139000"
}
```

### GET `/api/markets`
Obtiene los mercados actualmente monitoreados.

**Response**:
```json
{
  "markets": [
    {
      "asset": "BTC",
      "kalshi_ticker": "KXBTC15M-26JAN131045-45",
      "poly_ticker": "btc-updown-15m-1768318200",
      "status": "monitoring"
    }
  ],
  "count": 3
}
```

### GET `/api/opportunities`
Obtiene oportunidades de arbitraje detectadas.

**Response**:
```json
{
  "opportunities": [
    {
      "id": 1,
      "type": "HARD",
      "profit": 0.015,
      "strategy": "YES_K_NO_P",
      "kalshi_ticker": "KXBTC15M-...",
      "poly_ticker": "btc-updown-...",
      "title": "Bitcoin Up or Down 15m",
      "detected_at": "2026-01-13 15:40:31"
    }
  ],
  "count": 1
}
```

### GET `/api/trades`
Obtiene trades ejecutados.

**Response**:
```json
{
  "trades": [
    {
      "id": 1,
      "contracts": 1.0,
      "kalshi_cost": 0.45,
      "poly_cost": 0.50,
      "total_cost": 0.95,
      "expected_profit": 0.015,
      "strategy": "YES_K_NO_P",
      "kalshi_ticker": "KXBTC15M-...",
      "poly_ticker": "btc-updown-...",
      "executed_at": "2026-01-13 15:40:31"
    }
  ],
  "count": 1
}
```

### GET `/api/stats`
Obtiene estadísticas agregadas.

**Response**:
```json
{
  "total_trades": 5,
  "total_invested": 4.75,
  "avg_trade_size": 0.95,
  "opportunities_24h": 12,
  "avg_profit_potential": 0.015
}
```

### GET `/api/logs`
Obtiene logs recientes del bot.

**Response**:
```json
{
  "logs": [
    {
      "timestamp": "2026-01-13 15:40:31",
      "level": "INFO",
      "module": "bot.py",
      "message": "WebSocket feeds active. Listening for arbitrage opportunities..."
    }
  ],
  "count": 50
}
```

## Estructura del Proyecto

```
dashboard/
├── src/
│   ├── App.jsx          # Componente principal del dashboard
│   ├── App.css          # Estilos con tema oscuro
│   └── main.jsx         # Entry point de React
├── public/              # Archivos estáticos
├── package.json         # Dependencias de npm
├── vite.config.js       # Configuración de Vite
└── README.md            # Esta documentación
```

## Personalización

### Cambiar Frecuencia de Auto-refresh

En `src/App.jsx`, línea 45:

```javascript
const interval = setInterval(fetchData, 3000)  // 3000ms = 3 segundos
```

### Cambiar Puerto del Dashboard

En `package.json`, modifica el script `dev`:

```json
"dev": "vite --port 5173"
```

### Cambiar Puerto del API Server

En `api_server.py`, línea 323:

```python
app.run(debug=True, host='0.0.0.0', port=5000)
```

Y actualiza `src/App.jsx`, línea 4:

```javascript
const API_URL = 'http://localhost:5000/api'
```

### Personalizar Colores

En `src/App.css`, modifica las variables de color:

```css
/* Background principal */
background: #0f172a;

/* Cards y secciones */
background: #1e293b;

/* Bordes */
border: 1px solid #334155;

/* Color primario (azul) */
color: #3b82f6;

/* Éxito (verde) */
color: #22c55e;

/* Warning (naranja) */
color: #f59e0b;

/* Error (rojo) */
color: #ef4444;
```

## Troubleshooting

### El dashboard no muestra datos

1. Verifica que el API server esté corriendo: `http://localhost:5000/api/status`
2. Verifica que el bot esté corriendo y generando logs
3. Revisa la consola del navegador (F12) para errores de CORS

### Error de CORS

El API server ya tiene CORS habilitado. Si aún ves errores:

```python
# En api_server.py
CORS(app)  # Ya está configurado
```

### El bot no aparece como "active"

El estado se determina leyendo los logs. Verifica:
1. Que el bot esté corriendo
2. Que esté generando logs en `bot_log_YYYYMMDD.log`
3. Que los logs contengan "WebSocket feeds active"

### Node.js version warning

Actualiza Node.js a 20.19+ o 22.12+:

```bash
# Descarga desde https://nodejs.org/
# O usa nvm:
nvm install 20.19
nvm use 20.19
```

## Production Deployment

Para producción, compila el dashboard:

```bash
npm run build
```

Esto generará una carpeta `dist/` con archivos estáticos optimizados.

Sirve los archivos con un servidor web (nginx, apache, etc.) y configura el API server con un WSGI server (gunicorn, uWSGI):

```bash
gunicorn api_server:app -b 0.0.0.0:5000
```

## Licencia

Parte del proyecto Arbitrage Bot Kalshi-Polymarket.
