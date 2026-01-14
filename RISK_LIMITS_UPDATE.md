# ✅ Límites de Riesgo Actualizados

## Cambios Realizados

### ❌ Configuración Anterior
- **Límite por trade**: 90% del balance ($9.89 con $10.99 balance)
- **Hard cap**: $2.00 por LEG (permitía hasta $4.00 total!)
- **Problema**: Muy arriesgado, podía usar 36% del balance en un solo trade

### ✅ Nueva Configuración
- **Límite por trade**: **10% del balance total** ($1.10 con $10.99 balance)
- **Sin hard cap**: Se usa solo el porcentaje configurado
- **Aplicación**: El límite es para el TOTAL de ambas legs combinadas

---

## Archivos Modificados

### 1. `config.json`
```json
{
  "max_risk_per_trade": 0.10,  // Cambió de 0.90 a 0.10 (10%)
  ...
}
```

### 2. `risk_manager.py`
```python
def get_max_trade_dollar_amount(self) -> float:
    """
    Returns the max allowed risk per trade in USD.
    This is for TOTAL cost (both legs combined), not per leg.
    With 10% limit and $10.99 balance = $1.10 max total trade.
    """
    calc_risk = self.bankroll * config.risk_config.max_risk_per_trade
    return calc_risk  # Eliminado el hard cap de $2.00
```

### 3. `execution.py`
**Cambio principal**: El cálculo de contratos ahora considera el costo TOTAL:

```python
# ANTES (por leg):
k_limit = int(max_usd_risk / target_k_price)
p_limit = int(max_usd_risk / target_p_price)
count_size = min(k_limit, p_limit)

# AHORA (total combinado):
total_price_per_contract = target_k_price + target_p_price
count_size = int(max_usd_risk_total / total_price_per_contract)
```

---

## Ejemplos Prácticos

### Con Balance de $10.99 USDC

**Límite por trade**: $1.10 (10% de $10.99)

#### Ejemplo 1: Precios bajos
- Kalshi: $0.30
- Polymarket: $0.25
- **Total por contrato**: $0.55
- **Contratos permitidos**: 1 (costo total: $0.55)
- ✅ Dentro del límite

#### Ejemplo 2: Precios medios
- Kalshi: $0.45
- Polymarket: $0.50
- **Total por contrato**: $0.95
- **Contratos permitidos**: 1 (costo total: $0.95)
- ✅ Dentro del límite

#### Ejemplo 3: Precios altos
- Kalshi: $0.60
- Polymarket: $0.55
- **Total por contrato**: $1.15
- **Contratos permitidos**: 0 (excede $1.10)
- ❌ Trade rechazado

---

## Logs Actualizados

Los mensajes de log ahora muestran claramente el límite total:

```
[INFO] Dynamic Sizing: Max Total $1.10. Prices: K=$0.45, P=$0.50 => 1 Contracts.
       (Total Cost: $0.95 = K:$0.45 + P:$0.50)
```

Antes decía:
```
[INFO] Dynamic Sizing (Dual Check): Risk $2.00. Prices: K=$0.45, P=$0.50 => 4 Contracts.
       (Costs: K=$1.80, P=$2.00)  # ¡$3.80 total!
```

---

## Verificación

Ejecuta este comando para verificar los límites:

```bash
python verify_risk_limits.py
```

Debería mostrar:
```
OK - Limite configurado al 10% del balance total
Con $10.99 balance, el maximo por trade (ambas legs) es $1.10
```

---

## Seguridad Mejorada

### Protecciones Actuales:

1. ✅ **Límite por trade**: 10% del balance total
2. ✅ **Límite diario**: Pérdidas no pueden exceder 95% del balance
3. ✅ **Exposición máxima**: 100% del balance en posiciones abiertas
4. ✅ **Verificación doble**: `can_execute()` valida el costo total antes de operar
5. ✅ **Minimum de Polymarket**: Se respeta el mínimo de $1.00 solo si está dentro del límite

### Con Balance de $10.99:
- **Max por trade**: $1.10 (10%)
- **Max pérdida diaria**: $10.44 (95%)
- **Max exposición**: $10.99 (100%)

---

## Ajustar el Límite

Si quieres cambiar el porcentaje, edita `config.json`:

```json
{
  "max_risk_per_trade": 0.05,  // 5% = $0.55 con $10.99 balance
  "max_risk_per_trade": 0.15,  // 15% = $1.65 con $10.99 balance
  "max_risk_per_trade": 0.20,  // 20% = $2.20 con $10.99 balance
}
```

**Recomendado**: Mantener entre 5-10% para seguridad.

---

## ⚠️ Importante

Con el límite del 10%:
- Algunos trades pueden ser rechazados si los precios suman más de $1.10
- Esto es **CORRECTO** - protege tu capital
- Si ves muchos rechazos, considera depositar más fondos en la Safe

---

**Actualizado**: 2026-01-13
**Balance actual**: $10.99 USDC
**Límite por trade**: $1.10 (10% del balance total, ambas legs combinadas)
