#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
FitDrip feed builder (UA/RU) for Horoshop.

- Pulls DSN XML
- Enforces FitDrip category tree (categories.json)
- Assigns categoryId per product using vendorCode mapping (category_map.json)
- Renames <name> by your rules (UA/RU)
- NEVER changes:
  - offer @id
  - <vendorCode> (article)
"""

import json
import re
from pathlib import Path

import requests
from lxml import etree as ET

DSN_URL = "https://dsn.com.ua/content/export/02f6f031be3bbbdac0097758e1aa8dc6.xml"

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
OUT_DIR = ROOT / "docs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CATEGORIES_JSON = TOOLS / "categories.json"
CATEGORY_MAP_JSON = TOOLS / "category_map.json"

OUT_UA = OUT_DIR / "fitdrip_ua.xml"
OUT_RU = OUT_DIR / "fitdrip_ru.xml"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_xml(url: str) -> ET._ElementTree:
    r = requests.get(url, timeout=180)
    r.raise_for_status()
    parser = ET.XMLParser(recover=True, huge_tree=True)
    return ET.fromstring(r.content, parser=parser).getroottree()


def clean_desc(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r"\s+", " ", str(text)).strip()
    t = re.split(r"(Штрихкод|Артикул|SKU|Код|Виробник|Производитель)\b", t, maxsplit=1)[0]
    return t.strip()


def extract_purpose(desc: str) -> str:
    d = clean_desc(desc)
    if not d:
        return ""
    m = re.search(r"(для\s+[^\.\!\?]{10,90})", d, flags=re.I)
    if m:
        return m.group(1).strip(" -–—:;,.")
    return " ".join(d.split()[:8]).strip(" -–—:;,.")


def rename_ua(name: str, desc: str) -> str:
    n = (name or "").strip()

    # точечное правило
    if re.search(r"\bAnimal Flex\b", n, flags=re.I):
        n = re.sub(r"(?i)\bAnimal Flex\b", "Animal Flex — комплекс для суглобів та зв'язок", n)

    # если нет назначения — добавляем из description
    if ("—" not in n) and (":" not in n):
        purpose = extract_purpose(desc)
        if purpose:
            n = f"{n} — {purpose}"
    return n


def rename_ru(name: str, desc: str) -> str:
    n = (name or "").strip()

    if re.search(r"\bAnimal Flex\b", n, flags=re.I):
        n = re.sub(r"(?i)\bAnimal Flex\b", "Animal Flex — комплекс для суставов и связок", n)

    if ("—" not in n) and (":" not in n):
        purpose = extract_purpose(desc)
        if purpose:
            n = f"{n} — {purpose}"
    return n


def apply_categories(shop: ET._Element, categories_def: dict, lang: str) -> None:
    old = shop.find("categories")
    if old is not None:
        shop.remove(old)
    cats = ET.SubElement(shop, "categories")

    for c in categories_def.get("categories", []):
        el = ET.SubElement(cats, "category")
        el.set("id", str(c["id"]))
        parent = str(c.get("parentId", "") or "").strip()
        if parent:
            el.set("parentId", parent)
        el.text = c["ua"] if lang == "ua" else c["ru"]


def apply_category_ids(offers_node: ET._Element, category_map: dict) -> None:
    """
    Assign <categoryId> by vendorCode (article).
    If there is no mapping for a product, we keep its current categoryId as-is,
    but we NEVER replace it with brand.
    """
    for offer in offers_node.findall("offer"):
        vendor_code = (offer.findtext("vendorCode") or "").strip()
        if not vendor_code:
            continue

        new_cat = category_map.get(vendor_code)
        if not new_cat:
            continue

        cat_el = offer.find("categoryId")
        if cat_el is None:
            cat_el = ET.SubElement(offer, "categoryId")
        cat_el.text = str(new_cat)


def build(lang: str) -> ET._ElementTree:
    categories_def = load_json(CATEGORIES_JSON)
    category_map = load_json(CATEGORY_MAP_JSON).get("map", {})

    tree = fetch_xml(DSN_URL)
    root = tree.getroot()
    shop = root.find("shop")
    if shop is None:
        raise RuntimeError("Не найден <shop>")

    apply_categories(shop, categories_def, lang)

    offers_node = shop.find("offers")
    if offers_node is None:
        raise RuntimeError("Не найден <offers>")

    apply_category_ids(offers_node, category_map)

    # rename titles
    for offer in offers_node.findall("offer"):
        name_el = offer.find("name")
        if name_el is None:
            continue
        desc_el = offer.find("description")
        name_txt = name_el.text or ""
        desc_txt = (desc_el.text if desc_el is not None else "") or ""

        name_el.text = rename_ua(name_txt, desc_txt) if lang == "ua" else rename_ru(name_txt, desc_txt)

    return tree


def main():
    build("ua").write(str(OUT_UA), encoding="utf-8", xml_declaration=True)
    build("ru").write(str(OUT_RU), encoding="utf-8", xml_declaration=True)
    print("OK:", OUT_UA, OUT_RU)


if __name__ == "__main__":
    main()
