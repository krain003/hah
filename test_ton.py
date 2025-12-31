from tonsdk.contract.wallet import WalletContract, WalletVersionEnum
from tonsdk.crypto import mnemonic_to_wallet_key

mnemo = "abandon amount liar amount expire adjust cage candy arch gather drum buyer".split()
pub, priv = mnemonic_to_wallet_key(mnemo)

print("\nTrying variant 3 (dict)...")
try:
    # Передача словарем
    w = WalletContract(**{"public_key": pub, "password": "", "version": WalletVersionEnum.v4r2})
    print("Success! Address:", w.address.to_string(True, True, False))
except Exception as e:
    print("Failed:", e)

print("\nTrying variant 4 (nested options)...")
try:
    # Вложенный словарь options (как в некоторых версиях)
    w = WalletContract(options={"public_key": pub, "password": "", "version": WalletVersionEnum.v4r2})
    print("Success! Address:", w.address.to_string(True, True, False))
except Exception as e:
    print("Failed:", e)
    
print("\nTrying variant 5 (no version)...")
try:
    # Без версии (по умолчанию v3r2 или v4r2)
    w = WalletContract(public_key=pub)
    print("Success! Address:", w.address.to_string(True, True, False))
except Exception as e:
    print("Failed:", e)