"""
handlers/start.py — Accueil et sélection du rôle
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from db.database import get_user, create_user, get_pending_for_seller

WELCOME = """
🔐 *Bienvenue sur Vaultia*
_Le dépôt garanti pour les services au Cameroun_

━━━━━━━━━━━━━━━━

*Comment ça marche :*
1️⃣ Le client dépose l'argent chez Vaultia
2️⃣ La vendeuse reçoit la notification
3️⃣ Elle rend le service
4️⃣ Le client confirme → elle est payée

✅ *Ni le client, ni la vendeuse ne peuvent se faire arnaquer.*

━━━━━━━━━━━━━━━━
Qui es-tu ?
"""


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    existing = get_user(user.id)

    if existing:
        await show_main_menu(update, context, existing)
        return

    keyboard = [[
        InlineKeyboardButton("👤 Je suis client", callback_data="role_client"),
        InlineKeyboardButton("👩 Je suis vendeuse", callback_data="role_seller"),
    ]]
    msg = update.message or update.callback_query.message
    await msg.reply_text(WELCOME, parse_mode="Markdown",
                         reply_markup=InlineKeyboardMarkup(keyboard))


async def role_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    role = "client" if query.data == "role_client" else "seller"

    new_user = create_user(
        telegram_id=user.id,
        username=user.username or "",
        full_name=user.full_name or user.first_name,
        role=role
    )
    await show_main_menu(update, context, new_user, edit=True)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          user: dict, edit: bool = False):
    name = user["full_name"].split()[0]
    role = user["role"]

    if role == "client":
        text = f"""
👤 *Menu Client — {name}*

Déposez de l'argent en garantie pour sécuriser vos transactions.
La vendeuse est payée seulement après que vous confirmez.

💰 Solde disponible : *{user['balance']:,} XAF*
"""
        keyboard = [
            [InlineKeyboardButton("➕ Nouvelle demande escrow", callback_data="new_request")],
            [InlineKeyboardButton("📋 Mes demandes", callback_data="my_requests"),
             InlineKeyboardButton("💰 Mon solde", callback_data="my_balance")],
        ]

    else:  # seller
        # Vérifier les demandes en attente
        pending = []
        if user.get("username"):
            pending = get_pending_for_seller(user["username"])

        pending_text = f"\n⚠️ *{len(pending)} demande(s) en attente de votre réponse !*" if pending else ""
        text = f"""
👩 *Menu Vendeuse — {name}*

Les clients déposent l'argent avant de vous contacter.
Vous êtes payée dès confirmation du service rendu.{pending_text}

💰 Solde disponible : *{user['balance']:,} XAF*
"""
        keyboard = [
            [InlineKeyboardButton("📋 Mes services", callback_data="my_services")],
            [InlineKeyboardButton("💰 Mon solde & retraits", callback_data="my_balance")],
        ]
        if pending:
            keyboard.insert(0, [InlineKeyboardButton(
                f"⚠️ Voir {len(pending)} demande(s) en attente",
                callback_data="my_services"
            )])

    keyboard.append([InlineKeyboardButton("ℹ️ Comment ça marche", callback_data="how_it_works")])

    markup = InlineKeyboardMarkup(keyboard)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
    else:
        msg = update.message or update.callback_query.message
        await msg.reply_text(text, parse_mode="Markdown", reply_markup=markup)
