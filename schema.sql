-- PostgreSQL schema for Telegram Expense Bot.
-- The webhook entrypoint also creates these tables automatically on first request.
CREATE TABLE IF NOT EXISTS categories (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    emoji TEXT NOT NULL,
    name TEXT NOT NULL,
    UNIQUE(user_id, name)
);
CREATE TABLE IF NOT EXISTS expenses (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    title TEXT NOT NULL,
    amount NUMERIC(14,2) NOT NULL,
    category_id BIGINT NOT NULL REFERENCES categories(id),
    comment TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS user_state (
    user_id BIGINT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT '',
    pending_title TEXT,
    pending_amount NUMERIC(14,2)
);
