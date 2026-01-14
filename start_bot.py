#!/usr/bin/env python3
"""
Script de inicio rápido para el bot de arbitraje
Verifica la configuración antes de iniciar
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

print("=" * 80)
print("INICIANDO BOT DE ARBITRAJE KALSHI-POLYMARKET")
print("=" * 80)
print()

# Verificación rápida
print("Verificando configuración...")

required = [
    "POLYMARKET_PRIVATE_KEY",
    "POLYMARKET_API_KEY",
    "POLYMARKET_SAFE_ADDRESS",
    "KALSHI_API_KEY"
]

missing = []
for var in required:
    if not os.getenv(var):
        missing.append(var)

if missing:
    print()
    print("ERROR: Faltan variables de entorno:")
    for var in missing:
        print(f"  - {var}")
    print()
    print("Ejecuta primero: python verify_bot_config.py")
    sys.exit(1)

print("  OK - Variables de entorno configuradas")
print()

# Verificar archivos principales
files = ["main.py", "market_data.py", "config.json", ".env"]
for file in files:
    if not os.path.exists(file):
        print(f"ERROR: Archivo no encontrado: {file}")
        sys.exit(1)

print("  OK - Archivos principales encontrados")
print()

print("-" * 80)
print()
print("Configuración verificada. Iniciando bot...")
print()
print("-" * 80)
print()

# Importar y ejecutar el bot
try:
    import main
except KeyboardInterrupt:
    print()
    print()
    print("=" * 80)
    print("Bot detenido por el usuario (Ctrl+C)")
    print("=" * 80)
    sys.exit(0)
except Exception as e:
    print()
    print()
    print("=" * 80)
    print(f"ERROR al ejecutar el bot: {e}")
    print("=" * 80)
    import traceback
    traceback.print_exc()
    sys.exit(1)
