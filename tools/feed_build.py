#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
FitDrip feed builder (UA/RU) for Horoshop.

- Pulls DSN XML
- Enforces FitDrip category tree (tools/categories.json)
- Assigns categoryId per product using vendorCode mapping (tools/category_map.json)
- Renames <name> using rules (UA/RU)
- NEVER changes:
  - offer @id
  - <vendorCode> (article)
"""

import json
import re
from pathlib import Path

import requests
from lxml import etree as ET

# DSN двуязычная выгрузка (как ты давала)
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
    # обрезаем хвосты типа "Штрихкод/Артикул/..."
    t = re.split(r"(Штрихкод|Артикул|SKU|Код|Виробник|Производитель)\b", t, maxsplit=1)[0]
    return t.strip()


def extract_purpose(desc: str) -> str:
    """
    Если нет типа/назначения — берём из description.
    1) пробуем фразу "для ..."
    2) иначе первые 5–8 слов
    """
    d = clean_desc(desc)
    if not d:
        return ""
    m = re.search(r"(для\s+[^\.\!\?]{10,90})", d, flags=re.I)
    if m:
        return m.group(1).strip(" -–—:;,.")
    return " ".join(d.split()[:8]).strip(" -–—:;,.")


def normalize_base_name(name: str) -> str:
    """
    Убираем грубые хвосты вида '500g', '300 caps', '60 tabs', '100 ml'
    чтобы потом собрать красивое имя.
    """
    n = (name or "").strip()
    n = re.sub(r"\b\d+\s?(g|kg|caps|cap|tabs|tab|tablets|ml)\b", "", n, flags=re.I).strip()
    n = re.sub(r"\s{2,}", " ", n)
    return n


# --- UA naming rules ---
UA_TYPE_RULES = [
    (["creatine"], "креатин моногідрат"),
    (["omega", "omega 3", "epa", "dha"], "омега-3 жирні кислоти"),
    (["collagen"], "гідролізований колаген"),
    (["whey", "whey protein", "whey isolate", "isolate", "protein"], "сироватковий протеїн"),
    (["bcaa"], "амінокислоти BCAA"),
    (["glutamine"], "глютамін"),
    (["multivitamin", "multi"], "мультивітамінний комплекс"),
    (["zinc"], "цинк"),
    (["magnesium"], "магній"),
    (["vitamin c"], "вітамін C"),
    (["vitamin d"], "вітамін D"),
]


def detect_ua_type(base: str) -> str:
    lname = (base or "").lower()
    for keys, label in UA_TYPE_RULES:
        if any(k in lname for k in keys):
            return label
    return ""


def rename_ua(name: str, desc: str, vendor: str = "") -> str:
    n = (name or "").strip()

    # точечный кейс
    if re.search(r"\bAnimal Flex\b", n, flags=re.I):
        n = re.sub(r"(?i)\bAnimal Flex\b", "Animal Flex", n).strip()
        return f"{n} {vendor}".strip() + " — комплекс для суглобів та зв'язок"

    base = normalize_base_name(n)
    v = (vendor or "").strip()

    # 1) Пытаемся определить тип по ключевым словам в названии
    product_type = detect_ua_type(base)

    if product_type:
        if v:
            return f"{base} {v} — {product_type}"
        return f"{base} — {product_type}"

    # 2) Если в названии нет назначения — добавляем из description
    if ("—" not in base) and (":" not in base):
        purpose = extract_purpose(desc)
        if purpose:
            if v:
                return f"{base} {v} — {purpose}"
            return f"{base} — {purpose}"

    # 3) Если ничего не нашли — хотя бы добавим бренд (если его нет)
    if v and v.lower() not in base.lower():
        return f"{base} {v}"
    return n


# --- RU naming rules (минимально, чтобы был 2-й файл) ---
def rename_ru(name: str, desc: str, vendor: str = "") -> str:
    # если не хочешь русские правки — можно оставить почти как есть
    n = (name or "").strip()
    base = normalize_base_name(n)
    v = (vendor or "").strip()
    if v and v.lower() not in base.lower():
        return f"{base} {v}"
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
    If mapping is missing, keep the current <categoryId> (no brand fallback).
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
        vendor = offer.findtext("vendor") or ""

        if lang == "ua":
            name_el.text = rename_ua(name_txt, desc_txt, vendor)
        else:
            name_el.text = rename_ru(name_txt, desc_txt, vendor)

    return tree


def main():
    build("ua").write(str(OUT_UA), encoding="utf-8", xml_declaration=True)
    build("ru").write(str(OUT_RU), encoding="utf-8", xml_declaration=True)
    print("OK:", OUT_UA, OUT_RU)


if __name__ == "__main__":
    main()
