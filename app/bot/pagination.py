import base64
import hashlib

ITEMS_PER_PAGE = 12

PG_NOOP = "pg:noop"
PG_SOLD = "s"
PG_DELISTED = "d"
PG_NEW = "n"
PG_BRAND_TOP = "bt"
PG_BRAND_FAST = "bf"
PG_BRAND_STATS = "st"

CALLBACK_LIMIT = 64


def encode_brand(brand: str) -> str:
    return base64.urlsafe_b64encode(brand.encode()).decode().rstrip("=")


def decode_brand(encoded: str) -> str:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding).decode()


def brand_callback_token(brand: str, days: int, page: int) -> str:
    encoded = encode_brand(brand)
    if len(f"pg:{PG_BRAND_STATS}:{days}:{page}:{encoded}") <= CALLBACK_LIMIT:
        return encoded
    return "h" + hashlib.sha256(brand.encode()).hexdigest()[:15]


def resolve_brand_token(token: str, candidates: list[str]) -> str | None:
    if token.startswith("h"):
        digest = token[1:]
        for name in candidates:
            if hashlib.sha256(name.encode()).hexdigest()[:15] == digest:
                return name
        return None
    return decode_brand(token)


def paginate_items(total: int, page: int, per_page: int = ITEMS_PER_PAGE) -> tuple[int, int, int]:
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    end = min(start + per_page, total)
    return page, total_pages, start, end


def pg_sold(days: int, page: int) -> str:
    return f"pg:{PG_SOLD}:{days}:{page}"


def pg_delisted(days: int, page: int) -> str:
    return f"pg:{PG_DELISTED}:{days}:{page}"


def pg_new(days: int, page: int) -> str:
    return f"pg:{PG_NEW}:{days}:{page}"


def pg_brand_top(days: int, brand_index: int, page: int) -> str:
    return f"pg:{PG_BRAND_TOP}:{days}:{brand_index}:{page}"


def pg_brand_fast(days: int, brand_index: int, page: int) -> str:
    return f"pg:{PG_BRAND_FAST}:{days}:{brand_index}:{page}"


def pg_brand_stats(days: int, page: int, brand: str) -> str:
    return f"pg:{PG_BRAND_STATS}:{days}:{page}:{brand_callback_token(brand, days, page)}"


def parse_pg_callback(data: str) -> dict | None:
    if data == PG_NOOP:
        return {"type": "noop"}

    parts = data.split(":")
    if len(parts) < 4 or parts[0] != "pg":
        return None

    kind = parts[1]
    if kind == PG_SOLD and len(parts) == 4:
        return {"type": PG_SOLD, "days": int(parts[2]), "page": int(parts[3])}
    if kind == PG_DELISTED and len(parts) == 4:
        return {"type": PG_DELISTED, "days": int(parts[2]), "page": int(parts[3])}
    if kind == PG_NEW and len(parts) == 4:
        return {"type": PG_NEW, "days": int(parts[2]), "page": int(parts[3])}
    if kind == PG_BRAND_TOP and len(parts) == 5:
        return {
            "type": PG_BRAND_TOP,
            "days": int(parts[2]),
            "brand_index": int(parts[3]),
            "page": int(parts[4]),
        }
    if kind == PG_BRAND_FAST and len(parts) == 5:
        return {
            "type": PG_BRAND_FAST,
            "days": int(parts[2]),
            "brand_index": int(parts[3]),
            "page": int(parts[4]),
        }
    if kind == PG_BRAND_STATS and len(parts) == 5:
        return {
            "type": PG_BRAND_STATS,
            "days": int(parts[2]),
            "page": int(parts[3]),
            "brand_token": parts[4],
        }
    return None
