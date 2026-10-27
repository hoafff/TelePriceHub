"""Database access layer using stdlib sqlite3.

Provides atomic transactions, schema migrations, and optimized queries for price comparison.
"""

from contextlib import contextmanager
import json
import sqlite3
from typing import Any, Dict, Generator, List, Optional, Tuple


SCHEMA = """
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    name TEXT,
    is_active INTEGER DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_name TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    brand TEXT,
    model TEXT,
    spec_key TEXT NOT NULL,
    specs_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(canonical_name, spec_key)
);

CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    supplier_id INTEGER NOT NULL,
    price REAL NOT NULL,
    currency TEXT DEFAULT 'VND',
    in_stock INTEGER DEFAULT 1,
    duration TEXT,
    raw_message TEXT,
    crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
    FOREIGN KEY(supplier_id) REFERENCES suppliers(id) ON DELETE CASCADE,
    UNIQUE(product_id, supplier_id)
);

CREATE TABLE IF NOT EXISTS offer_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    supplier_id INTEGER NOT NULL,
    price REAL NOT NULL,
    currency TEXT DEFAULT 'VND',
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS crawl_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id INTEGER NOT NULL,
    node_hash TEXT NOT NULL,
    depth INTEGER DEFAULT 0,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(supplier_id, node_hash)
);

CREATE INDEX IF NOT EXISTS idx_products_canonical ON products(canonical_name, spec_key);
CREATE INDEX IF NOT EXISTS idx_products_raw ON products(raw_name);
CREATE INDEX IF NOT EXISTS idx_offers_product_price ON offers(product_id, price ASC);
CREATE INDEX IF NOT EXISTS idx_crawl_state_lookup ON crawl_state(supplier_id, node_hash);
"""


class Database:
    def __init__(self, db_path: str = "teleprice.db") -> None:
        self.db_path = db_path
        self.init_db()

    @contextmanager
    def get_conn(self) -> Generator[sqlite3.Connection, None, None]:
        # ponytail: single-threaded/thread-local sqlite connection; upgrade to WAL mode & connection pool if multi-worker concurrency needed
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.get_conn() as conn:
            conn.executescript(SCHEMA)

    def upsert_supplier(self, username: str, name: Optional[str] = None) -> int:
        username = username.strip()
        if not username.startswith("@") and not username.isdigit():
            username = f"@{username}"
        display_name = name or username
        with self.get_conn() as conn:
            conn.execute(
                """
                INSERT INTO suppliers (username, name, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(username) DO UPDATE SET
                    name = coalesce(excluded.name, suppliers.name),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (username, display_name),
            )
            row = conn.execute("SELECT id FROM suppliers WHERE username = ?", (username,)).fetchone()
            return int(row["id"])

    def upsert_product(
        self,
        raw_name: str,
        canonical_name: str,
        brand: str = "",
        model: str = "",
        spec_key: str = "",
        specs: Optional[Dict[str, Any]] = None,
    ) -> int:
        specs_json = json.dumps(specs or {}, ensure_ascii=False)
        spec_key = spec_key or "default"
        with self.get_conn() as conn:
            conn.execute(
                """
                INSERT INTO products (raw_name, canonical_name, brand, model, spec_key, specs_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_name, spec_key) DO UPDATE SET
                    raw_name = excluded.raw_name,
                    brand = CASE WHEN excluded.brand != '' THEN excluded.brand ELSE products.brand END,
                    model = CASE WHEN excluded.model != '' THEN excluded.model ELSE products.model END,
                    specs_json = excluded.specs_json
                """,
                (raw_name, canonical_name, brand, model, spec_key, specs_json),
            )
            row = conn.execute(
                "SELECT id FROM products WHERE canonical_name = ? AND spec_key = ?",
                (canonical_name, spec_key),
            ).fetchone()
            return int(row["id"])

    def save_offer(
        self,
        supplier_id: int,
        product_id: int,
        price: float,
        currency: str = "VND",
        in_stock: int = 1,
        duration: str = "",
        raw_message: str = "",
    ) -> None:
        with self.get_conn() as conn:
            # Check previous price to log history on change
            prev = conn.execute(
                "SELECT price FROM offers WHERE product_id = ? AND supplier_id = ?",
                (product_id, supplier_id),
            ).fetchone()

            if prev is None or abs(float(prev["price"]) - price) > 0.001:
                conn.execute(
                    """
                    INSERT INTO offer_history (product_id, supplier_id, price, currency)
                    VALUES (?, ?, ?, ?)
                    """,
                    (product_id, supplier_id, price, currency),
                )

            conn.execute(
                """
                INSERT INTO offers (product_id, supplier_id, price, currency, in_stock, duration, raw_message, crawled_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(product_id, supplier_id) DO UPDATE SET
                    price = excluded.price,
                    currency = excluded.currency,
                    in_stock = excluded.in_stock,
                    duration = excluded.duration,
                    raw_message = excluded.raw_message,
                    crawled_at = CURRENT_TIMESTAMP
                """,
                (product_id, supplier_id, price, currency, in_stock, duration, raw_message),
            )

    def is_node_visited(self, supplier_id: int, node_hash: str) -> bool:
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM crawl_state WHERE supplier_id = ? AND node_hash = ?",
                (supplier_id, node_hash),
            ).fetchone()
            return row is not None

    def mark_node_visited(self, supplier_id: int, node_hash: str, depth: int = 0) -> None:
        with self.get_conn() as conn:
            conn.execute(
                """
                INSERT INTO crawl_state (supplier_id, node_hash, depth, last_seen)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(supplier_id, node_hash) DO UPDATE SET
                    depth = excluded.depth,
                    last_seen = CURRENT_TIMESTAMP
                """,
                (supplier_id, node_hash, depth),
            )

    def reset_crawl_state(self, supplier_id: Optional[int] = None) -> None:
        with self.get_conn() as conn:
            if supplier_id is not None:
                conn.execute("DELETE FROM crawl_state WHERE supplier_id = ?", (supplier_id,))
            else:
                conn.execute("DELETE FROM crawl_state")

    def get_comparison(
        self, keyword: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        query = """
        SELECT
            p.id as product_id,
            p.canonical_name,
            p.spec_key,
            p.brand,
            p.specs_json,
            s.id as supplier_id,
            s.username as supplier_username,
            s.name as supplier_name,
            o.price,
            o.currency,
            o.in_stock,
            o.duration,
            o.crawled_at
        FROM products p
        JOIN offers o ON p.id = o.product_id
        JOIN suppliers s ON o.supplier_id = s.id
        """
        params: List[Any] = []
        if keyword:
            query += " WHERE p.canonical_name LIKE ? OR p.raw_name LIKE ? OR p.brand LIKE ?"
            like_pat = f"%{keyword}%"
            params.extend([like_pat, like_pat, like_pat])

        query += " ORDER BY p.canonical_name ASC, p.spec_key ASC, o.price ASC"

        with self.get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_all_canonical_products(self) -> List[Dict[str, Any]]:
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT id, raw_name, canonical_name, brand, model, spec_key, specs_json FROM products"
            ).fetchall()
            return [dict(r) for r in rows]
