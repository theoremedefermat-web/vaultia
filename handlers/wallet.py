"""
handlers/wallet.py — Solde et retraits
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from db.database import get_user, get_balance, create_withdrawal, get_withdrawals

WDRAW_AMOUNT, WDRAW_PHONE, WDRAW_CONFIRM = range(10, 13)


async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    balance = get_balance(user_id)
    withdrawals = get_withdrawals(user_id)

    status_map = {"pending": "⏳ En attente", "processed": "✅ Traité", "failed": "❌ Échoué"}

    hist = ""
    if withdrawals:
        hist = "\n━━━━━━━━━━━━━━━━\n📊 *Derniers retraits :*\n\n"
        for w in withdrawals:
            s = status_map.get(w["status"], w["status"])
            hist += f"• {w['amount']:,} XAF → {w['payment_phone']} — {s}\n"

    keyboard = []
    if balance >= 1000:
        keyboard.append([InlineKeyboardButton("💸 Retirer mes gains", callback_data="withdraw")])
    keyboard.append([InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])

    await query.edit_message_text(
        f"💰 *Mon solde Vaultia*\n\n"
        f"Disponible : *{balance:,} XAF*\n"
        f"{'_Minimum de retrait : 1 000 XAF_' if balance < 1000 else ''}"
        f"{hist}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def withdraw_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    balance = get_balance(query.from_user.id)
    context.user_data["balance"] = balance

    if balance < 1000:
        await query.edit_message_text(
            f"❌ Solde insuffisant : *{balance:,} XAF*\nMinimum de retrait : 1 000 XAF",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")]])
        )
        return ConversationHandler.END

    await query.edit_message_text(
        f"💸 *Retrait*\n\nSolde disponible : *{balance:,} XAF*\n\n"
        f"Combien voulez-vous retirer ? (min 1 000 XAF)\n\n/cancel pour annuler",
        parse_mode="Markdown"
    )
    return WDRAW_AMOUNT


async def withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = int(update.message.text.strip().replace(" ", ""))
        balance = context.user_data.get("balance", 0)
        if amount < 1000:
            await update.message.reply_text("❌ Minimum 1 000 XAF.")
            return WDRAW_AMOUNT
        if amount > balance:
            await update.message.reply_text(f"❌ Solde insuffisant ({balance:,} XAF).")
            return WDRAW_AMOUNT
    except:
        await update.message.reply_text("❌ Entrez un montant valide.")
        return WDRAW_AMOUNT

    context.user_data["wdraw_amount"] = amount
    keyboard = [[
        InlineKeyboardButton("🟠 Orange Money", callback_data="wmethod_orange"),
        InlineKeyboardButton("🟡 MTN MoMo", callback_data="wmethod_mtn"),
    ]]
    await update.message.reply_text(
        f"✅ Montant : *{amount:,} XAF*\n\nChoisissez votre moyen de réception :",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return WDRAW_PHONE


async def withdraw_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Gérer le choix de méthode ET l'entrée du numéro
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        method = query.data.replace("wmethod_", "")
        context.user_data["wdraw_method"] = method
        method_name = "Orange Money" if method == "orange" else "MTN MoMo"
        await query.edit_message_text(
            f"✅ Via *{method_name}*\n\nEntrez votre numéro de réception :",
            parse_mode="Markdown"
        )
        return WDRAW_PHONE

    phone = update.message.text.strip()
    context.user_data["wdraw_phone"] = phone
    amount = context.user_data["wdraw_amount"]
    method = context.user_data.get("wdraw_method", "orange")
    method_name = "Orange Money" if method == "orange" else "MTN MoMo"

    keyboard = [[
        InlineKeyboardButton("✅ Confirmer", callback_data="wdraw_ok"),
        InlineKeyboardButton("❌ Annuler", callback_data="wdraw_cancel"),
    ]]
    await update.message.reply_text(
        f"📋 *Récapitulatif retrait*\n\n"
        f"💵 Montant : *{amount:,} XAF*\n"
        f"📱 Via : *{method_name}*\n"
        f"📞 Numéro : *{phone}*\n\n"
        f"Confirmez-vous ?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return WDRAW_CONFIRM


async def withdraw_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "wdraw_cancel":
        await query.edit_message_text("❌ Retrait annulé.")
        return ConversationHandler.END

    seller_id = query.from_user.id
    amount = context.user_data["wdraw_amount"]
    phone = context.user_data["wdraw_phone"]
    method = context.user_data.get("wdraw_method", "orange")

    create_withdrawal(seller_id, amount, phone, method)

    await query.edit_message_text(
        f"✅ *Demande de retrait enregistrée !*\n\n"
        f"💵 *{amount:,} XAF* vers *{phone}*\n\n"
        f"⏳ Traitement sous 24h maximum.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")]])
    )
    context.user_data.clear()
    return ConversationHandler.END
