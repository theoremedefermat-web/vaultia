"""
handlers/escrow.py — Logique cœur de l'escrow
Flux : création → paiement → notification vendeuse → acceptation → livraison → confirmation → paiement
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode
from db.database import (
    get_user, get_or_create_user, create_escrow, get_escrow,
    get_client_escrows, get_seller_escrows, get_pending_for_seller,
    mark_funded, mark_accepted, mark_delivered,
    mark_completed, mark_disputed, mark_refunded,
    ESCROW_STATES
)
from utils.notchpay import create_payment, verify_payment
import os

# États conversation
REQ_DESC, REQ_AMOUNT, REQ_METHOD, REQ_PHONE, REQ_CONFIRM = range(5)

ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "0"))
COMMISSION = 0.10  # 10%


# ==================== CRÉATION D'UNE DEMANDE ====================

async def new_request_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()

    await query.edit_message_text(
        "➕ *Nouvelle demande escrow*\n\n"
        "Étape 1/5 — Décrivez le service que vous attendez :\n\n"
        "_Ex: Frais de transport pour venue à l'hôtel Hilton Yaoundé ce soir_\n"
        "_Ex: Réservation soirée privée vendredi 22h_\n"
        "_Ex: Envoi de contenu photo pack premium_\n\n"
        "/cancel pour annuler",
        parse_mode="Markdown"
    )
    return REQ_DESC


async def new_request_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    if len(desc) < 10:
        await update.message.reply_text("❌ Description trop courte. Soyez plus précis :")
        return REQ_DESC

    context.user_data["desc"] = desc

    await update.message.reply_text(
        f"✅ *Description enregistrée*\n\n"
        f"Étape 2/5 — Quel montant voulez-vous déposer en garantie ? (XAF)\n\n"
        f"💡 Ce montant sera versé à la vendeuse après confirmation du service.\n"
        f"💡 Minimum : 500 XAF\n\n"
        f"_Ex: 5000_",
        parse_mode="Markdown"
    )
    return REQ_AMOUNT


async def new_request_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = int(update.message.text.strip().replace(" ", "").replace("xaf", "").replace("XAF", ""))
        if amount < 500:
            await update.message.reply_text("❌ Minimum 500 XAF. Réessayez :")
            return REQ_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ Entrez un montant. Ex: 5000")
        return REQ_AMOUNT

    context.user_data["amount"] = amount
    fee = int(amount * COMMISSION)
    seller_gets = amount - fee

    keyboard = [[
        InlineKeyboardButton("🟠 Orange Money", callback_data="method_orange"),
        InlineKeyboardButton("🟡 MTN MoMo", callback_data="method_mtn"),
    ]]
    await update.message.reply_text(
        f"✅ Montant : *{amount:,} XAF*\n"
        f"   Commission Vaultia (10%) : -{fee:,} XAF\n"
        f"   La vendeuse recevra : *{seller_gets:,} XAF*\n\n"
        f"Étape 3/5 — Votre moyen de paiement :",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return REQ_METHOD


async def new_request_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    method = query.data.replace("method_", "")
    context.user_data["method"] = method
    method_name = "Orange Money" if method == "orange" else "MTN MoMo"

    await query.edit_message_text(
        f"✅ Paiement via *{method_name}*\n\n"
        f"Étape 4/5 — Entrez le *@username Telegram* de la vendeuse :\n\n"
        f"_Ex: @NovaStar237_\n\n"
        f"💡 Elle recevra une notification dès que vous avez payé.",
        parse_mode="Markdown"
    )
    return REQ_PHONE


async def new_request_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    seller_input = update.message.text.strip()

    # Accepter @username ou numéro de téléphone
    if not seller_input.startswith("@") and not seller_input.startswith("+") and not seller_input.startswith("6"):
        await update.message.reply_text(
            "❌ Entrez le @username Telegram de la vendeuse.\n"
            "_Ex: @NovaStar237_",
            parse_mode="Markdown"
        )
        return REQ_PHONE

    seller_ref = seller_input.lstrip("@")
    context.user_data["seller_ref"] = seller_ref

    amount = context.user_data["amount"]
    fee = int(amount * COMMISSION)
    method_name = "Orange Money" if context.user_data["method"] == "orange" else "MTN MoMo"

    keyboard = [[
        InlineKeyboardButton("✅ Confirmer et payer", callback_data="req_confirm"),
        InlineKeyboardButton("❌ Annuler", callback_data="req_cancel"),
    ]]

    await update.message.reply_text(
        f"📋 *Récapitulatif de votre demande*\n\n"
        f"📝 Service : _{context.user_data['desc']}_\n"
        f"👩 Vendeuse : @{seller_ref}\n"
        f"💵 Montant garanti : *{amount:,} XAF*\n"
        f"📱 Paiement via : *{method_name}*\n"
        f"🏦 Commission Vaultia : {fee:,} XAF\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🛡️ *Votre argent est sécurisé.*\n"
        f"Il ne sera versé à la vendeuse qu'après votre confirmation du service.\n"
        f"Si elle ne se présente pas, vous êtes remboursé.\n\n"
        f"Confirmez-vous ?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return REQ_CONFIRM


async def new_request_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "req_cancel":
        await query.edit_message_text("❌ Demande annulée.")
        context.user_data.clear()
        return ConversationHandler.END

    user = query.from_user
    data = context.user_data

    await query.edit_message_text("⏳ Initialisation du paiement...")

    # Créer l'escrow en base
    escrow = create_escrow(
        client_id=user.id,
        client_name=user.full_name or user.first_name,
        seller_telegram=data["seller_ref"],
        description=data["desc"],
        amount=data["amount"],
        pay_method=data["method"],
        pay_phone=""  # on demandera le numéro à NotchPay
    )

    # Initialiser le paiement NotchPay
    payment = await create_payment(
        escrow_id=escrow["id"],
        amount=data["amount"],
        method=data["method"],
        description=f"Escrow Vaultia — {data['desc'][:50]}"
    )

    if payment["success"]:
        keyboard = [[
            InlineKeyboardButton("📲 Payer maintenant", url=payment["payment_url"])
        ]]
        await query.edit_message_text(
            f"📲 *Confirmez votre paiement*\n\n"
            f"💵 Montant : *{data['amount']:,} XAF*\n\n"
            f"Cliquez sur le bouton ci-dessous et confirmez le paiement "
            f"sur votre téléphone avec votre code PIN.\n\n"
            f"⏳ Dès confirmation, la vendeuse @{data['seller_ref']} "
            f"sera notifiée automatiquement.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        # Mode simulation — marquer directement comme funded
        await _after_payment_confirmed(query, context, escrow, data["seller_ref"])

    context.user_data.clear()
    return ConversationHandler.END


async def _after_payment_confirmed(query_or_msg, context, escrow: dict, seller_ref: str):
    """Appelé après confirmation du paiement (webhook ou simulation)"""
    escrow_id = escrow["id"]
    mark_funded(escrow_id, f"SIM_{escrow_id[:8]}")

    short_id = escrow_id[:8].upper()
    amount = escrow["amount"]
    seller_gets = escrow["seller_amount"]
    desc = escrow["description"]

    # Notifier le client
    try:
        await context.bot.send_message(
            chat_id=escrow["client_telegram_id"],
            text=f"✅ *Paiement confirmé !*\n\n"
                 f"🔐 Référence : `{short_id}`\n"
                 f"💵 *{amount:,} XAF* sécurisés chez Vaultia\n\n"
                 f"📨 La vendeuse @{seller_ref} a été notifiée.\n"
                 f"Elle doit accepter votre demande.\n\n"
                 f"⏰ Si elle n'accepte pas dans 24h, vous êtes automatiquement remboursé.",
            parse_mode="Markdown"
        )
    except:
        pass

    # Notifier la vendeuse
    await _notify_seller(context, escrow, seller_ref)


async def _notify_seller(context, escrow: dict, seller_username: str):
    """Cherche la vendeuse par username et lui envoie une notification"""
    # En production, chercher l'ID Telegram via la base de données
    # Pour l'instant, on utilise le système de deep link
    short_id = escrow["id"][:8].upper()
    amount = escrow["amount"]
    seller_gets = escrow["seller_amount"]

    keyboard = [[
        InlineKeyboardButton("✅ Accepter", callback_data=f"accept_{escrow['id']}"),
        InlineKeyboardButton("❌ Refuser", callback_data=f"decline_{escrow['id']}"),
    ]]

    # Si on a l'ID de la vendeuse en base
    from db.database import get_db
    try:
        res = get_db().table("users").select("telegram_id").eq("username", seller_username).single().execute()
        if res.data:
            seller_id = res.data["telegram_id"]
            await context.bot.send_message(
                chat_id=seller_id,
                text=f"🔔 *Nouvelle demande !*\n\n"
                     f"🔐 Réf : `{short_id}`\n"
                     f"📝 Service : _{escrow['description']}_\n"
                     f"💰 Vous recevrez : *{seller_gets:,} XAF*\n\n"
                     f"✅ L'argent est déjà sécurisé chez Vaultia.\n"
                     f"Si vous acceptez et rendez le service, vous serez payée.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except:
        # La vendeuse n'a pas encore le bot — envoyer le lien
        pass


# ==================== ACTIONS VENDEUSE ====================

async def seller_accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    escrow_id = query.data.replace("accept_", "")
    escrow = get_escrow(escrow_id)

    if not escrow or escrow["status"] != "funded":
        await query.answer("Cette demande n'est plus disponible.", show_alert=True)
        return

    seller = query.from_user
    mark_accepted(escrow_id, seller.id)

    short_id = escrow_id[:8].upper()

    keyboard = [[
        InlineKeyboardButton("✅ J'ai rendu le service", callback_data=f"delivered_{escrow_id}"),
    ]]

    await query.edit_message_text(
        f"✅ *Demande acceptée !*\n\n"
        f"🔐 Réf : `{short_id}`\n"
        f"📝 _{escrow['description']}_\n"
        f"💰 Vous recevrez : *{escrow['seller_amount']:,} XAF*\n\n"
        f"Rendez le service convenu.\n"
        f"Quand c'est fait, appuyez sur le bouton ci-dessous.\n"
        f"Le client devra confirmer pour que vous soyez payée.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    # Notifier le client
    try:
        keyboard_client = [[
            InlineKeyboardButton("✅ Confirmer réception", callback_data=f"confirm_delivery_{escrow_id}"),
            InlineKeyboardButton("⚠️ Ouvrir un litige", callback_data=f"dispute_{escrow_id}"),
        ]]
        await context.bot.send_message(
            chat_id=escrow["client_telegram_id"],
            text=f"✅ *La vendeuse a accepté votre demande !*\n\n"
                 f"🔐 Réf : `{short_id}`\n"
                 f"📝 _{escrow['description']}_\n\n"
                 f"Elle va vous rendre le service.\n"
                 f"Dès que c'est fait, confirmez ici pour qu'elle soit payée.\n\n"
                 f"⚠️ Si elle ne se présente pas, ouvrez un litige.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard_client)
        )
    except:
        pass


async def seller_decline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    escrow_id = query.data.replace("decline_", "")
    escrow = get_escrow(escrow_id)

    if not escrow:
        return

    mark_refunded(escrow_id)
    short_id = escrow_id[:8].upper()

    await query.edit_message_text(
        f"❌ Vous avez refusé la demande `{short_id}`.\n"
        f"Le client sera remboursé automatiquement.",
        parse_mode="Markdown"
    )

    # Rembourser le client
    try:
        await context.bot.send_message(
            chat_id=escrow["client_telegram_id"],
            text=f"↩️ *La vendeuse a refusé votre demande.*\n\n"
                 f"🔐 Réf : `{short_id}`\n\n"
                 f"Votre remboursement de *{escrow['amount']:,} XAF* "
                 f"sera effectué sous 24h sur votre {escrow['pay_method'].upper()}.",
            parse_mode="Markdown"
        )
    except:
        pass


async def seller_mark_delivered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """La vendeuse signale qu'elle a livré"""
    query = update.callback_query
    await query.answer()

    escrow_id = query.data.replace("delivered_", "")
    escrow = get_escrow(escrow_id)

    if not escrow or escrow["status"] != "accepted":
        await query.answer("Statut invalide.", show_alert=True)
        return

    mark_delivered(escrow_id)
    short_id = escrow_id[:8].upper()

    await query.edit_message_text(
        f"📦 *Service signalé comme rendu*\n\n"
        f"🔐 Réf : `{short_id}`\n\n"
        f"En attente de confirmation du client.\n"
        f"Vous serez payée dès qu'il confirme.\n\n"
        f"⏰ Si le client ne répond pas dans 48h, les fonds vous sont versés automatiquement.",
        parse_mode="Markdown"
    )

    # Notifier le client
    try:
        keyboard = [[
            InlineKeyboardButton("✅ Confirmer — libérer les fonds", callback_data=f"confirm_delivery_{escrow_id}"),
            InlineKeyboardButton("⚠️ Litige", callback_data=f"dispute_{escrow_id}"),
        ]]
        await context.bot.send_message(
            chat_id=escrow["client_telegram_id"],
            text=f"📦 *La vendeuse signale avoir rendu le service*\n\n"
                 f"🔐 Réf : `{short_id}`\n"
                 f"📝 _{escrow['description']}_\n\n"
                 f"Confirmez-vous avoir reçu le service ?\n\n"
                 f"✅ *Oui* → La vendeuse reçoit *{escrow['seller_amount']:,} XAF*\n"
                 f"⚠️ *Non* → Ouvrez un litige, Vaultia arbitre",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except:
        pass


# ==================== ACTIONS CLIENT ====================

async def client_confirm_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Client confirme avoir reçu le service → fonds libérés"""
    query = update.callback_query
    await query.answer()

    escrow_id = query.data.replace("confirm_delivery_", "")
    escrow = get_escrow(escrow_id)

    if not escrow or escrow["status"] not in ("accepted", "delivered"):
        await query.answer("Cette demande n'est plus en cours.", show_alert=True)
        return

    mark_completed(escrow_id)
    short_id = escrow_id[:8].upper()

    await query.edit_message_text(
        f"🎉 *Service confirmé !*\n\n"
        f"🔐 Réf : `{short_id}`\n"
        f"💵 *{escrow['seller_amount']:,} XAF* versés à la vendeuse.\n\n"
        f"Merci d'avoir utilisé Vaultia.",
        parse_mode="Markdown"
    )

    # Notifier la vendeuse
    if escrow.get("seller_telegram_id"):
        try:
            await context.bot.send_message(
                chat_id=escrow["seller_telegram_id"],
                text=f"💰 *Paiement reçu !*\n\n"
                     f"🔐 Réf : `{short_id}`\n"
                     f"💵 *{escrow['seller_amount']:,} XAF* crédités sur votre solde Vaultia.\n\n"
                     f"Retirez vos gains via /menu → Mon solde & retraits.",
                parse_mode="Markdown"
            )
        except:
            pass


async def client_dispute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Client ouvre un litige"""
    query = update.callback_query
    await query.answer()

    escrow_id = query.data.replace("dispute_", "")
    escrow = get_escrow(escrow_id)

    if not escrow:
        return

    mark_disputed(escrow_id, "Litige ouvert par le client")
    short_id = escrow_id[:8].upper()

    # Notifier l'admin
    if ADMIN_ID:
        keyboard = [[
            InlineKeyboardButton("✅ Rembourser client", callback_data=f"resolve_client_{escrow_id}"),
            InlineKeyboardButton("💰 Payer vendeuse", callback_data=f"resolve_seller_{escrow_id}"),
        ]]
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"⚠️ *LITIGE OUVERT*\n\n"
                     f"🔐 Réf : `{short_id}`\n"
                     f"📝 _{escrow['description']}_\n"
                     f"💵 Montant : {escrow['amount']:,} XAF\n"
                     f"👤 Client ID : {escrow['client_telegram_id']}\n"
                     f"👩 Vendeuse : @{escrow['seller_telegram']}\n\n"
                     f"Choisissez la résolution :",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except:
            pass

    await query.edit_message_text(
        f"⚠️ *Litige ouvert*\n\n"
        f"🔐 Réf : `{short_id}`\n\n"
        f"L'équipe Vaultia va examiner votre demande.\n"
        f"Les fonds restent bloqués jusqu'à résolution.\n\n"
        f"⏳ Délai de traitement : 24-48h maximum.",
        parse_mode="Markdown"
    )


# ==================== RÉSOLUTION LITIGES (ADMIN) ====================

async def resolve_dispute_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin : rembourser le client"""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("Accès réservé à l'admin.", show_alert=True)
        return

    escrow_id = query.data.replace("resolve_client_", "")
    escrow = get_escrow(escrow_id)
    if not escrow:
        return

    mark_refunded(escrow_id)
    short_id = escrow_id[:8].upper()

    await query.edit_message_text(f"✅ Litige `{short_id}` résolu — Client remboursé.", parse_mode="Markdown")

    try:
        await context.bot.send_message(
            chat_id=escrow["client_telegram_id"],
            text=f"✅ *Litige résolu en votre faveur*\n\n"
                 f"🔐 Réf : `{short_id}`\n"
                 f"↩️ Remboursement de *{escrow['amount']:,} XAF* sous 24h.",
            parse_mode="Markdown"
        )
    except:
        pass


async def resolve_dispute_seller(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin : payer la vendeuse"""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("Accès réservé à l'admin.", show_alert=True)
        return

    escrow_id = query.data.replace("resolve_seller_", "")
    escrow = get_escrow(escrow_id)
    if not escrow:
        return

    mark_completed(escrow_id)
    short_id = escrow_id[:8].upper()

    await query.edit_message_text(f"✅ Litige `{short_id}` résolu — Vendeuse payée.", parse_mode="Markdown")

    if escrow.get("seller_telegram_id"):
        try:
            await context.bot.send_message(
                chat_id=escrow["seller_telegram_id"],
                text=f"✅ *Litige résolu en votre faveur*\n\n"
                     f"🔐 Réf : `{short_id}`\n"
                     f"💵 *{escrow['seller_amount']:,} XAF* crédités sur votre solde.",
                parse_mode="Markdown"
            )
        except:
            pass


# ==================== HISTORIQUE ====================

async def my_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    escrows = get_client_escrows(query.from_user.id)
    if not escrows:
        keyboard = [[InlineKeyboardButton("➕ Nouvelle demande", callback_data="new_request")]]
        await query.edit_message_text(
            "📋 *Mes demandes*\n\nAucune demande pour le moment.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    text = "📋 *Mes demandes escrow*\n\n"
    keyboard = []

    for e in escrows:
        short_id = e["id"][:8].upper()
        status = ESCROW_STATES.get(e["status"], e["status"])
        text += f"🔐 `{short_id}` — {status}\n"
        text += f"   📝 _{e['description'][:40]}_\n"
        text += f"   💵 {e['amount']:,} XAF\n\n"

        # Ajouter boutons d'action si pertinent
        if e["status"] in ("accepted", "delivered"):
            keyboard.append([
                InlineKeyboardButton(f"✅ Confirmer {short_id}", callback_data=f"confirm_delivery_{e['id']}"),
                InlineKeyboardButton(f"⚠️ Litige {short_id}", callback_data=f"dispute_{e['id']}"),
            ])

    keyboard.append([InlineKeyboardButton("➕ Nouvelle demande", callback_data="new_request")])
    keyboard.append([InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])

    await query.edit_message_text(text, parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(keyboard))


async def my_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    seller_id = query.from_user.id
    escrows = get_seller_escrows(seller_id)

    # Aussi chercher les demandes en attente par username
    user = get_user(seller_id)
    pending = []
    if user and user.get("username"):
        pending = get_pending_for_seller(user["username"])

    if not escrows and not pending:
        await query.edit_message_text(
            "📋 *Mes services*\n\nAucun service pour le moment.\n\n"
            "Les clients vous trouvent via votre @username Telegram.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")]])
        )
        return

    text = "📋 *Mes services*\n\n"
    keyboard = []

    # Demandes en attente d'acceptation
    if pending:
        text += "⚠️ *En attente de votre réponse :*\n\n"
        for e in pending:
            short_id = e["id"][:8].upper()
            text += f"🔐 `{short_id}` — 💰 {e['seller_amount']:,} XAF\n"
            text += f"   📝 _{e['description'][:40]}_\n\n"
            keyboard.append([
                InlineKeyboardButton(f"✅ Accepter {short_id}", callback_data=f"accept_{e['id']}"),
                InlineKeyboardButton(f"❌ Refuser", callback_data=f"decline_{e['id']}"),
            ])

    # Historique
    if escrows:
        text += "📊 *Historique :*\n\n"
        for e in escrows[:5]:
            short_id = e["id"][:8].upper()
            status = ESCROW_STATES.get(e["status"], e["status"])
            text += f"🔐 `{short_id}` — {status}\n"
            text += f"   💵 {e['seller_amount']:,} XAF\n\n"
            if e["status"] == "accepted":
                keyboard.append([
                    InlineKeyboardButton(f"✅ Service rendu {short_id}", callback_data=f"delivered_{e['id']}"),
                ])

    keyboard.append([InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
    await query.edit_message_text(text, parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(keyboard))
