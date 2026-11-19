"""Staj Radar toplayıcı: Trendyol (Lever API), Aselsan ve Mercedes-Benz Türk (sayfa taraması).

Kurulum:
    pip install requests playwright
    playwright install chromium
Çalıştırma:
    python toplayici.py
Çıktı: ilanlar.json
"""
import json, re, time, datetime as dt, urllib.robotparser as rp
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests

OUT = Path("ilanlar.json")
UA = "StajRadar/0.1 (personal use)"
STAJ = re.compile(r"staj|\bintern(ship)?s?\b|\bPEP\b|talent program|yetenek program|summer stars|drive up", re.I)

# Sayfa taraması yapılacak şirketler. Aselsan adresini kendi kariyer sayfasına göre doğrula.
SAYFALAR = [
    {"c": "Mercedes-Benz Türk", "url": "https://careers.mercedesbenzturk.com.tr/content/Staj-Programlari/?locale=tr_TR", "city": "İstanbul / Aksaray"},
    {"c": "Aselsan", "url": "https://www.aselsan.com/tr/kariyer?menu=a-yetenek-yaz-staji", "city": "Ankara", "tek_ilan": True},
]


def robots_izin(url):
    p = urlparse(url)
    r = rp.RobotFileParser(f"{p.scheme}://{p.netloc}/robots.txt")
    try:
        r.read()
        return r.can_fetch(UA, url)
    except Exception:
        return True  # robots.txt okunamadıysa devam et


def trendyol():
    """Lever herkese açık JSON ucu."""
    veri = requests.get("https://api.lever.co/v0/postings/trendyol?mode=json",
                        headers={"User-Agent": UA}, timeout=30).json()
    sonuc = []
    for j in veri:
        cat = j.get("categories", {})
        metin = " ".join([j.get("text", ""), cat.get("team", ""), cat.get("commitment", "")])
        if not STAJ.search(metin):
            continue
        sonuc.append({
            "t": j["text"], "c": "Trendyol",
            "city": (cat.get("location") or "İstanbul").split("/")[0].strip(),
            "f": (cat.get("team") or "Diğer").split("–")[0].strip(),
            "m": (j.get("workplaceType") or "hibrit").replace("hybrid", "Hibrit").replace("remote", "Uzaktan").replace("on-site", "Ofis").capitalize(),
            "s": "Lever API", "u": j["hostedUrl"],
        })
    return sonuc


def liste_bul(o):
    """Yanıtın içindeki ilan listesini bulur (yanıt biçimi bilinmediği için esnek)."""
    if isinstance(o, list):
        return o
    if isinstance(o, dict):
        for v in o.values():
            r = liste_bul(v)
            if r:
                return r
    return []


def al(d, *anahtarlar):
    for k in anahtarlar:
        v = d.get(k)
        if isinstance(v, dict):
            v = v.get("name") or v.get("title")
        if v:
            return str(v)
    return ""


