"""
Verificar que los límites de riesgo están correctamente configurados
"""
import json

print("=" * 80)
print("VERIFICACION DE LIMITES DE RIESGO")
print("=" * 80)
print()

# Leer configuración
with open("config.json", "r") as f:
    config = json.load(f)

# Balance actual (ejemplo)
balance_actual = 10.99  # USDC

# Obtener límites
max_risk_per_trade = config.get("max_risk_per_trade", 0)
max_daily_loss = config.get("max_daily_loss", 0)
max_net_exposure = config.get("max_net_exposure", 0)

print("CONFIGURACION ACTUAL:")
print("-" * 80)
print(f"Balance disponible:    ${balance_actual:.2f} USDC")
print(f"max_risk_per_trade:    {max_risk_per_trade * 100:.0f}%")
print(f"max_daily_loss:        {max_daily_loss * 100:.0f}%")
print(f"max_net_exposure:      {max_net_exposure * 100:.0f}%")
print()

print("LIMITES CALCULADOS:")
print("-" * 80)

# Calcular límites en dólares
max_trade_total = balance_actual * max_risk_per_trade
max_loss_usd = balance_actual * max_daily_loss
max_exposure_usd = balance_actual * max_net_exposure

print(f"Max por trade (TOTAL ambas legs): ${max_trade_total:.2f}")
print(f"Max perdida diaria:                ${max_loss_usd:.2f}")
print(f"Max exposicion neta:               ${max_exposure_usd:.2f}")
print()

# Ejemplos de trades
print("EJEMPLOS DE TRADES:")
print("-" * 80)

ejemplos = [
    {"k_price": 0.30, "p_price": 0.25},
    {"k_price": 0.45, "p_price": 0.50},
    {"k_price": 0.60, "p_price": 0.35},
]

for i, ej in enumerate(ejemplos, 1):
    k_price = ej["k_price"]
    p_price = ej["p_price"]
    total_price = k_price + p_price

    # Calcular contratos permitidos
    count = int(max_trade_total / total_price) if total_price > 0 else 0

    # Costos
    cost_k = count * k_price
    cost_p = count * p_price
    total_cost = cost_k + cost_p

    print(f"Ejemplo {i}:")
    print(f"  Precios: K=${k_price:.2f}, P=${p_price:.2f} (Total: ${total_price:.2f}/contrato)")
    print(f"  Contratos permitidos: {count}")
    print(f"  Costo Kalshi:  ${cost_k:.2f}")
    print(f"  Costo Poly:    ${cost_p:.2f}")
    print(f"  Costo TOTAL:   ${total_cost:.2f}")

    if total_cost <= max_trade_total:
        print(f"  Estado: OK (dentro del limite de ${max_trade_total:.2f})")
    else:
        print(f"  Estado: EXCEDE el limite!")

    print()

print("=" * 80)
print("VERIFICACION COMPLETADA")
print("=" * 80)
print()

if max_risk_per_trade == 0.10:
    print("OK - Limite configurado al 10% del balance total")
    print(f"Con ${balance_actual:.2f} balance, el maximo por trade (ambas legs) es ${max_trade_total:.2f}")
    print()
    print("Esto significa que si tienes:")
    print(f"  - Balance: ${balance_actual:.2f}")
    print(f"  - Cada trade NO puede exceder: ${max_trade_total:.2f} TOTAL")
    print(f"  - Kalshi leg + Poly leg <= ${max_trade_total:.2f}")
else:
    print(f"ADVERTENCIA - Limite configurado al {max_risk_per_trade * 100:.0f}%")
    print("Se recomienda usar 0.10 (10%) para seguridad")

print()
print("=" * 80)
