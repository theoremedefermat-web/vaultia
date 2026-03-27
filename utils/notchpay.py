"""
utils/notchpay.py — Intégration NotchPay
Orange Money + MTN MoMo au Cameroun
Docs : https://developer.notchpay.co
"""

import os
import httpx
from typing import dict

NOTCHPAY_PUBLIC_KEY = os.getenv("NOTCHPAY_PUBLIC_KEY", "")
NOTCHPAY_HASH_KEY = os.getenv("NOTCHPAY_HASH_KEY", "")
WEBHOOK_URL = os.getenv("WEBHOOK_BASE_URL", "")


async def create_payment(escrow_id: str, amount: int,
                          method: str, description: str) -> dict:
    """
    Crée une demande de paiement NotchPay.
    Retourne { success, payment_url, reference }
    """
    if not NOTCHPAY_PUBLIC_KEY:
        # Mode simulation — pas de vraie clé API
        return _simulate_payment(escrow_id, amount)

    headers = {
        "Authorization": NOTCHPAY_PUBLIC_KEY,
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    # Mapping méthode → channel NotchPay
    channel_map = {"orange": "cm.orange", "mtn": "cm.mtn"}

    payload = {
        "amount": amount,
        "currency": "XAF",
        "description": description,
        "reference": escrow_id,
        "callback": f"{WEBHOOK_URL}/webhook/notchpay",
        "channel": channel_map.get(method, "cm.orange")
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.notchpay.co/payments/initialize",
                headers=headers,
                json=payload
            )
            data = resp.json()

            if data.get("code") in (201, "201") or data.get("status") == "Accepted":
                return {
                    "success": True,
                    "payment_url": data.get("authorization_url", ""),
                    "reference": data.get("transaction", {}).get("reference", escrow_id)
                }
            else:
                return _simulate_payment(escrow_id, amount)

    except Exception as e:
        return _simulate_payment(escrow_id, amount)


def _simulate_payment(escrow_id: str, amount: int) -> dict:
    """Mode test — simule un paiement réussi"""
    return {
        "success": False,  # False = déclenche livraison directe dans le handler
        "payment_url": "",
        "reference": f"SIM_{escrow_id[:8]}"
    }


async def verify_payment(reference: str) -> dict:
    """Vérifie le statut d'un paiement"""
    if not NOTCHPAY_PUBLIC_KEY:
        return {"status": "complete", "amount": 0}

    headers = {"Authorization": NOTCHPAY_PUBLIC_KEY}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://api.notchpay.co/payments/{reference}",
                headers=headers
            )
            data = resp.json()
            return {
                "status": data.get("transaction", {}).get("status", "failed"),
                "amount": data.get("transaction", {}).get("amount", 0)
            }
    except:
        return {"status": "failed", "amount": 0}


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Vérifie la signature du webhook NotchPay"""
    import hashlib
    import hmac
    if not NOTCHPAY_HASH_KEY:
        return True  # mode test
    expected = hmac.new(
        NOTCHPAY_HASH_KEY.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
