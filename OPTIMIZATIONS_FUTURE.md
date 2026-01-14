# 🚀 Optimizaciones Futuras - Latency Reduction Roadmap

**Fecha**: 2026-01-13
**Estado actual**: ~2-3s latency por trade
**Objetivo**: <1s latency por trade

---

## 🔴 ALTA PRIORIDAD (100-300ms savings)

### **Opt #13: Mover DB writes fuera del hot path**
**Ahorro esperado**: 50-100ms
**Complejidad**: Baja
**Ubicación**: `bot.py:282` (register_market_pair)

**Problema**:
```python
# Llamado en CADA WebSocket update (100s por minuto)
pair_id = self.db_manager.register_market_pair(...)  # SYNC DB write ~50-100ms
```

**Solución**:
```python
# Solo registrar en DB cuando detectamos arbitrage
if opp:
    pair_id = self.db_manager.register_market_pair(...)
else:
    pair_id = None  # No DB write en hot path
```

**Implementación**:
1. Mover `register_market_pair()` dentro del `if opp:` block
2. Pasar `None` si no hay arbitrage
3. DB write solo cuando trade es ejecutado

**Impacto**:
- Elimina 50-100ms de CADA update
- Solo penaliza cuando hay trade real (acceptable)
- Reduce DB contention en ~99%

---

### **Opt #14: Async background rediscovery**
**Ahorro esperado**: 200-300ms
**Complejidad**: Muy baja
**Ubicación**: `bot.py:367` (await rediscover_and_subscribe)

**Problema**:
```python
# Bloquea hasta completar rediscovery (~200-300ms)
await self.rediscover_and_subscribe()
```

**Solución**:
```python
# Fire and forget - no bloquea
asyncio.create_task(self.rediscover_and_subscribe())
logger.info("Market rediscovery started in background")
```

**Impacto**:
- No bloquea el siguiente arbitrage check
- Mercados se suscriben eventualmente (acceptable delay)
- Reduce latency post-trade en 200-300ms

---

### **Opt #15: Aggressive market orders para high-confidence arb**
**Ahorro esperado**: 1-2s
**Complejidad**: Media
**Ubicación**: `execution.py:410-411` (place_order calls)

**Problema**:
```python
# Limit orders pueden tardar en fill
self.p_feed.place_order(..., price=p_price)  # Limit order
```

**Solución**:
```python
# Para arbitrage >2% profit, usar market orders
if opp.profit_potential > 0.02:
    # Market order = instant fill (usa best available price)
    use_market_order = True
    # Adjust price slightly para garantizar fill
    p_price = p_price * 1.005  # 0.5% slippage tolerance
    k_price = k_price * 1.005
```

**Trade-offs**:
- ✅ Fill instantáneo (~100ms vs ~2-4s)
- ❌ Slightly worse execution price (0.3-0.5%)
- **Net**: Vale la pena para high-confidence arb (>2%)

**Implementación**:
1. Añadir config: `use_market_orders_threshold = 0.02`
2. Si profit > threshold, ajustar prices aggressively
3. Log cuando se usa market order

---

## 🟡 MEDIA PRIORIDAD (10-100ms savings)

### **Opt #16: Quick pre-filter antes de arbitrage calc**
**Ahorro esperado**: 3-5ms per update
**Complejidad**: Muy baja
**Ubicación**: `bot.py:288` o `arbitrage_engine.py:31`

**Problema**:
```python
# Calcula arbitrage incluso cuando es obviamente imposible
opp = self.detector.check_hard_arbitrage(ke, pe, pair_id)
```

**Solución**:
```python
# Quick reject si sum de prices > threshold
total_cost = ke.yes_price + pe.no_price  # Best case scenario
if total_cost > 0.95:  # Con fees, imposible profit
    return None  # Skip expensive calculation

# Solo calcular si hay chance razonable
opp = self.detector.check_hard_arbitrage(ke, pe, pair_id)
```

**Impacto**:
- Rechaza ~80-90% de updates inmediatamente
- Ahorra ~3-5ms por update rechazado
- Acumulado: ~300-450ms por segundo de updates

---

### **Opt #17: Cache arbitrage calculations por 100ms**
**Ahorro esperado**: 2-3ms per duplicate check
**Complejidad**: Baja
**Ubicación**: `arbitrage_engine.py:31`

