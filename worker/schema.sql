CREATE TABLE IF NOT EXISTS articles (
 id TEXT PRIMARY KEY,
 title TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 url TEXT NOT NULL,
 source TEXT NOT NULL,
 category TEXT NOT NULL,
 published TEXT NOT NULL,
 delivered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_articles_time ON articles(delivered_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category, delivered_at DESC);