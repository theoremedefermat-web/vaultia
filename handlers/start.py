"""
handlers/start.py — Accueil et sélection du mode (session-based)
Le rôle n'est PAS lié au compte. À chaque /start, l'utilisateur
choisit comment il veut utiliser le bot : en tant que client ou vendeuse.
Un même compte peut switcher librement.
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from db.database import get_user, get_or_create_user, get_pending_for_seller

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
Comment voulez-vous utiliser Vaultia aujourd'hui ?
"""


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start affiche TOUJOURS le choix du mode, même si l'utilisateur
    est déjà connu. Le rôle est une décision de session, pas de compte.
    """
    user = update.effective_user

    # Créer le compte si première visite, sinon juste récupérer
    get_or_create_user(
        telegram_id=user.id,
        username=user.username or "",
        full_name=user.full_name or user.first_name
    )

    # Toujours afficher le choix du mode
    keyboard = [[
        InlineKeyboardButton("👤 Mode Client", callback_data="role_client"),
        InlineKeyboardButton("👩 Mode Vendeuse", callback_data="role_seller"),
    ]]
    msg = update.message or update.callback_query.message
    await msg.reply_text(
        WELCOME,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def role_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """L'utilisateur choisit son mode pour cette session."""
    query = update.callback_query
    await query.answer()

    tg_user = query.from_user
    mode = "client" if query.data == "role_client" else "seller"

    # Sauvegarder le mode dans la session (context.user_data)
    context.user_data["mode"] = mode

    # Récupérer le profil (déjà créé au /start)
    user = get_user(tg_user.id)
    if not user:
        user = get_or_create_user(tg_user.id, tg_user.username or "", tg_user.full_name or tg_user.first_name)

    await show_main_menu(update, context, user, mode=mode, edit=True)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          user: dict, mode: str = None, edit: bool = False):
    """
    Affiche le menu selon le mode choisi pour cette session.
    Si mode non fourni, le lit depuis context.user_data.
    """
    if mode is None:
        mode = context.user_data.get("mode", "client")

    name = (user.get("full_name") or "").split()[0] or "vous"
    balance = user.get("balance", 0)

    if mode == "client":
        text = (
            f"👤 *Mode Client — {name}*\n\n"
            f"Déposez de l'argent en garantie pour sécuriser vos transactions.\n"
            f"La vendeuse est payée seulement après votre confirmation.\n\n"
            f"💰 Solde disponible : *{balance:,} XAF*"
        )
        keyboard = [
            [InlineKeyboardButton("➕ Nouvelle demande escrow", callback_data="new_request")],
            [
                InlineKeyboardButton("📋 Mes demandes", callback_data="my_requests"),
                InlineKeyboardButton("💰 Mon solde", callback_data="my_balance"),
            ],
            [InlineKeyboardButton("🔄 Passer en mode Vendeuse", callback_data="role_seller")],
        ]

    else:  # seller mode
        pending = []
        if user.get("username"):
            pending = get_pending_for_seller(user["username"])

        pending_text = (
            f"\n\n⚠️ *{len(pending)} demande(s) en attente de votre réponse !*"
            if pending else ""
        )
        text = (
            f"👩 *Mode Vendeuse — {name}*\n\n"
            f"Les clients déposent l'argent avant de vous contacter.\n"
            f"Vous êtes payée dès confirmation du service rendu."
            f"{pending_text}\n\n"
            f"💰 Solde disponible : *{balance:,} XAF*"
        )
        keyboard = [
            [InlineKeyboardButton("📋 Mes services en cours", callback_data="my_services")],
            [InlineKeyboardButton("💰 Mon solde & retraits", callback_data="my_balance")],
            [InlineKeyboardButton("🔄 Passer en mode Client", callback_data="role_client")],
        ]
        if pending:
            keyboard.insert(0, [InlineKeyboardButton(
                f"⚠️ {len(pending)} demande(s) en attente — Voir",
                callback_data="my_services"
            )])

    keyboard.append([InlineKeyboardButton("🏠 Changer de mode (/start)", callback_data="go_start")])

    markup = InlineKeyboardMarkup(keyboard)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=markup
        )
    else:
        msg = update.message or (update.callback_query.message if update.callback_query else None)
        if msg:
            await msg.reply_text(text, parse_mode="Markdown", reply_markup=markup)