**Problema**:
```python
# Recalcula arbitrage en cada WebSocket update
# Incluso si prices apenas cambiaron
```

**Solución**:
```python
# Cache resultado por 100ms si prices casi iguales
cache_key = f"{k_event.ticker}:{p_event.ticker}:{k_event.yes_price:.3f}:{p_event.yes_price:.3f}"
cached = self.arb_cache.get(cache_key)
if cached and (time.time() - cached['timestamp']) < 0.1:
    return cached['result']
```

**Trade-off**:
- Puede miss opportunity si price cambia levemente
- Acceptable para updates dentro de 100ms window

---

### **Opt #18: Pre-compute common calculations**
**Ahorro esperado**: 1-2ms
**Complejidad**: Muy baja
**Ubicación**: `arbitrage_engine.py:50-80`

**Solución**:
```python
# Pre-compute valores que no cambian
class ArbitrageDetector:
    def __init__(self, ...):
        # Pre-compute threshold
        self.total_cost_threshold = 1.0 - self.fee_poly - (0.5 * self.fee_kalshi)
```

---

## 🟢 BAJA PRIORIDAD (1-10ms savings)

### **Opt #19: Reduce logging overhead**
**Ahorro esperado**: 1-3ms per trade
**Solución**:
- Use `logger.debug()` para mensajes verbose
- Solo `logger.info()` para eventos importantes
- Async logging buffer

---

### **Opt #20: Optimize dataclasses serialization**
**Ahorro esperado**: 2-5ms
**Solución**:
- Pre-serialize solo campos necesarios
- Avoid `dataclasses.asdict()` en hot path

---

## 📊 IMPACTO TOTAL ESPERADO

| Fase | Optimizaciones | Ahorro Total | Nueva Latency |
|------|----------------|--------------|---------------|
| **Actual** | Opt #1-8 | - | ~2-3s |
| **+ Alta Prioridad** | Opt #13-15 | 1.3-2.4s | **~700ms-1.7s** 🚀 |
| **+ Media Prioridad** | Opt #16-18 | 50-150ms | **~550ms-1.5s** 🚀🚀 |
| **+ Baja Prioridad** | Opt #19-20 | 10-30ms | **~500ms-1.5s** 🚀🚀🚀 |

**Objetivo alcanzable**: **<1s latency** con todas las optimizaciones

---

## 🎯 ROADMAP RECOMENDADO

### **Sprint 1** (1 día):
- ✅ Opt #13: Mover DB writes (50-100ms)
- ✅ Opt #14: Async rediscovery (200-300ms)
- ✅ Opt #16: Quick pre-filter (3-5ms/update)

**Ganancia**: ~300-500ms | **Esfuerzo**: Bajo

### **Sprint 2** (2-3 días):
- ✅ Opt #15: Market orders para high-confidence (1-2s)
- ✅ Opt #17: Cache arbitrage calcs (2-3ms)

**Ganancia**: ~1-2s | **Esfuerzo**: Medio

### **Sprint 3** (1-2 días):
- ✅ Opt #6: Event-driven fills via WebSocket (1-3s)
  - Requiere WebSocket order update streams
  - Complejidad alta pero high impact

**Ganancia**: ~1-3s | **Esfuerzo**: Alto

---

## ⚠️ TRADE-OFFS A CONSIDERAR

1. **Market orders vs Limit orders**:
   - ✅ Pro: Instant fill (~100ms vs ~2s)
   - ❌ Con: Worse price (~0.3-0.5%)
   - **Decisión**: Usar solo para arb >2% profit

2. **Async rediscovery**:
   - ✅ Pro: No bloquea (~200ms saved)
   - ⚠️ Con: Puede miss next market momentarily
   - **Decisión**: Acceptable (markets last 15min)

3. **Quick pre-filter**:
   - ✅ Pro: Rechaza rápido (~3-5ms saved)
   - ⚠️ Con: Puede miss edge cases
   - **Decisión**: Use conservative threshold (0.95)

---

## 🧪 TESTING REQUIRED

Para cada optimización:
1. ✅ **Backtesting**: Simular con historical data
2. ✅ **Paper trading**: 48 horas antes de live
3. ✅ **Metrics**: Track latency, profit impact, false negatives
4. ✅ **Rollback plan**: Feature flags para disable si issues

---

**Última actualización**: 2026-01-13
**Próxima revisión**: Tras Sprint 1 completion
