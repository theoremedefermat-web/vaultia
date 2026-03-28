"""
db/database.py — Toutes les interactions Supabase
"""

import os
from supabase import create_client, Client
from datetime import datetime, timedelta
from typing import Optional

_client: Optional[Client] = None

def get_db() -> Client:
    global _client
    if _client is None:
        _client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    return _client


# ==================== USERS ====================

def get_user(telegram_id: int) -> Optional[dict]:
    try:
        res = get_db().table("users").select("*").eq("telegram_id", telegram_id).single().execute()
        return res.data
    except:
        return None

def create_user(telegram_id: int, username: str, full_name: str, role: str) -> dict:
    user = {
        "telegram_id": telegram_id,
        "username": username or "",
        "full_name": full_name,
        "role": role,
        "balance": 0,
        "total_sent": 0,
        "total_received": 0,
        "created_at": datetime.utcnow().isoformat()
    }
    res = get_db().table("users").insert(user).execute()
    return res.data[0]

def get_or_create_user(telegram_id: int, username: str, full_name: str, role: str = None) -> dict:
    user = get_user(telegram_id)
    if user:
        return user
    # Le rôle n'est plus stocké — c'est une décision de session
    return create_user(telegram_id, username, full_name, role or "")

def update_balance(telegram_id: int, delta: int):
    user = get_user(telegram_id)
    if user:
        get_db().table("users").update({
            "balance": user["balance"] + delta
        }).eq("telegram_id", telegram_id).execute()

def get_balance(telegram_id: int) -> int:
    user = get_user(telegram_id)
    return user["balance"] if user else 0


# ==================== ESCROW REQUESTS ====================

def create_escrow(
    client_id: int, client_name: str,
    seller_telegram: str,  # username ou phone de la vendeuse
    description: str,
    amount: int,
    pay_method: str,
    pay_phone: str,
    expires_hours: int = 24
) -> dict:
    """Crée une demande d'escrow en statut 'pending_payment'"""
    db = get_db()
    fee = int(amount * 0.10)          # 10% commission Vaultia
    seller_amount = amount - fee       # 90% pour la vendeuse

    escrow = {
        "client_telegram_id": client_id,
        "client_name": client_name,
        "seller_telegram": seller_telegram,   # identifiant vendeuse (username TG)
        "seller_telegram_id": None,           # rempli quand elle accepte
        "description": description,
        "amount": amount,
        "fee": fee,
        "seller_amount": seller_amount,
        "pay_method": pay_method,
        "pay_phone": pay_phone,
        "status": "pending_payment",
        "notchpay_ref": "",
        "expires_at": (datetime.utcnow() + timedelta(hours=expires_hours)).isoformat(),
        "created_at": datetime.utcnow().isoformat()
    }
    res = db.table("escrows").insert(escrow).execute()
    return res.data[0]

def get_escrow(escrow_id: str) -> Optional[dict]:
    try:
        res = get_db().table("escrows").select("*").eq("id", escrow_id).single().execute()
        return res.data
    except:
        return None

def update_escrow(escrow_id: str, updates: dict):
    get_db().table("escrows").update(updates).eq("id", escrow_id).execute()

def get_client_escrows(client_id: int) -> list:
    res = (get_db().table("escrows")
           .select("*")
           .eq("client_telegram_id", client_id)
           .order("created_at", desc=True)
           .limit(10)
           .execute())
    return res.data or []

def get_seller_escrows(seller_id: int) -> list:
    res = (get_db().table("escrows")
           .select("*")
           .eq("seller_telegram_id", seller_id)
           .order("created_at", desc=True)
           .limit(10)
           .execute())
    return res.data or []

def get_pending_for_seller(seller_username: str) -> list:
    """Demandes en attente d'acceptation pour une vendeuse"""
    res = (get_db().table("escrows")
           .select("*")
           .eq("seller_telegram", seller_username)
           .eq("status", "funded")
           .execute())
    return res.data or []


# ==================== TRANSITIONS D'ÉTAT ====================

ESCROW_STATES = {
    "pending_payment": "⏳ En attente de paiement",
    "funded":          "💰 Fonds sécurisés — en attente de la vendeuse",
    "accepted":        "✅ Acceptée — service en cours",
    "delivered":       "📦 Livré — en attente de confirmation client",
    "completed":       "🎉 Terminé — fonds libérés",
    "disputed":        "⚠️ En litige",
    "refunded":        "↩️ Remboursé",
    "expired":         "❌ Expiré"
}

def mark_funded(escrow_id: str, notchpay_ref: str):
    """Paiement reçu — fonds sécurisés"""
    update_escrow(escrow_id, {
        "status": "funded",
        "notchpay_ref": notchpay_ref,
        "funded_at": datetime.utcnow().isoformat()
    })

def mark_accepted(escrow_id: str, seller_id: int):
    """Vendeuse accepte la demande"""
    update_escrow(escrow_id, {
        "status": "accepted",
        "seller_telegram_id": seller_id,
        "accepted_at": datetime.utcnow().isoformat()
    })

def mark_delivered(escrow_id: str):
    """Vendeuse signale qu'elle a livré"""
    update_escrow(escrow_id, {
        "status": "delivered",
        "delivered_at": datetime.utcnow().isoformat()
    })

def mark_completed(escrow_id: str):
    """Client confirme — on libère les fonds"""
    escrow = get_escrow(escrow_id)
    if not escrow:
        return
    # Créditer la vendeuse
    if escrow["seller_telegram_id"]:
        update_balance(escrow["seller_telegram_id"], escrow["seller_amount"])
    update_escrow(escrow_id, {
        "status": "completed",
        "completed_at": datetime.utcnow().isoformat()
    })

def mark_disputed(escrow_id: str, reason: str = ""):
    update_escrow(escrow_id, {
        "status": "disputed",
        "dispute_reason": reason,
        "disputed_at": datetime.utcnow().isoformat()
    })

def mark_refunded(escrow_id: str):
    """Remboursement client — litige résolu en faveur du client"""
    update_escrow(escrow_id, {
        "status": "refunded",
        "refunded_at": datetime.utcnow().isoformat()
    })


# ==================== WITHDRAWALS ====================

def create_withdrawal(seller_id: int, amount: int, phone: str, method: str) -> dict:
    update_balance(seller_id, -amount)
    w = {
        "seller_telegram_id": seller_id,
        "amount": amount,
        "payment_phone": phone,
        "payment_method": method,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat()
    }
    res = get_db().table("withdrawals").insert(w).execute()
    return res.data[0]

def get_withdrawals(seller_id: int) -> list:
    res = (get_db().table("withdrawals")
           .select("*")
           .eq("seller_telegram_id", seller_id)
           .order("created_at", desc=True)
           .limit(5)
           .execute())
    return res.data or []
