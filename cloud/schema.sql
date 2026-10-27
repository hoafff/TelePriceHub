CREATE TABLE IF NOT EXISTS offers (
  supplier TEXT NOT NULL, canonical_name TEXT NOT NULL, spec_key TEXT NOT NULL,
  raw_name TEXT, price REAL NOT NULL, currency TEXT NOT NULL,
  in_stock INTEGER NOT NULL, last_seen INTEGER NOT NULL,
  PRIMARY KEY (supplier, canonical_name, spec_key, currency)
);
CREATE INDEX IF NOT EXISTS offers_search ON offers(canonical_name);
CREATE INDEX IF NOT EXISTS offers_fresh ON offers(last_seen);
CREATE TABLE IF NOT EXISTS price_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, supplier TEXT NOT NULL,
  canonical_name TEXT NOT NULL, spec_key TEXT NOT NULL,
  price REAL NOT NULL, currency TEXT NOT NULL, in_stock INTEGER NOT NULL,
  changed_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS price_history_idx ON price_history(supplier, canonical_name, spec_key);
