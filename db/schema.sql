-- ==========================================
-- VAULTIA ESCROW — Schéma SQL Supabase
-- ==========================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- USERS
CREATE TABLE users (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  telegram_id       BIGINT UNIQUE NOT NULL,
  username          TEXT DEFAULT '',
  full_name         TEXT NOT NULL,
  role              TEXT DEFAULT '',  -- Plus utilisé comme rôle fixe, gardé pour compatibilité
  balance           INTEGER DEFAULT 0,  -- Solde en XAF (gains non retirés)
  total_sent        INTEGER DEFAULT 0,  -- Total envoyé comme client
  total_received    INTEGER DEFAULT 0,  -- Total reçu comme vendeuse
  created_at        TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_users_tg ON users(telegram_id);
CREATE INDEX idx_users_username ON users(username);

-- ESCROWS
CREATE TABLE escrows (
  id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  client_telegram_id    BIGINT NOT NULL REFERENCES users(telegram_id),
  client_name           TEXT NOT NULL,
  seller_telegram       TEXT NOT NULL,        -- @username de la vendeuse
  seller_telegram_id    BIGINT,               -- rempli quand elle accepte
  description           TEXT NOT NULL,        -- Description du service
  amount                INTEGER NOT NULL,     -- Montant total en XAF
  fee                   INTEGER NOT NULL,     -- Commission Vaultia (10%)
  seller_amount         INTEGER NOT NULL,     -- Ce que reçoit la vendeuse (90%)
  pay_method            TEXT,                 -- 'orange' ou 'mtn'
  pay_phone             TEXT DEFAULT '',
  notchpay_ref          TEXT DEFAULT '',
  dispute_reason        TEXT DEFAULT '',
  status                TEXT DEFAULT 'pending_payment' CHECK (status IN (
                          'pending_payment',  -- En attente de paiement client
                          'funded',           -- Payé — en attente vendeuse
                          'accepted',         -- Vendeuse acceptée — service en cours
                          'delivered',        -- Vendeuse dit avoir livré
                          'completed',        -- Client confirme — fonds libérés
                          'disputed',         -- Litige en cours
                          'refunded',         -- Remboursé au client
                          'expired'           -- Délai dépassé
                        )),
  expires_at            TIMESTAMPTZ,
  funded_at             TIMESTAMPTZ,
  accepted_at           TIMESTAMPTZ,
  delivered_at          TIMESTAMPTZ,
  completed_at          TIMESTAMPTZ,
  disputed_at           TIMESTAMPTZ,
  refunded_at           TIMESTAMPTZ,
  created_at            TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_escrows_client ON escrows(client_telegram_id);
CREATE INDEX idx_escrows_seller_id ON escrows(seller_telegram_id);
CREATE INDEX idx_escrows_seller_username ON escrows(seller_telegram);
CREATE INDEX idx_escrows_status ON escrows(status);
CREATE INDEX idx_escrows_notchpay ON escrows(notchpay_ref);

-- WITHDRAWALS
CREATE TABLE withdrawals (
  id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  seller_telegram_id  BIGINT NOT NULL REFERENCES users(telegram_id),
  amount              INTEGER NOT NULL,
  payment_phone       TEXT NOT NULL,
  payment_method      TEXT CHECK (payment_method IN ('orange', 'mtn')),
  status              TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'processed', 'failed')),
  created_at          TIMESTAMPTZ DEFAULT NOW(),
  processed_at        TIMESTAMPTZ
);
CREATE INDEX idx_withdrawals_seller ON withdrawals(seller_telegram_id);

-- VUE : stats plateforme
CREATE VIEW platform_stats AS
SELECT
  (SELECT COUNT(*) FROM users WHERE role = 'client') AS total_clients,
  (SELECT COUNT(*) FROM users WHERE role = 'seller') AS total_sellers,
  (SELECT COUNT(*) FROM escrows WHERE status = 'completed') AS completed_escrows,
  (SELECT SUM(amount) FROM escrows WHERE status = 'completed') AS total_volume_xaf,
  (SELECT SUM(fee) FROM escrows WHERE status = 'completed') AS total_fees_xaf,
  (SELECT COUNT(*) FROM escrows WHERE status = 'disputed') AS active_disputes;
