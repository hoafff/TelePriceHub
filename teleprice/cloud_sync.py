"""Upload fresh per-run offer snapshot to private Cloudflare Worker D1 storage."""
import json
import os
import urllib.request
from teleprice.db import Database


def publish(db: Database) -> int:
    url = os.environ.get("WORKER_SYNC_URL", "").strip().rstrip("/")
    token = os.environ.get("SYNC_TOKEN", "").strip()
    if not url or not token:
        raise RuntimeError("WORKER_SYNC_URL and SYNC_TOKEN are required; refuse to silently lose price data")
    offers = db.get_comparison()
    rows = [
        {"supplier": o["supplier_username"], "canonical_name": o["canonical_name"],
         "spec_key": o["spec_key"], "raw_name": o["canonical_name"],
         "price": float(o["price"]), "currency": o["currency"],
         "in_stock": int(o["in_stock"])}
        for o in offers
    ]
    if not rows:
        raise RuntimeError("Crawl produced no offers; refusing empty cloud synchronization")
    count = 0
    for start in range(0, len(rows), 60):
        body = json.dumps({"offers": rows[start:start+60]}, ensure_ascii=False).encode()
        req = urllib.request.Request(url+"/ingest", data=body, method="POST",
            headers={"Content-Type":"application/json","Authorization":"Bearer "+token})
        with urllib.request.urlopen(req, timeout=40) as response:
            payload = json.loads(response.read().decode())
            if not payload.get("ok"):
                raise RuntimeError("Cloud synchronization rejected a batch")
        count += min(60,len(rows)-start)
    return count
