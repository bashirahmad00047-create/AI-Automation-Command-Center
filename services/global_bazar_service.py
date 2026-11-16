"""
Global-Bazar-Core Integration Service for BashFlow.
Connects BashFlow AI Automation Command Center to Global-Bazar-Core (FastAPI & SQLite)
for automated WhatsApp inventory synchronization, order creation, and shop hisaab-kitaab.
Operates seamlessly in dual-mode (REST API with instant SQLite fallback).
"""

import os
import re
import json
import sqlite3
import logging
import datetime
from typing import List, Dict, Any, Optional, Tuple, Union

logger = logging.getLogger("opsflow.global_bazar")


class GlobalBazarService:
    """Enterprise connector between BashFlow WhatsApp automation and Global-Bazar-Core ERP."""

    DEFAULT_API_URL = os.environ.get("GLOBAL_BAZAR_API_URL", "http://127.0.0.1:8000")
    DEFAULT_DB_PATH = os.environ.get(
        "GLOBAL_BAZAR_DB_PATH",
        os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "Global-Bazar-Core", "global_bazar.db")
        )
    )

    @classmethod
    def get_db_path(cls) -> str:
        """Resolves absolute path to Global-Bazar-Core's SQLite database."""
        candidates = [
            cls.DEFAULT_DB_PATH,
            r"C:\Users\It Hub\Global-Bazar-Core\global_bazar.db",
            "/root/Global-Bazar-Core/global_bazar.db",
            os.path.abspath(os.path.join(os.getcwd(), "..", "Global-Bazar-Core", "global_bazar.db"))
        ]
        for p in candidates:
            if p and os.path.exists(p):
                return os.path.abspath(p)
        return cls.DEFAULT_DB_PATH

    @classmethod
    def get_db_connection(cls) -> sqlite3.Connection:
        """Creates a SQLite connection with Row factory for dict-like access."""
        db_path = cls.get_db_path()
        conn = sqlite3.connect(db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def is_api_online(cls) -> bool:
        """Checks if Global-Bazar-Core FastAPI server is running on port 8000."""
        try:
            import urllib.request
            req = urllib.request.Request(f"{cls.DEFAULT_API_URL}/health", headers={"User-Agent": "BashFlow-Core/1.0"})
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                return resp.status == 200
        except Exception:
            return False

    # =========================================================================
    # VENDORS
    # =========================================================================

    @classmethod
    def get_vendors(cls) -> List[Dict[str, Any]]:
        """Retrieves active shop/vendor profiles from Global-Bazar-Core."""
        try:
            with cls.get_db_connection() as conn:
                c = conn.cursor()
                rows = c.execute("SELECT * FROM vendors WHERE is_active = 1 ORDER BY id ASC").fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"[GlobalBazar] Failed to fetch vendors: {e}")
            return []

    @classmethod
    def get_default_vendor_id(cls) -> int:
        """Returns the primary vendor ID (default 1)."""
        vendors = cls.get_vendors()
        if vendors:
            return vendors[0]["id"]
        return 1

    @classmethod
    def find_or_create_vendor(
        cls,
        name: str,
        phone: str,
        owner_name: Optional[str] = None,
        address: Optional[str] = None
    ) -> Dict[str, Any]:
        """Finds an existing vendor by phone or creates a new one in Global-Bazar-Core."""
        try:
            clean_p = str(phone or "").strip()
            digits = "".join(filter(str.isdigit, clean_p))[-10:]
            with cls.get_db_connection() as conn:
                c = conn.cursor()
                if digits:
                    row = c.execute("SELECT * FROM vendors WHERE phone = ? OR phone LIKE ?", (clean_p, f"%{digits}%")).fetchone()
                else:
                    row = c.execute("SELECT * FROM vendors WHERE phone = ?", (clean_p,)).fetchone()
                if row:
                    return dict(row)
                row = c.execute("SELECT * FROM vendors WHERE name = ?", (name.strip(),)).fetchone()
                if row:
                    return dict(row)

                now_iso = datetime.datetime.utcnow().isoformat()
                c.execute("""
                    INSERT INTO vendors (name, owner_name, phone, address, currency, is_active, created_at)
                    VALUES (?, ?, ?, ?, 'PKR', 1, ?)
                """, (name.strip(), owner_name or name.strip(), clean_p, address or "Chitral / Pakistan", now_iso))
                conn.commit()
                new_id = c.lastrowid
                new_row = c.execute("SELECT * FROM vendors WHERE id = ?", (new_id,)).fetchone()
                logger.info(f"[GlobalBazar] Created new vendor #{new_id}: '{name}' ({clean_p})")
                return dict(new_row) if new_row else {"id": new_id, "name": name, "phone": clean_p}
        except Exception as e:
            logger.error(f"[GlobalBazar] Error in find_or_create_vendor: {e}")
            return {"id": 1, "name": name, "phone": phone}

    @classmethod
    def get_vendor_by_id(cls, vendor_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves a single vendor profile by integer ID."""
        try:
            with cls.get_db_connection() as conn:
                c = conn.cursor()
                row = c.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"[GlobalBazar] Failed to get vendor {vendor_id}: {e}")
            return None

    @classmethod
    def get_vendor_by_phone(cls, phone: str) -> Optional[Dict[str, Any]]:
        """Retrieves an existing vendor profile by phone number or creates default if not found."""
        try:
            clean_p = str(phone or "").strip()
            digits = "".join(filter(str.isdigit, clean_p))[-10:]
            with cls.get_db_connection() as conn:
                c = conn.cursor()
                if digits:
                    row = c.execute("SELECT * FROM vendors WHERE phone = ? OR phone LIKE ?", (clean_p, f"%{digits}%")).fetchone()
                else:
                    row = c.execute("SELECT * FROM vendors WHERE phone = ?", (clean_p,)).fetchone()
                if row:
                    return dict(row)
            return cls.find_or_create_vendor(name="Dukan Owner", phone=phone)
        except Exception as e:
            logger.error(f"[GlobalBazar] Error in get_vendor_by_phone: {e}")
            return {"id": 1, "name": "Dukan Owner", "phone": phone}

    @classmethod
    def get_vendor_dashboard_data(cls, vendor_id: int) -> Dict[str, Any]:
        """Fetches complete profile, inventory, and stats for a specific vendor's mobile portal."""
        vendor = cls.get_vendor_by_id(vendor_id)
        if not vendor:
            return {}

        products = cls.get_products(vendor_id=vendor_id)
        total_products = len(products)
        total_stock = sum(int(p.get("stock") or 0) for p in products)
        total_inventory_value = sum(
            float(p.get("price") or 0.0) * (int(p.get("stock") or 1) if int(p.get("stock") or 0) > 0 else 1)
            for p in products
        )

        today_str = datetime.date.today().isoformat()
        today_slash = today_str.replace("-", "/")
        month_str = datetime.date.today().strftime("%Y-%m")
        month_slash = month_str.replace("-", "/")

        with cls.get_db_connection() as conn:
            c = conn.cursor()
            sales_row = c.execute(
                "SELECT COALESCE(SUM(amount), 0) as total_sales FROM ledger WHERE vendor_id = ? AND entry_type = 'sale'",
                (vendor_id,)
            ).fetchone()
            total_sales = float(sales_row["total_sales"]) if sales_row else 0.0

            # Daily sales & orders (today)
            today_orders_row = c.execute(
                "SELECT COUNT(*) as count, COALESCE(SUM(total_amount), 0.0) as total FROM orders WHERE vendor_id = ? AND (created_at LIKE ? OR created_at LIKE ?)",
                (vendor_id, f"{today_str}%", f"{today_slash}%")
            ).fetchone()
            today_ledger_row = c.execute(
                "SELECT COUNT(*) as count, COALESCE(SUM(amount), 0.0) as total FROM ledger WHERE vendor_id = ? AND entry_type = 'sale' AND (entry_date = ? OR created_at LIKE ?)",
                (vendor_id, today_str, f"{today_str}%")
            ).fetchone()
            today_orders_count = int(today_orders_row["count"] or 0) + int(today_ledger_row["count"] or 0)
            today_sales_total = float(max(float(today_orders_row["total"] or 0.0), float(today_ledger_row["total"] or 0.0)))

            # Monthly sales & orders (current month)
            month_orders_row = c.execute(
                "SELECT COUNT(*) as count, COALESCE(SUM(total_amount), 0.0) as total FROM orders WHERE vendor_id = ? AND (created_at LIKE ? OR created_at LIKE ?)",
                (vendor_id, f"{month_str}%", f"{month_slash}%")
            ).fetchone()
            month_ledger_row = c.execute(
                "SELECT COUNT(*) as count, COALESCE(SUM(amount), 0.0) as total FROM ledger WHERE vendor_id = ? AND entry_type = 'sale' AND (entry_date LIKE ? OR created_at LIKE ?)",
                (vendor_id, f"{month_str}%", f"{month_str}%")
            ).fetchone()
            month_orders_count = int(month_orders_row["count"] or 0) + int(month_ledger_row["count"] or 0)
            month_sales_total = float(max(float(month_orders_row["total"] or 0.0), float(month_ledger_row["total"] or 0.0)))

            # Expenses (today, monthly, total)
            today_exp_row = c.execute(
                "SELECT COALESCE(SUM(amount), 0.0) as total FROM ledger WHERE vendor_id = ? AND entry_type in ('expense', 'debit') AND (entry_date = ? OR created_at LIKE ?)",
                (vendor_id, today_str, f"{today_str}%")
            ).fetchone()
            today_expenses_total = float(today_exp_row["total"] or 0.0)

            month_exp_row = c.execute(
                "SELECT COALESCE(SUM(amount), 0.0) as total FROM ledger WHERE vendor_id = ? AND entry_type in ('expense', 'debit') AND (entry_date LIKE ? OR created_at LIKE ?)",
                (vendor_id, f"{month_str}%", f"{month_str}%")
            ).fetchone()
            month_expenses_total = float(month_exp_row["total"] or 0.0)

            total_exp_row = c.execute(
                "SELECT COALESCE(SUM(amount), 0.0) as total FROM ledger WHERE vendor_id = ? AND entry_type in ('expense', 'debit')",
                (vendor_id,)
            ).fetchone()
            total_expenses_total = float(total_exp_row["total"] or 0.0)

            # Low stock count (stock <= 3)
            low_stock_count = sum(1 for p in products if int(p.get("stock") or 0) <= 3)

            # Total profit calculation:
            # Margin of 25% on recorded sales minus monthly expenses
            gross_profit = month_sales_total * 0.25
            total_profit = max(0.0, gross_profit - month_expenses_total)

            orders_rows = c.execute(
                "SELECT * FROM orders WHERE vendor_id = ? ORDER BY id DESC LIMIT 25",
                (vendor_id,)
            ).fetchall()
            orders = [dict(r) for r in orders_rows]

            ledger_rows = c.execute(
                "SELECT * FROM ledger WHERE vendor_id = ? ORDER BY id DESC LIMIT 25",
                (vendor_id,)
            ).fetchall()
            ledger_entries = [dict(r) for r in ledger_rows]

        return {
            "vendor": vendor,
            "products": products,
            "total_products": total_products,
            "total_stock": total_stock,
            "total_inventory_value": total_inventory_value,
            "total_sales": total_sales,
            "today_sales_total": today_sales_total,
            "today_orders_count": today_orders_count,
            "month_sales_total": month_sales_total,
            "month_orders_count": month_orders_count,
            "today_expenses_total": today_expenses_total,
            "month_expenses_total": month_expenses_total,
            "total_expenses_total": total_expenses_total,
            "expenses": total_expenses_total,
            "today_expenses": today_expenses_total,
            "today_sales": today_sales_total,
            "today_orders": today_orders_count,
            "month_sales": month_sales_total,
            "month_orders": month_orders_count,
            "total_profit": total_profit,
            "profit_margin_pct": 25.0,
            "low_stock_count": low_stock_count,
            "orders": orders,
            "ledger_entries": ledger_entries
        }

    @classmethod
    def format_vendor_hisab_summary(cls, vendor_id: int, token: str) -> str:
        """Formats real-time shop hisab-kitab summary for WhatsApp reply."""
        data = cls.get_vendor_dashboard_data(vendor_id)
        vendor = data.get("vendor") or {}
        shop_name = vendor.get("name") or "Chitral Shahi Bazar"
        total_items = data.get("total_products", 0)
        inv_val = data.get("total_inventory_value", 0.0)
        today_sales = data.get("today_sales_total", 0.0)
        today_orders = data.get("today_orders_count", 0)
        month_sales = data.get("month_sales_total", 0.0)
        month_orders = data.get("month_orders_count", 0)
        base_domain = os.environ.get("VENDOR_PORTAL_BASE_URL", "http://66.45.230.232:5000")
        portal_url = f"{base_domain}/vendor/auth/{token}"

        return (
            f"🏪 *Dukan:* {shop_name}\n"
            f"📦 *Total Saman (Inventory):* {total_items} items (Worth PKR {inv_val:,.0f})\n"
            f"💰 *Aaj Ki Sale (Daily Sale):* PKR {today_sales:,.0f} ({today_orders} orders)\n"
            f"📈 *Mahine Ki Sale (Monthly Sale):* PKR {month_sales:,.0f} ({month_orders} orders)\n"
            f"🏪 *Aapki Online Dukaan Tayyar Hai!*\n"
            f"🔗 *Dukan & Khata Dashboard Link:* {portal_url}"
        )

    MAGIC_TOKEN_SECRET = os.environ.get("VENDOR_TOKEN_SECRET", "bashflow-vendor-magic-portal-secret-key-2026")

    @classmethod
    def generate_vendor_magic_token(cls, vendor_id: int, phone: Optional[str] = None, expires_in_seconds: int = 86400 * 7) -> str:
        """Generates a secure, short-lived magic link token for vendor authentication."""
        from itsdangerous import URLSafeTimedSerializer
        clean_phone = str(phone or "").strip()
        if not clean_phone:
            v = cls.get_vendor_by_id(vendor_id) or {}
            clean_phone = str(v.get("phone") or "923471000668").strip()
        s = URLSafeTimedSerializer(cls.MAGIC_TOKEN_SECRET, salt="vendor-magic-link")
        return s.dumps({"vendor_id": int(vendor_id), "phone": clean_phone})

    @classmethod
    def verify_vendor_magic_token(cls, token: str, max_age_seconds: int = 86400 * 7) -> Optional[Dict[str, Any]]:
        """Verifies vendor magic link token and returns decoded payload with vendor profile."""
        from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
        s = URLSafeTimedSerializer(cls.MAGIC_TOKEN_SECRET, salt="vendor-magic-link")
        try:
            data = s.loads(token, max_age=max_age_seconds)
            v_id = data.get("vendor_id")
            if v_id:
                vendor = cls.get_vendor_by_id(v_id)
                if vendor:
                    return {"vendor": vendor, "payload": data}
            return None
        except (SignatureExpired, BadSignature, Exception) as e:
            logger.warning(f"Vendor token verification notice: {e}")
            return None

    # =========================================================================
    # INVENTORY & PRODUCTS
    # =========================================================================

    @classmethod
    def get_products(
        cls,
        vendor_id: Optional[int] = None,
        query: Optional[str] = None,
        category: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        in_stock_only: bool = False
    ) -> List[Dict[str, Any]]:
        """Retrieves inventory products with optional multi-vendor filtering."""
        try:
            with cls.get_db_connection() as conn:
                c = conn.cursor()
                sql = "SELECT * FROM products WHERE 1=1"
                params = []

                if vendor_id is not None:
                    sql += " AND vendor_id = ?"
                    params.append(vendor_id)
                if query and query.strip():
                    sql += " AND (title LIKE ? OR description LIKE ?)"
                    q_like = f"%{query.strip()}%"
                    params.extend([q_like, q_like])
                if category and category.strip():
                    sql += " AND category LIKE ?"
                    params.append(f"%{category.strip()}%")
                if min_price is not None:
                    sql += " AND price >= ?"
                    params.append(min_price)
                if max_price is not None:
                    sql += " AND price <= ?"
                    params.append(max_price)
                if in_stock_only:
                    sql += " AND stock > 0"

                sql += " ORDER BY created_at DESC"
                rows = c.execute(sql, params).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"[GlobalBazar] Failed to query products: {e}")
            return []

    @classmethod
    def get_product_by_id(cls, product_id: int) -> Optional[Dict[str, Any]]:
        """Finds a single product by its integer ID."""
        try:
            with cls.get_db_connection() as conn:
                c = conn.cursor()
                row = c.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"[GlobalBazar] Failed to get product {product_id}: {e}")
            return None

    @classmethod
    def find_product_by_title_or_sku(cls, search_term: str, vendor_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Intelligently matches a product by name, keywords, or SKU."""
        if not search_term or not str(search_term).strip():
            return None
        clean = str(search_term).strip().lower()
        products = cls.get_products(vendor_id=vendor_id)
        # 1. Exact match on title
        for p in products:
            if clean == p["title"].strip().lower():
                return p
        # 2. In title or description
        for p in products:
            if clean in p["title"].strip().lower() or clean in str(p.get("description") or "").lower():
                return p
        # 3. Partial word tokens match
        tokens = [t for t in clean.split() if len(t) > 2]
        if tokens:
            for p in products:
                title_lower = p["title"].lower()
                if any(t in title_lower for t in tokens):
                    return p
        return None

    @classmethod
    def update_product_stock(
        cls,
        product_id: int,
        quantity_delta: int = 0,
        new_stock: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Updates product stock (supports absolute stock or relative delta like -1)."""
        try:
            with cls.get_db_connection() as conn:
                c = conn.cursor()
                curr = c.execute("SELECT stock FROM products WHERE id = ?", (product_id,)).fetchone()
                if not curr:
                    return None
                current_stock = curr["stock"]

                if new_stock is not None:
                    updated_stock = max(0, int(new_stock))
                else:
                    updated_stock = max(0, current_stock + int(quantity_delta))

                c.execute("UPDATE products SET stock = ? WHERE id = ?", (updated_stock, product_id))
                conn.commit()

                updated_row = c.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
                logger.info(f"[GlobalBazar] Stock updated for Product #{product_id}: {current_stock} -> {updated_stock}")
                return dict(updated_row) if updated_row else None
        except Exception as e:
            logger.error(f"[GlobalBazar] Failed to update stock for product {product_id}: {e}")
            return None

    @classmethod
    def enhance_product_image_studio(cls, image_bytes: bytes) -> bytes:
        """Applies PIL studio enhancement: square frame, sharpness, contrast, brightness, auto-leveling."""
        try:
            from PIL import Image, ImageEnhance, ImageOps
            import io

            if not image_bytes or len(image_bytes) < 32:
                return image_bytes

            orig = Image.open(io.BytesIO(image_bytes))
            try:
                orig = ImageOps.exif_transpose(orig)
            except Exception:
                pass

            if orig.mode in ("RGBA", "LA", "P"):
                rgb_canvas = Image.new("RGB", orig.size, (255, 255, 255))
                if orig.mode == "P":
                    orig = orig.convert("RGBA")
                rgb_canvas.paste(orig, mask=orig.split()[-1] if orig.mode in ("RGBA", "LA") else None)
                orig = rgb_canvas
            elif orig.mode != "RGB":
                orig = orig.convert("RGB")

            # 1. Auto-level lighting
            try:
                orig = ImageOps.autocontrast(orig, cutoff=1)
            except Exception:
                pass

            # 2. Enhancements: Brightness 1.08, Contrast 1.15, Sharpness 1.4
            orig = ImageEnhance.Brightness(orig).enhance(1.08)
            orig = ImageEnhance.Contrast(orig).enhance(1.15)
            orig = ImageEnhance.Sharpness(orig).enhance(1.4)

            # 3. Auto-crop/pad to clean square studio frame with subtle background
            w, h = orig.size
            max_side = max(w, h)
            target_side = max(max_side, 640)
            studio_bg = Image.new("RGB", (target_side, target_side), (248, 249, 250))
            paste_x = (target_side - w) // 2
            paste_y = (target_side - h) // 2
            studio_bg.paste(orig, (paste_x, paste_y))

            out_buf = io.BytesIO()
            studio_bg.save(out_buf, format="JPEG", quality=92, optimize=True)
            enhanced = out_buf.getvalue()
            return enhanced if len(enhanced) > 32 else image_bytes
        except Exception as e:
            logger.warning(f"[Studio Enhancement Notice]: {e}")
            return image_bytes

    @classmethod
    def analyze_product_vision(
        cls,
        image_bytes: Optional[bytes],
        caption: Optional[str] = None
    ) -> Optional[Dict[str, str]]:
        """Passes image bytes + vendor caption to Gemini Vision to recognize actual product item, category and description."""
        if not image_bytes or len(image_bytes) < 32:
            return None

        clean_cap = str(caption or "").strip()
        cap_no_price = re.sub(r'(?i)\b(?:rs\.?|pkr|price|rate|cost)\s*[:=]?\s*[\d,]+(?:\.\d+)?|\b[\d,]+(?:\.\d+)?\s*(?:rs|pkr|rupees|rupay)\b', '', clean_cap).strip()

        api_key = (
            os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("GOOGLE_GENAI_API_KEY")
        )
        if not api_key:
            try:
                from dotenv import load_dotenv
                load_dotenv()
                api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            except Exception:
                pass

        if not api_key:
            return None

        prompt = (
            "You are an expert e-commerce cataloger. Inspect the actual product object in the image and the optional vendor caption.\n"
            f"Vendor caption: '{cap_no_price}'\n\n"
            "Respond ONLY with a valid JSON object with these exact keys:\n"
            "{\n"
            '  "title": "<specific product name in English/Roman Urdu, e.g. Heavy Duty Brass Security Padlock>",\n'
            '  "category": "<accurate category choosing strictly from: Electronics | Hardware & Tools | Apparel & Accessories | Desi & Biryani | Fast Food & Burgers | Chitrali Crafts | Dry Fruits | Home & Kitchen>",\n'
            '  "description": "<2 crisp sentences describing the exact item visible in the photo, its quality, and practical use without mentioning any price>"\n'
            "}\n"
            "Do not include markdown code fences (```json), just the raw JSON object."
        )

        for model_name in ("gemini-2.5-flash", "gemini-1.5-flash"):
            try:
                from google import genai
                from google.genai import types
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model=model_name,
                    contents=[
                        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                        prompt
                    ],
                    config={"response_mime_type": "application/json"}
                )
                if response and response.text:
                    clean_txt = response.text.strip().replace("```json", "").replace("```", "").strip()
                    parsed = json.loads(clean_txt)
                    if isinstance(parsed, dict) and parsed.get("title"):
                        desc = str(parsed.get("description") or "").strip()
                        desc = re.sub(r'(?i)\b(?:rs\.?|pkr|price|rate|cost)\s*[:=]?\s*[\d,]+(?:\.\d+)?|\b[\d,]+(?:\.\d+)?\s*(?:rs|pkr|rupees|rupay)\b', '', desc).strip()
                        parsed["description"] = desc
                        return parsed
            except Exception as e1:
                logger.debug(f"[Vision AI {model_name} google-genai]: {e1}")

            try:
                import google.generativeai as genai_legacy
                genai_legacy.configure(api_key=api_key)
                m = genai_legacy.GenerativeModel(model_name)
                res = m.generate_content(
                    [{'mime_type': 'image/jpeg', 'data': image_bytes}, prompt],
                    request_options={"timeout": 8.0}
                )
                if res and res.text:
                    clean_txt = res.text.strip().replace("```json", "").replace("```", "").strip()
                    parsed = json.loads(clean_txt)
                    if isinstance(parsed, dict) and parsed.get("title"):
                        desc = str(parsed.get("description") or "").strip()
                        desc = re.sub(r'(?i)\b(?:rs\.?|pkr|price|rate|cost)\s*[:=]?\s*[\d,]+(?:\.\d+)?|\b[\d,]+(?:\.\d+)?\s*(?:rs|pkr|rupees|rupay)\b', '', desc).strip()
                        parsed["description"] = desc
                        return parsed
            except Exception as e2:
                logger.debug(f"[Vision AI {model_name} google.generativeai]: {e2}")

            try:
                import base64
                import requests
                b64_img = base64.b64encode(image_bytes).decode("utf-8")
                rest_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                body = {
                    "contents": [{
                        "parts": [
                            {"inline_data": {"mime_type": "image/jpeg", "data": b64_img}},
                            {"text": prompt}
                        ]
                    }],
                    "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}
                }
                r = requests.post(rest_url, json=body, timeout=8.0)
                if r.status_code == 200:
                    data = r.json()
                    candidates = data.get("candidates") or []
                    if candidates:
                        text_part = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        clean_txt = text_part.strip().replace("```json", "").replace("```", "").strip()
                        parsed = json.loads(clean_txt)
                        if isinstance(parsed, dict) and parsed.get("title"):
                            desc = str(parsed.get("description") or "").strip()
                            desc = re.sub(r'(?i)\b(?:rs\.?|pkr|price|rate|cost)\s*[:=]?\s*[\d,]+(?:\.\d+)?|\b[\d,]+(?:\.\d+)?\s*(?:rs|pkr|rupees|rupay)\b', '', desc).strip()
                            parsed["description"] = desc
                            return parsed
            except Exception as e3:
                logger.debug(f"[Vision AI {model_name} REST]: {e3}")

        return None

    @classmethod
    def add_product(
        cls,
        title: str,
        price: float,
        stock: int = 10,
        vendor_id: Optional[int] = None,
        category: str = "General",
        description: str = "",
        image_url: Optional[str] = None,
        cost_price: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """Creates a new product in Global-Bazar-Core inventory."""
        try:
            v_id = vendor_id or cls.get_default_vendor_id()
            now_iso = datetime.datetime.utcnow().isoformat()
            c_price = float(cost_price) if cost_price is not None else float(price * 0.75)
            with cls.get_db_connection() as conn:
                c = conn.cursor()
                c.execute("""
                    INSERT INTO products (vendor_id, title, description, category, price, cost_price, stock, image_url, ai_image_url, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (v_id, title.strip(), description.strip(), category.strip(), float(price), c_price, int(stock), image_url, image_url, now_iso))
                conn.commit()
                new_id = c.lastrowid
                row = c.execute("SELECT * FROM products WHERE id = ?", (new_id,)).fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"[GlobalBazar] Failed to add product: {e}")
            return None

    @classmethod
    def sell_one_product(cls, vendor_id: int, product_id: int) -> Optional[Dict[str, Any]]:
        """Deducts 1 stock from product and records sale into ledger and daily sale immediately."""
        try:
            with cls.get_db_connection() as conn:
                c = conn.cursor()
                prod_row = c.execute("SELECT * FROM products WHERE id = ? AND (vendor_id = ? OR vendor_id IS NULL)", (product_id, vendor_id)).fetchone()
                if not prod_row:
                    return None
                prod = dict(prod_row)
                current_stock = max(0, int(prod.get("stock") or 0))
                new_stock = max(0, current_stock - 1)
                c.execute("UPDATE products SET stock = ? WHERE id = ?", (new_stock, product_id))

                sale_price = float(prod.get("price") or 0.0)
                t_date = datetime.date.today().isoformat()
                now_iso = datetime.datetime.utcnow().isoformat()
                c.execute("""
                    INSERT INTO ledger (vendor_id, entry_type, amount, category, description, entry_date, created_at)
                    VALUES (?, 'sale', ?, 'quick_sell', ?, ?, ?)
                """, (vendor_id, sale_price, f"Sell 1 Counter: {prod.get('title')}", t_date, now_iso))
                conn.commit()
                prod["stock"] = new_stock
                return prod
        except Exception as e:
            logger.error(f"[GlobalBazar] sell_one_product failed: {e}")
            return None

    @classmethod
    def update_product(
        cls,
        product_id: int,
        vendor_id: int,
        title: str,
        price: float,
        cost_price: float,
        stock: int,
        category: str
    ) -> Optional[Dict[str, Any]]:
        """Updates product details."""
        try:
            with cls.get_db_connection() as conn:
                c = conn.cursor()
                c.execute("""
                    UPDATE products
                    SET title = ?, price = ?, cost_price = ?, stock = ?, category = ?
                    WHERE id = ? AND (vendor_id = ? OR vendor_id IS NULL)
                """, (title.strip(), float(price), float(cost_price), int(stock), category.strip(), product_id, vendor_id))
                conn.commit()
                row = c.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"[GlobalBazar] update_product failed: {e}")
            return None

    @classmethod
    def delete_product(cls, product_id: int, vendor_id: int) -> bool:
        """Deletes a product."""
        try:
            with cls.get_db_connection() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM products WHERE id = ? AND (vendor_id = ? OR vendor_id IS NULL)", (product_id, vendor_id))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"[GlobalBazar] delete_product failed: {e}")
            return False

    @classmethod
    def cleanup_duplicate_products(cls, vendor_id: Optional[int] = None) -> int:
        """Cleans up duplicate products (e.g. duplicate padlock/artisan/studio items)."""
        try:
            with cls.get_db_connection() as conn:
                c = conn.cursor()
                sql = "SELECT id, title, price, category, created_at, vendor_id FROM products"
                params = []
                if vendor_id:
                    sql += " WHERE vendor_id = ?"
                    params.append(vendor_id)
                sql += " ORDER BY id ASC"
                rows = [dict(r) for r in c.execute(sql, params).fetchall()]

                deleted_ids = []
                seen_keys = {}
                for r in rows:
                    t_clean = r["title"].strip().lower()
                    if t_clean in ("artisan store product", "studio collection elegance edition"):
                        key = (r["vendor_id"], r["price"], "dummy")
                    else:
                        key = (r["vendor_id"], r["price"], t_clean)

                    if key in seen_keys:
                        deleted_ids.append(r["id"])
                    else:
                        seen_keys[key] = r["id"]

                if deleted_ids:
                    c.execute(f"DELETE FROM products WHERE id IN ({','.join(['?']*len(deleted_ids))})", deleted_ids)
                    conn.commit()
                    logger.info(f"[GlobalBazar] Cleaned up {len(deleted_ids)} duplicate products: {deleted_ids}")
                return len(deleted_ids)
        except Exception as e:
            logger.error(f"[GlobalBazar] cleanup_duplicate_products error: {e}")
            return 0

    @classmethod
    def process_ai_catalog_direct(
        cls,
        image_bytes: Optional[bytes] = None,
        caption: Optional[str] = None,
        price: Optional[float] = None,
        vendor_id: Optional[int] = None,
        vendor_phone: Optional[str] = None,
        vendor_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Direct offline/in-process engine for AI cataloging with Studio Enhancement and Real Vision AI.
        Saves enhanced image to static uploads, recognizes product item, and persists ONCE to database.
        """
        import uuid
        import re
        import json

        clean_cap = str(caption or "").strip()
        extracted_price = price
        if not extracted_price and clean_cap:
            p_match = re.search(r'(?:rs\.?|pkr)?\s*[:=]?\s*([\d,]+(?:\.\d+)?)', clean_cap, re.IGNORECASE)
            if p_match:
                try:
                    extracted_price = float(p_match.group(1).replace(",", ""))
                except ValueError:
                    pass

        final_price = float(extracted_price) if extracted_price else 2500.0

        # Step A: Studio Image Enhancement (PIL auto-contrast, brightness, sharpness, studio square frame)
        enhanced_bytes = cls.enhance_product_image_studio(image_bytes) if image_bytes else None
        final_image_bytes = enhanced_bytes or image_bytes

        # Step B: Real Vision AI Title, Category & Description
        vision_res = cls.analyze_product_vision(final_image_bytes, caption=clean_cap) if final_image_bytes else None
        if vision_res and vision_res.get("title"):
            title = str(vision_res["title"]).strip()
            category = str(vision_res.get("category") or "Hardware & Tools").strip()
            description = str(vision_res.get("description") or "Quality product available on Chitral & Global Bazar.").strip()
        else:
            # Fallback title if vision AI is unreachable - extract meaningful title from caption without prices
            clean_title = re.sub(r'(?i)\b(?:rs\.?|pkr|price|rate|cost)\s*[:=]?\s*[\d,]+(?:\.\d+)?|\b[\d,]+(?:\.\d+)?\s*(?:rs|pkr|rupees|rupay)\b', '', clean_cap).strip()
            clean_title = re.sub(r'(?i)\b(add|sell|price|for|this|product|item)\b', '', clean_title).strip()
            if clean_title and len(clean_title) >= 3:
                title = clean_title.title()
            else:
                title = "Store Inventory Item"
            category = "General"
            description = f"Quality product available on Chitral & Global Bazar."

        # Strip price string out of description so it doesn't repeat
        description = re.sub(r'(?i)\b(?:rs\.?|pkr|price|rate|cost)\s*[:=]?\s*[\d,]+(?:\.\d+)?|\b[\d,]+(?:\.\d+)?\s*(?:rs|pkr|rupees|rupay)\b', '', description).strip()
        if not description:
            description = f"Quality {title} available for immediate order on Chitral & Global Bazar."

        # Multi-vendor resolution if vendor_id not given
        target_vendor_id = vendor_id
        resolved_vendor = None
        if not target_vendor_id and vendor_phone:
            v_obj = cls.find_or_create_vendor(
                name=vendor_name or f"Shop {vendor_phone[-4:]}",
                phone=vendor_phone,
                owner_name=vendor_name or "Vendor"
            )
            target_vendor_id = v_obj.get("id")
            resolved_vendor = v_obj

        # Save enhanced image file to static/uploads
        unique_id = uuid.uuid4().hex
        filename = f"catalog_{unique_id}.jpg"
        uploads_dir = os.path.abspath(os.path.join(os.path.dirname(cls.get_db_path()), "static", "uploads"))
        os.makedirs(uploads_dir, exist_ok=True)
        filepath = os.path.join(uploads_dir, filename)

        if final_image_bytes:
            with open(filepath, "wb") as f:
                f.write(final_image_bytes)
        else:
            with open(filepath, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")

        image_url = f"/static/uploads/{filename}"

        # Persist to database ONCE
        cost_price = float(final_price * 0.75)
        saved_prod = cls.add_product(
            title=title,
            price=final_price,
            stock=15,
            vendor_id=target_vendor_id,
            category=category,
            description=description,
            image_url=image_url,
            cost_price=cost_price
        )

        return {
            "title": title,
            "description": description,
            "estimated_price": final_price,
            "detected_title": title,
            "detected_price": final_price,
            "category": category,
            "image_url": image_url,
            "filename": filename,
            "saved_product_id": saved_prod["id"] if saved_prod else None,
            "saved_product": saved_prod,
            "vendor_id": target_vendor_id,
            "vendor_name": resolved_vendor.get("name") if resolved_vendor else vendor_name,
            "vendor_phone": resolved_vendor.get("phone") if resolved_vendor else vendor_phone
        }

    @classmethod
    def get_vendor_inventory_message(cls, phone: str, name: Optional[str] = None) -> str:
        """
        Builds a quick WhatsApp inventory report for a vendor based on their sender phone number.
        Returns total count and list of products added from their WhatsApp number.
        """
        try:
            clean_p = str(phone or "").strip()
            digits = "".join(filter(str.isdigit, clean_p))[-10:]

            with cls.get_db_connection() as conn:
                c = conn.cursor()
                vendor = None
                if digits:
                    vendor = c.execute("SELECT * FROM vendors WHERE phone LIKE ? OR phone = ?", (f"%{digits}%", clean_p)).fetchone()
                if not vendor and name:
                    vendor = c.execute("SELECT * FROM vendors WHERE name = ?", (name.strip(),)).fetchone()

                v_id = vendor["id"] if vendor else None
                v_name = (vendor["name"] if vendor else name) or "Vendor"

                products = []
                if v_id:
                    rows = c.execute("SELECT * FROM products WHERE vendor_id = ? ORDER BY id DESC", (v_id,)).fetchall()
                    products = [dict(r) for r in rows]

                # Also search local Flask Product table for items listed with this vendor phone
                try:
                    from models import Product
                    local_items = Product.query.filter(
                        Product.seller_phone.ilike(f"%{digits}%") if digits else Product.seller_name == v_name
                    ).all()
                    for lp in local_items:
                        if not any(lp.name.strip().lower() == p.get("title", "").strip().lower() for p in products):
                            products.append({
                                "id": lp.id,
                                "title": lp.name,
                                "price": lp.price,
                                "stock": lp.stock_quantity or 0,
                                "category": lp.category
                            })
                except Exception:
                    pass

                if not products:
                    return (
                        f"ℹ️ *Aap Ke Number Se Koi Product Registered Nahi Hai*\n\n"
                        f"📱 *Phone:* {clean_p}\n"
                        f"Aap ke WhatsApp number se abhi tak koi item Chitral & Global Bazar par add nahi hua.\n\n"
                        f"📸 *Naya item add karne ka aasan tareeqa:*\n"
                        f"Kisi bhi product ki photo bhejein aur sath price likhein (maslan: *'Add Rs 2500'*). AI khud background remove kar ke store par live kar dega!"
                    )

                lines = [
                    f"📦 *Aap Ka Live Inventory Summary ({v_name})*",
                    f"📱 *Phone:* {clean_p}",
                    f"📊 *Total Products:* {len(products)} item(s) live on store\n"
                ]
                for idx, p in enumerate(products[:15], 1):
                    p_title = p.get("title") or p.get("name") or "Product"
                    p_price = float(p.get("price") or 0.0)
                    p_stock = int(p.get("stock") or p.get("stock_quantity") or 0)
                    lines.append(f"{idx}. *{p_title}* - PKR {p_price:,.0f} (Stock: {p_stock})")

                if len(products) > 15:
                    lines.append(f"\n...aur mazeed {len(products) - 15} items.")

                lines.append("\n✅ Tamam items Chitral & Global Bazar par live hain!")
                return "\n".join(lines)

        except Exception as e:
            logger.error(f"[GlobalBazar] Error generating vendor inventory message: {e}")
            return f"⚠️ Inventory check failed: {e}"

    # =========================================================================
    # ORDERS & AUTOMATED FULFILLMENT
    # =========================================================================

    @classmethod
    def create_order(
        cls,
        vendor_id: Optional[int],
        customer_name: str,
        customer_phone: str,
        items_summary: str,
        total_amount: float,
        delivery_address: str = "WhatsApp Order",
        order_source: str = "whatsapp",
        status: str = "confirmed"
    ) -> Optional[Dict[str, Any]]:
        """Inserts an order into Global-Bazar-Core orders table."""
        try:
            v_id = vendor_id or cls.get_default_vendor_id()
            now_iso = datetime.datetime.utcnow().isoformat()
            with cls.get_db_connection() as conn:
                c = conn.cursor()
                c.execute("""
                    INSERT INTO orders (vendor_id, order_source, customer_name, customer_phone, delivery_address, total_amount, status, items_summary, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (v_id, order_source, customer_name.strip(), customer_phone.strip(), delivery_address.strip(), float(total_amount), status, items_summary.strip(), now_iso))
                conn.commit()
                order_id = c.lastrowid
                row = c.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
                logger.info(f"[GlobalBazar] Created Order #{order_id} for {customer_name} ({total_amount} PKR)")
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"[GlobalBazar] Failed to create order: {e}")
            return None

    # =========================================================================
    # LEDGER & DAILY HISAAB-KITAAB
    # =========================================================================

    @classmethod
    def record_ledger_sale(
        cls,
        vendor_id: Optional[int],
        amount: float,
        description: str,
        category: str = "whatsapp_sale",
        entry_date: Optional[datetime.date] = None
    ) -> Optional[Dict[str, Any]]:
        """Records a completed sale into Global-Bazar-Core's daily ledger hisaab."""
        try:
            v_id = vendor_id or cls.get_default_vendor_id()
            t_date = (entry_date or datetime.date.today()).isoformat()
            now_iso = datetime.datetime.utcnow().isoformat()
            with cls.get_db_connection() as conn:
                c = conn.cursor()
                c.execute("""
                    INSERT INTO ledger (vendor_id, entry_type, amount, category, description, entry_date, created_at)
                    VALUES (?, 'sale', ?, ?, ?, ?, ?)
                """, (v_id, float(amount), category, description.strip(), t_date, now_iso))
                conn.commit()
                ledger_id = c.lastrowid
                row = c.execute("SELECT * FROM ledger WHERE id = ?", (ledger_id,)).fetchone()
                logger.info(f"[GlobalBazar] Ledger entry recorded #{ledger_id}: sale of {amount} PKR ({description})")
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"[GlobalBazar] Failed to record ledger sale: {e}")
            return None

    @classmethod
    def record_ledger_entry(
        cls,
        vendor_id: Optional[int],
        entry_type: str,
        amount: float,
        description: str,
        category: str = "manual_khata",
        entry_date: Optional[datetime.date] = None
    ) -> Optional[Dict[str, Any]]:
        """Records a sale or expense into the vendor's ledger."""
        try:
            v_id = vendor_id or cls.get_default_vendor_id()
            t_date = (entry_date or datetime.date.today()).isoformat()
            now_iso = datetime.datetime.utcnow().isoformat()
            e_type = 'sale' if entry_type in ('sale', 'credit', 'income') else 'expense'
            with cls.get_db_connection() as conn:
                c = conn.cursor()
                c.execute("""
                    INSERT INTO ledger (vendor_id, entry_type, amount, category, description, entry_date, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (v_id, e_type, float(amount), category, description.strip(), t_date, now_iso))
                conn.commit()
                ledger_id = c.lastrowid
                row = c.execute("SELECT * FROM ledger WHERE id = ?", (ledger_id,)).fetchone()
                logger.info(f"[GlobalBazar] Ledger entry recorded #{ledger_id}: {e_type} of {amount} PKR ({description})")
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"[GlobalBazar] Failed to record ledger entry: {e}")
            return None

    @classmethod
    def get_ledger_summary(
        cls,
        vendor_id: Optional[int] = None,
        target_date: Optional[datetime.date] = None
    ) -> Dict[str, Any]:
        """Calculates total sales, total expenses, and net profit for today or given date."""
        try:
            v_id = vendor_id or cls.get_default_vendor_id()
            t_date = (target_date or datetime.date.today()).isoformat()
            with cls.get_db_connection() as conn:
                c = conn.cursor()
                sales_row = c.execute("""
                    SELECT COALESCE(SUM(amount), 0.0) as total_sales, COUNT(*) as count_sales
                    FROM ledger WHERE vendor_id = ? AND entry_type = 'sale' AND entry_date = ?
                """, (v_id, t_date)).fetchone()

                expense_row = c.execute("""
                    SELECT COALESCE(SUM(amount), 0.0) as total_expenses, COUNT(*) as count_expenses
                    FROM ledger WHERE vendor_id = ? AND entry_type = 'expense' AND entry_date = ?
                """, (v_id, t_date)).fetchone()

                total_sales = float(sales_row["total_sales"] or 0.0)
                total_expenses = float(expense_row["total_expenses"] or 0.0)
                net_profit = total_sales - total_expenses

                return {
                    "date": t_date,
                    "vendor_id": v_id,
                    "total_sales": total_sales,
                    "count_sales": int(sales_row["count_sales"] or 0),
                    "total_expenses": total_expenses,
                    "count_expenses": int(expense_row["count_expenses"] or 0),
                    "net_profit": net_profit
                }
        except Exception as e:
            logger.error(f"[GlobalBazar] Failed to compute ledger summary: {e}")
            return {"date": str(target_date or datetime.date.today()), "total_sales": 0.0, "total_expenses": 0.0, "net_profit": 0.0}

    # =========================================================================
    # END-TO-END AUTOMATED WHATSAPP INVENTORY MANAGEMENT
    # =========================================================================

    @classmethod
    def process_whatsapp_order(
        cls,
        customer_phone: str,
        customer_name: str,
        product_identifier: Union[int, str],
        quantity: int = 1,
        delivery_address: str = "WhatsApp Order",
        vendor_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Master automated order pipeline:
        1. Identifies product in Global-Bazar-Core inventory.
        2. Validates live stock.
        3. Deducts stock in Global-Bazar-Core.
        4. Registers order in Global-Bazar-Core orders table.
        5. Automatically posts revenue to shop's Ledger hisaab.
        6. Formats immediate WhatsApp customer confirmation.
        """
        v_id = vendor_id or cls.get_default_vendor_id()

        # 1. Resolve product
        if isinstance(product_identifier, int) or (isinstance(product_identifier, str) and product_identifier.isdigit()):
            product = cls.get_product_by_id(int(product_identifier))
        else:
            product = cls.find_product_by_title_or_sku(str(product_identifier), vendor_id=v_id)

        if not product:
            return {
                "success": False,
                "reason": "product_not_found",
                "message": f"Maazrat! Item '{product_identifier}' hamare inventory catalog mein nahi mila."
            }

        product_id = product["id"]
        product_title = product["title"]
        price = float(product["price"])
        stock = int(product["stock"])

        # 2. Check stock
        if stock < quantity:
            return {
                "success": False,
                "reason": "out_of_stock",
                "product": product,
                "message": f"Maazrat! *{product_title}* ka required stock dastiyab nahi hai (Available: {stock} units)."
            }

        # 3. Deduct stock
        updated_product = cls.update_product_stock(product_id, quantity_delta=-quantity)
        new_stock = updated_product["stock"] if updated_product else (stock - quantity)

        # 4. Create Order
        total_amount = price * quantity
        items_summary = f"{quantity}x {product_title} @ PKR {price:,.0f}"
        order = cls.create_order(
            vendor_id=v_id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            items_summary=items_summary,
            total_amount=total_amount,
            delivery_address=delivery_address,
            order_source="whatsapp",
            status="confirmed"
        )

        # 5. Record in Ledger
        order_id_ref = order["id"] if order else "NEW"
        cls.record_ledger_sale(
            vendor_id=v_id,
            amount=total_amount,
            description=f"WhatsApp Order #{order_id_ref}: {items_summary}",
            category="whatsapp_sale"
        )

        # 6. Format Response
        confirmation_msg = (
            f"🎉 *Order Confirmed & Inventory Updated!*\n\n"
            f"Mohtaram {customer_name}! Aapka order kamyabi se record ho chuka hai:\n\n"
            f"🧾 *Order ID:* `GB-{order_id_ref}`\n"
            f"📦 *Item:* {quantity}x {product_title}\n"
            f"💰 *Total Amount:* PKR {total_amount:,.0f}\n"
            f"📊 *Remaining Stock:* {new_stock} units\n"
            f"📍 *Delivery:* {delivery_address}\n\n"
            f"Shukriya! Hamara team member delivery confirm karne ke liye rabta karega."
        )

        return {
            "success": True,
            "order": order,
            "product": updated_product,
            "total_amount": total_amount,
            "new_stock": new_stock,
            "message": confirmation_msg
        }

    # =========================================================================
    # WHATSAPP CHAT COMMANDS (!stock, !hisaab, !addstock)
    # =========================================================================

    @classmethod
    def get_inventory_whatsapp_message(cls, vendor_id: Optional[int] = None, query: Optional[str] = None) -> str:
        """Formats a WhatsApp report of current inventory and stock levels."""
        products = cls.get_products(vendor_id=vendor_id, query=query)
        if not products:
            return "📦 *Global-Bazar Inventory Status*\n\nFilhal koi products inventory mein registered nahi hain."

        lines = ["📦 *GLOBAL-BAZAR LIVE INVENTORY REPORT* 📊\n---------------------------------------"]
        for p in products:
            stock_icon = "🟢" if p["stock"] > 5 else ("🟡" if p["stock"] > 0 else "🔴")
            lines.append(
                f"{stock_icon} *ID #{p['id']}:* {p['title']}\n"
                f"   💵 Price: PKR {p['price']:,.0f} | Stock: *{p['stock']} units*\n"
                f"   📁 Category: {p.get('category') or 'General'}\n"
            )
        lines.append("---------------------------------------\n_Reply with `!addstock <id> <qty>` to adjust stock._")
        return "\n".join(lines)

    @classmethod
    def get_hisaab_whatsapp_message(cls, vendor_id: Optional[int] = None) -> str:
        """Formats today's hisaab-kitaab and profit summary for shopkeeper."""
        summary = cls.get_ledger_summary(vendor_id=vendor_id)
        t_date = summary.get("date", str(datetime.date.today()))
        return (
            f"📒 *DAILY HISAAB-KITAAB & PROFIT SUMMARY*\n"
            f"📅 Date: {t_date}\n"
            f"-----------------------------------------\n"
            f"💰 *Total Sales:* PKR {summary['total_sales']:,.0f} ({summary['count_sales']} orders)\n"
            f"💸 *Total Expenses:* PKR {summary['total_expenses']:,.0f} ({summary['count_expenses']} items)\n"
            f"-----------------------------------------\n"
            f"📈 *Net Profit Today:* *PKR {summary['net_profit']:,.0f}*\n\n"
            f"Automated with BashFlow & Global-Bazar-Core."
        )

    # =========================================================================
    # SYNCHRONIZATION WITH BASHFLOW CATALOG
    # =========================================================================

    @classmethod
    def get_catalog_items_for_ai(cls, vendor_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Converts Global-Bazar-Core products into standard format for Gemini prompt grounding."""
        products = cls.get_products(vendor_id=vendor_id)
        items = []
        for p in products:
            stock_qty = int(p.get("stock", 0))
            items.append({
                "id": str(p["id"]),
                "name": p["title"],
                "category": p.get("category") or "General Apparel",
                "price": float(p["price"]),
                "currency": "PKR",
                "stock_quantity": stock_qty,
                "stock_status": "in_stock" if stock_qty > 0 else "out_of_stock",
                "sku": f"GB-{p['id']}",
                "description": p.get("description") or p["title"],
                "image_url": p.get("image_url") or p.get("ai_image_url")
            })
        return items
