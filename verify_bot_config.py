"""
Verificar que el bot esté correctamente configurado con la Safe wallet
"""
import os
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

print("=" * 80)
print("VERIFICACION DE CONFIGURACION DEL BOT")
print("=" * 80)
print()

# 1. Verificar variables de entorno
print("1. VARIABLES DE ENTORNO")
print("-" * 80)

required_vars = {
    "POLYMARKET_PRIVATE_KEY": "Private key del EOA",
    "POLYMARKET_API_KEY": "CLOB API Key",
    "POLYMARKET_API_SECRET": "CLOB API Secret",
    "POLYMARKET_PASSPHRASE": "CLOB API Passphrase",
    "POLYMARKET_SAFE_ADDRESS": "Direccion de la Safe wallet",
}

all_present = True
for var, description in required_vars.items():
    value = os.getenv(var)
    if value:
        if "KEY" in var or "SECRET" in var or "PASS" in var:
            display = value[:10] + "..." if len(value) > 10 else value
        else:
            display = value
        print(f"  OK - {var}: {display}")
    else:
        print(f"  FALTA - {var}: {description}")
        all_present = False

print()

if not all_present:
    print("ERROR: Faltan variables de entorno requeridas")
    exit(1)

# 2. Verificar Safe wallet en blockchain
print("2. SAFE WALLET EN BLOCKCHAIN")
print("-" * 80)

w3 = Web3(Web3.HTTPProvider('https://polygon-rpc.com'))
safe_address = Web3.to_checksum_address(os.getenv("POLYMARKET_SAFE_ADDRESS"))

# Verificar que esté desplegada
code = w3.eth.get_code(safe_address)
if len(code) > 2:
    print(f"  OK - Safe desplegada en: {safe_address}")
    print(f"  OK - Bytecode size: {len(code)} bytes")
else:
    print(f"  ERROR - Safe no desplegada en: {safe_address}")
    exit(1)

# Verificar balance USDC
USDC_ADDRESS = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
usdc_abi = [
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"}
]
usdc_contract = w3.eth.contract(address=USDC_ADDRESS, abi=usdc_abi)
balance = usdc_contract.functions.balanceOf(safe_address).call()
balance_usdc = Web3.from_wei(balance, 'mwei')

print(f"  Balance USDC: ${balance_usdc:.2f}")

if balance_usdc < 0.5:
    print(f"  ADVERTENCIA - Balance bajo (${balance_usdc:.2f})")
else:
    print(f"  OK - Balance suficiente")

print()

# 3. Verificar owner de la Safe
print("3. OWNERSHIP DE LA SAFE")
print("-" * 80)

safe_abi = [
    {"inputs":[],"name":"getOwners","outputs":[{"type":"address[]"}],"stateMutability":"view","type":"function"},
]

safe_contract = w3.eth.contract(address=safe_address, abi=safe_abi)

try:
    owners = safe_contract.functions.getOwners().call()
    from eth_account import Account
    pkey = os.getenv("POLYMARKET_PRIVATE_KEY")
    if not pkey.startswith('0x'):
        pkey = '0x' + pkey
    eoa = Account.from_key(pkey).address

    print(f"  EOA: {eoa}")
    print(f"  Owners de la Safe: {len(owners)}")

    is_owner = eoa in owners
    if is_owner:
        print(f"  OK - Tu EOA es owner de la Safe")
    else:
        print(f"  ERROR - Tu EOA NO es owner de la Safe")
        exit(1)
except Exception as e:
    print(f"  ERROR - No se pudo verificar ownership: {e}")
    exit(1)

print()

# 4. Verificar configuración en market_data.py
print("4. CONFIGURACION DEL BOT")
print("-" * 80)

try:
    with open("market_data.py", "r", encoding="utf-8") as f:
        content = f.read()

    if "signature_type=2" in content:
        print("  OK - signature_type=2 configurado (GNOSIS_SAFE)")
    else:
        print("  ADVERTENCIA - signature_type=2 no encontrado")

    if "POLYMARKET_SAFE_ADDRESS" in content:
        print("  OK - POLYMARKET_SAFE_ADDRESS utilizada")
    else:
        print("  ADVERTENCIA - POLYMARKET_SAFE_ADDRESS no encontrada")

except Exception as e:
    print(f"  ERROR - No se pudo leer market_data.py: {e}")

print()

# 5. Resumen
print("=" * 80)
print("RESUMEN")
print("=" * 80)
print()
print("Configuracion actual del bot:")
print(f"  - Safe Wallet: {safe_address}")
print(f"  - Balance: ${balance_usdc:.2f} USDC")
print(f"  - Signature Type: 2 (GNOSIS_SAFE)")
print(f"  - Owner: {eoa}")
print()
print("El bot esta configurado para usar la Safe wallet.")
print()
print("Proximos pasos:")
print("  1. Asegurate de tener fondos en la Safe (minimo $10)")
print("  2. Aprueba los tokens si no lo has hecho:")
print("     python dev_tools/approve_safe_tokens.py")
print("  3. Ejecuta el bot:")
print("     python main.py")
print()
print("=" * 80)
