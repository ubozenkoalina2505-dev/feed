#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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

OUT_UA = OUT_DIR / "fitdrip_ua.xml"
OUT_RU = OUT_DIR / "fitdrip_ru.xml"


def fetch_xml(url: str) -> ET._ElementTree:
    r = requests.get(url, timeout=180)
    r.raise_for_status()
    parser = ET.XMLParser(recover=True, huge_tree=True)
    return ET.fromstring(r.content, parser=parser).getroottree()


def clean_desc(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r"\s+", " ", text).strip()
    t = re.split(r"(Штрихкод|Артикул|SKU|Код|Виробник|Производитель)\b", t, maxsplit=1)[0]
    return t.strip()


def rename_ua(name: str, desc: str) -> str:
    n = (name or "").strip()

    if re.search(r"\bAnimal Flex\b", n, flags=re.I):
        n = re.sub(r"(?i)\bAnimal Flex\b", "Animal Flex — комплекс для суглобів та зв'язок", n)

    if ("—" not in n) and (":" not in n):
        d = clean_desc(desc)
        if d:
            frag = " ".join(d.split()[:8])
            n = f"{n} — {frag}"
    return n


def rename_ru(name: str, desc: str) -> str:
    n = (name or "").strip()

    if re.search(r"\bAnimal Flex\b", n, flags=re.I):
        n = re.sub(r"(?i)\bAnimal Flex\b", "Animal Flex — комплекс для суставов и связок", n)

    if ("—" not in n) and (":" not in n):
        d = clean_desc(desc)
        if d:
            frag = " ".join(d.split()[:8])
            n = f"{n} — {frag}"
    return n


def build(lang: str) -> ET._ElementTree:
    tree = fetch_xml(DSN_URL)
    root = tree.getroot()
    shop = root.find("shop")
    offers = shop.find("offers")

    for offer in offers.findall("offer"):
        name_el = offer.find("name")
        desc_el = offer.find("description")
        if name_el is None:
            continue

        name = name_el.text or ""
        desc = desc_el.text or ""

        if lang == "ua":
            name_el.text = rename_ua(name, desc)
        else:
            name_el.text = rename_ru(name, desc)

    return tree


def main():
    ua_tree = build("ua")
    ua_tree.write(str(OUT_UA), encoding="utf-8", xml_declaration=True)

    ru_tree = build("ru")
    ru_tree.write(str(OUT_RU), encoding="utf-8", xml_declaration=True)

    print("Feeds updated")


if __name__ == "__main__":
    main()
