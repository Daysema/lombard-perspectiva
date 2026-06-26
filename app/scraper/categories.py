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

ARCHIVE_CATEGORIES: list[CatalogCategory] = [
    CatalogCategory("clocks_archive", "Архив часов", "clocks_archive"),
    CatalogCategory("jewellery_archive", "Архив ювелирки", "jewelries_archive"),
    CatalogCategory("accessories_archive", "Архив аксессуаров", "accessory_archive"),
    CatalogCategory("arts_archive", "Архив искусства", "arts_archive"),
]
