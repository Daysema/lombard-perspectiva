from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogCategory:
    slug: str
    name: str
    url_path: str


CATEGORIES: list[CatalogCategory] = [
    CatalogCategory("clocks", "Швейцарские часы", "clocks_today"),
    CatalogCategory("jewellery", "Ювелирные украшения", "jewellery"),
    CatalogCategory("accessories", "Аксессуары", "accessories"),
    CatalogCategory("arts", "Предметы искусства", "arts"),
]
