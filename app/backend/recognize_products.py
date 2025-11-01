import re
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup

def fetch_html(url: str) -> str:
    resp = requests.get(url, timeout=5)
    resp.raise_for_status()
    return resp.text

def pick_title(soup: BeautifulSoup) -> str | None:
    # Prefer Open Graph, then <title>, then <h1>
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()

    if soup.title and soup.title.string:
        return soup.title.string.strip()

    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)

    # Fallback: Twitter card
    tw = soup.find("meta", attrs={"name": "twitter:title"})
    if tw and tw.get("content"):
        return tw["content"].strip()

    return None

def _url_from_srcset(srcset: str) -> str | None:
    # srcset like: "https://a.jpg 1x, https://b.jpg 2x"
    if not srcset:
        return None
    first = srcset.split(",")[0].strip()
    # first token is URL; there may be a descriptor like "1x" or "300w"
    return first.split()[0] if first else None

def _canonicalize_img_url(u: str | None, base: str) -> str | None:
    if not u:
        return None
    # Handle protocol-relative //example.com/img.jpg
    if u.startswith("//"):
        u = "https:" + u
    # Discard data URIs
    if u.startswith("data:"):
        return None
    return urljoin(base, u)


def pick_first_image_url(soup: BeautifulSoup, base_url: str) -> str | None:
    # 1) Open Graph first (most reliable on product pages)
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        u = _canonicalize_img_url(og["content"].strip(), base_url)
        if u:
            return u

    # 2) <link rel="image_src">
    link_img = soup.find("link", rel=lambda v: v and "image_src" in v)
    if link_img and link_img.get("href"):
        u = _canonicalize_img_url(link_img["href"].strip(), base_url)
        if u:
            return u

    # 3) Twitter card
    tw = soup.find("meta", attrs={"name": "twitter:image"})
    if tw and tw.get("content"):
        u = _canonicalize_img_url(tw["content"].strip(), base_url)
        if u:
            return u

    # 4) First <img> in DOM, considering lazy-load attributes
    img = soup.find("img")
    if img:
        # Try common lazy-load attributes in priority order
        candidates = [
            img.get("src"),
            img.get("data-src"),
            img.get("data-original"),
            img.get("data-lazy-src"),
            img.get("data-flickity-lazyload"),
            _url_from_srcset(img.get("srcset", "")),
            _url_from_srcset(img.get("data-srcset", "")),
        ]
        for c in candidates:
            u = _canonicalize_img_url(c, base_url)
            if u:
                return u

    # 5) Last resort: any <meta content> ending with an image extension
    meta_img = soup.find("meta", content=re.compile(r"\.(png|jpe?g|webp|gif)(\?.*)?$", re.I))
    if meta_img and meta_img.get("content"):
        u = _canonicalize_img_url(meta_img["content"].strip(), base_url)
        if u:
            return u

    return None

def parse_title_and_first_image(url: str) -> dict:
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")
    title = pick_title(soup)
    image_url = pick_first_image_url(soup, url)
    return {"title": title, "image_url": image_url}


def recognize_products(driver, url: str):
    """
    For an URL of a galaxus product, return all relevant information to create a preview of that product.
    """
    product_id = parse_product_id(url)
    if product_id:

        galaxus_url = f"https://galaxus.ch/product/{product_id}"
        product_data = parse_title_and_first_image(galaxus_url)
        return product_data
    return None
    


def parse_product_id(url: str):
    """
    Extracts the galaxus product id from the url.
    """
    if (not "galaxus" in url) | (not "product" in url):
        return None

    # parse id
    match = re.search(r'-([0-9]{7,})\b', url)
    if match:
        product_id = match.group(1)
        return product_id

    else:
        return None




