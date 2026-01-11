Actúa como un ingeniero cuantitativo senior especializado en:
- trading algorítmico
- mercados de predicción (Kalshi y Polymarket)
- arbitraje de bajo riesgo
- simulación de ejecución realista

Quiero diseñar un BOT DE ARBITRAJE CRUZADO entre Kalshi y Polymarket,
enfocado en eventos CRYPTO (BTC / ETH) de corto plazo (15 minutos y 1 hora),
priorizando riesgo mínimo y neutralidad direccional.

========================
OBJETIVO DEL SISTEMA
========================
Detectar y explotar discrepancias de precios entre Kalshi y Polymarket
cuando ambos listan eventos equivalentes o altamente comparables,
ejecutando posiciones compensadas en ambos mercados.

========================
REQUISITOS FUNDAMENTALES
========================
1. El bot debe tener DOS MODOS TOTALMENTE SEPARADOS:
   - MODO SIMULACIÓN / BACKTEST (por defecto)
   - MODO REAL (desactivado salvo confirmación explícita)

2. Arquitectura modular y mantenible:
   - EventMatcher (emparejamiento semántico de eventos)
   - MarketDataFeed (orderbooks y precios)
   - ArbitrageDetector (hard, probabilístico y temporal)
   - ExecutionCoordinator (coordinación de órdenes)
   - RiskManager (riesgo cruzado)
   - Simulator (latencia, slippage, fallos)
   - PerformanceAnalyzer (métricas reales)
   - ConfigManager (parámetros externos)

========================
EVENT MATCHING (CRÍTICO)
========================
El bot SOLO puede operar si:
- El evento de Kalshi y Polymarket es semánticamente equivalente
- La hora de resolución coincide exactamente
- La fuente de verificación es compatible
- El resultado final es binario sin ambigüedad

Debe rechazar eventos con:
- Diferencias semánticas ("touch" vs "close")
- Diferencias horarias
- Condiciones vagas o disputables

========================
ESTRATEGIAS DE ARBITRAJE
========================
Implementar y documentar estas estrategias:

1) HARD ARBITRAGE (preferente):
   - Si price(YES_A) + price(NO_B) < 1 - fees
   - Comprar ambos lados
   - Beneficio matemáticamente asegurado

2) PROBABILISTIC ARBITRAGE:
   - Comparar probabilidades implícitas
   - Comprar YES donde esté infravalorado
   - Comprar NO donde esté sobrevalorado
   - Solo si spread > umbral + riesgo

3) TIME-LAG ARBITRAGE:
   - Polymarket reacciona primero al spot
   - Kalshi reacciona más lento
   - Entrar solo durante desalineaciones cortas

========================
MODO SIMULACIÓN (OBLIGATORIO)
========================
El simulador debe:
- Reproducir ambos mercados simultáneamente
- Simular latencia distinta por exchange
- Simular slippage, órdenes parciales y fallos
- Permitir backtesting histórico y paper trading

Debe calcular:
- PnL por trade y acumulado
- Máximo drawdown
- Tiempo medio con exposición neta
- % de ejecuciones incompletas
- Worst-case loss

========================
GESTIÓN DE RIESGO (NO NEGOCIABLE)
========================
- Riesgo máximo por trade (% bankroll)
- Exposición neta máxima permitida
- Límite diario de pérdidas
- Kill-switch automático si:
  - Una orden queda sin cubrir
  - Se rompe la equivalencia del evento
  - Latencia excede el umbral

========================
RESTRICCIONES
========================
- NO asumir ejecución perfecta
- NO operar eventos ambiguos
- NO usar predicciones mágicas
- NO sobreoptimizar parámetros

========================
ENTREGABLES ESPERADOS
========================
1. Arquitectura general del sistema
2. Diseño detallado del simulador
3. Lógica del EventMatcher
4. Ejemplo de estrategia de arbitraje cruzado
5. Ejemplo de ejecución coordinada segura
6. Ejemplo de métricas de performance
7. Recomendaciones para pasar a real

Lenguaje preferido: Python
Código claro, modular y documentado.

Comienza por la arquitectura y avanza paso a paso.