def savunma_kariyer():
    """savunmakariyer.com herkese açık ilan API'si (POST). Aselsan, TUSAS, Roketsan, Havelsan vb."""
    url = "https://savunmakariyer.com/api/career-core/public/jobs"
    sonuc, turler, ilk = [], set(), None
    for sayfa in range(1, 31):
        govde = {"page": sayfa, "size": 10, "sortBy": "updatedAt", "sortDirection": "DESC",
                 "companyId": None, "jobLocation": None, "jobTitle": None, "jobType": None, "isBgbg": False}
        r = requests.post(url, json=govde, headers={"User-Agent": UA}, timeout=30)
        r.raise_for_status()
        yanit = r.json()
        toplam = (yanit.get("data") or {}).get("totalPages", 1)
        liste = liste_bul(yanit)
        if not liste:
            break
        ilk = ilk or liste[0]
        for j in liste:
            baslik, tur = al(j, "jobTitle", "title", "name"), al(j, "jobType", "type")
            turler.add(tur)
            if j.get("applicable") is False:
                continue
            if not STAJ.search(f"{baslik} {tur}"):
                continue
            sonuc.append({
                "t": baslik, "c": al(j, "companyName", "company") or "Savunma şirketi",
                "city": al(j, "jobLocation", "location", "city") or "-",
                "f": "Savunma", "m": "Ofis", "s": "Savunma Kariyer",
                "ilk_gorulme": al(j, "createdAt")[:10],
                "u": "https://savunmakariyer.com/ilanlar?selectedJob=" + al(j, "id", "_id"),
            })
        if sayfa >= toplam:
            break
        time.sleep(1)  # siteyi yormamak için
    if ilk:  # alan adlarını kontrol etmek için ham örnek
        Path("ham_ornek.json").write_text(json.dumps(ilk, ensure_ascii=False, indent=1), "utf-8")
    print("  görülen ilan türleri:", sorted(t for t in turler if t))
    return sonuc


def sayfa_tara(site):
    """Tarayıcı ile sayfayı açıp staj ifadesi geçen bağlantıları toplar."""
    from playwright.sync_api import sync_playwright
    if not robots_izin(site["url"]):
        print(f"robots.txt izin vermiyor, atlandı: {site['c']}")
        return []
    sonuc, gorulen = [], set()
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(user_agent=UA)
        pg.goto(site["url"], wait_until="networkidle", timeout=60000)
        for _ in range(4):  # lazy-load için kaydır
            pg.mouse.wheel(0, 3000)
            time.sleep(1)
        if site.get("tek_ilan"):  # sayfanın kendisi bir staj programı
            h = pg.query_selector("h1")
            baslik = " ".join(((h.inner_text() if h else "") or pg.title()).split())
            govde = pg.inner_text("body")[:3000]
            if STAJ.search(baslik + " " + govde):
                sonuc.append({"t": baslik[:120] or "A Yetenek Yaz Stajı", "c": site["c"], "city": site["city"],
                              "f": "Diğer", "m": "Ofis", "s": "Kariyer sayfası", "u": site["url"]})
            b.close()
            return sonuc
        for a in pg.query_selector_all("a[href]"):
            metin = " ".join((a.inner_text() or "").split())
            href = urljoin(site["url"], a.get_attribute("href"))
            if href.split("#")[0] == site["url"] or len(metin) < 6 or href in gorulen or not STAJ.search(metin):
                continue
            gorulen.add(href)
            sonuc.append({"t": metin[:120], "c": site["c"], "city": site["city"],
                          "f": "Diğer", "m": "Ofis", "s": "Kariyer sayfası", "u": href})
        b.close()
    return sonuc


def main():
    eski = {x["u"]: x for x in json.loads(OUT.read_text("utf-8"))} if OUT.exists() else {}
    bugun = dt.date.today()
    toplanan = []
    for ad, fn in [("Trendyol", trendyol), ("Savunma Kariyer", savunma_kariyer)] + [(s["c"], lambda s=s: sayfa_tara(s)) for s in SAYFALAR]:
        try:
            gelen = fn()
            print(f"{ad}: {len(gelen)} ilan")
            toplanan += gelen
        except Exception as e:
            print(f"{ad}: HATA {e}")
    for x in toplanan:  # ilk görülme tarihini koru, yaşı hesapla
        ilk = x.get("ilk_gorulme") or eski.get(x["u"], {}).get("ilk_gorulme", bugun.isoformat())
        x["ilk_gorulme"] = ilk
        x["d"] = (bugun - dt.date.fromisoformat(ilk)).days
    toplanan.sort(key=lambda x: x["d"])
    OUT.write_text(json.dumps(toplanan, ensure_ascii=False, indent=1), "utf-8")
    print(f"Toplam {len(toplanan)} ilan yazıldı: {OUT}")


if __name__ == "__main__":
    main()
