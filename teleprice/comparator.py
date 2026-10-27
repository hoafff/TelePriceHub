"""Price comparison and supplier ranking engine.

Computes lowest price, supplier ranking, price delta, and markdown comparison tables.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class SupplierRanking:
    rank: int
    supplier_name: str
    supplier_username: str
    price: float
    currency: str
    in_stock: bool
    duration: str
    delta_amount: float
    delta_percent: float


@dataclass
class ProductComparison:
    canonical_name: str
    spec_key: str
    brand: str
    min_price: float
    max_price: float
    currency: str
    rankings: List[SupplierRanking]


class PriceComparator:
    @staticmethod
    def compare(offers: List[Dict[str, Any]]) -> List[ProductComparison]:
        """Groups raw database offer rows into structured ProductComparison objects."""
        grouped: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
        for o in offers:
            key = (o["canonical_name"], o["spec_key"])
            grouped[key].append(o)

        results: List[ProductComparison] = []

        for (canonical_name, spec_key), rows in grouped.items():
            # Sort by price ascending
            sorted_rows = sorted(rows, key=lambda r: float(r["price"]))
            if not sorted_rows:
                continue

            min_price = float(sorted_rows[0]["price"])
            max_price = float(sorted_rows[-1]["price"])
            currency = sorted_rows[0].get("currency", "VND")
            brand = sorted_rows[0].get("brand", "")

            rankings: List[SupplierRanking] = []
            for idx, r in enumerate(sorted_rows, start=1):
                p = float(r["price"])
                delta_amt = p - min_price
                delta_pct = (delta_amt / min_price * 100.0) if min_price > 0 else 0.0

                rankings.append(
                    SupplierRanking(
                        rank=idx,
                        supplier_name=r.get("supplier_name") or r.get("supplier_username", "Unknown"),
                        supplier_username=r.get("supplier_username", ""),
                        price=p,
                        currency=r.get("currency", currency),
                        in_stock=bool(r.get("in_stock", 1)),
                        duration=r.get("duration", ""),
                        delta_amount=delta_amt,
                        delta_percent=delta_pct,
                    )
                )

            results.append(
                ProductComparison(
                    canonical_name=canonical_name,
                    spec_key=spec_key,
                    brand=brand,
                    min_price=min_price,
                    max_price=max_price,
                    currency=currency,
                    rankings=rankings,
                )
            )

        return results

    @staticmethod
    def format_markdown_table(comp: ProductComparison) -> str:
        """Formats a comparison object into a clean Markdown table."""
        lines = [
            f"### 📊 Bảng so sánh: {comp.canonical_name}",
            f"**Thông số/Gói:** `{comp.spec_key}` | **Giá rẻ nhất:** {comp.min_price:,.0f} {comp.currency}",
            "",
            "| Top | Nhà cung cấp | Giá | Chênh lệch | Tình trạng |",
            "| :---: | :--- | :---: | :---: | :---: |",
        ]

        for r in comp.rankings:
            delta_str = (
                "Rẻ nhất"
                if r.rank == 1
                else f"+{r.delta_amount:,.0f} {r.currency} (+{r.delta_percent:.1f}%)"
            )
            stock_str = "✅ Sẵn hàng" if r.in_stock else "❌ Hết hàng"
            supp_link = f"[{r.supplier_name}](https://t.me/{r.supplier_username.lstrip('@')})"
            lines.append(
                f"| #{r.rank} | {supp_link} | {r.price:,.0f} {r.currency} | {delta_str} | {stock_str} |"
            )

        return "\n".join(lines)
