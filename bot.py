"""
VAULTIA ESCROW BOT
Bot Telegram d'escrow pour services physiques au Cameroun
Stack : python-telegram-bot 22.x + Supabase + NotchPay
"""

import logging
import os
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters
)
from dotenv import load_dotenv

from handlers.start import start_handler, role_callback
from handlers.escrow import (
    # Création d'une demande (client)
    new_request_start, new_request_desc, new_request_amount,
    new_request_method, new_request_phone, new_request_confirm,
    # Réponse vendeuse
    seller_accept, seller_decline,
    # Confirmation client après service
    client_confirm_delivery, client_dispute,
    # Litiges
    resolve_dispute_seller, resolve_dispute_client,
    # Historique
    my_requests, my_services,
    # États
    REQ_DESC, REQ_AMOUNT, REQ_METHOD, REQ_PHONE, REQ_CONFIRM
)
from handlers.wallet import (
    show_balance, withdraw_start, withdraw_amount,
    withdraw_phone, withdraw_confirm,
    WDRAW_AMOUNT, WDRAW_PHONE, WDRAW_CONFIRM
)

load_dotenv()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN manquant dans .env")

    app = Application.builder().token(token).build()

    # === CONVERSATION : Nouvelle demande escrow ===
    new_request_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(new_request_start, pattern="^new_request$")],
        states={
            REQ_DESC:    [MessageHandler(filters.TEXT & ~filters.COMMAND, new_request_desc)],
            REQ_AMOUNT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, new_request_amount)],
            REQ_METHOD:  [CallbackQueryHandler(new_request_method, pattern="^method_")],
            REQ_PHONE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, new_request_phone)],
            REQ_CONFIRM: [CallbackQueryHandler(new_request_confirm, pattern="^(req_confirm|req_cancel)$")],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        allow_reentry=True
    )

    # === CONVERSATION : Retrait ===
    withdraw_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(withdraw_start, pattern="^withdraw$")],
        states={
            WDRAW_AMOUNT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_amount)],
            WDRAW_PHONE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_phone)],
            WDRAW_CONFIRM: [CallbackQueryHandler(withdraw_confirm, pattern="^(wdraw_ok|wdraw_cancel)$")],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )

    # === HANDLERS ===
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("menu", start_handler))
    app.add_handler(CallbackQueryHandler(role_callback, pattern="^role_"))
    app.add_handler(CallbackQueryHandler(my_requests, pattern="^my_requests$"))
    app.add_handler(CallbackQueryHandler(my_services, pattern="^my_services$"))
    app.add_handler(CallbackQueryHandler(show_balance, pattern="^my_balance$"))
    app.add_handler(CallbackQueryHandler(seller_accept, pattern="^accept_"))
    app.add_handler(CallbackQueryHandler(seller_decline, pattern="^decline_"))
    app.add_handler(CallbackQueryHandler(client_confirm_delivery, pattern="^confirm_delivery_"))
    app.add_handler(CallbackQueryHandler(client_dispute, pattern="^dispute_"))
    app.add_handler(CallbackQueryHandler(resolve_dispute_seller, pattern="^resolve_seller_"))
    app.add_handler(CallbackQueryHandler(resolve_dispute_client, pattern="^resolve_client_"))
    app.add_handler(new_request_conv)
    app.add_handler(withdraw_conv)

    logger.info("🔐 Vaultia Escrow Bot démarré !")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
