import os
import asyncio
import aiohttp
import re
import json
import urllib.parse
import uvicorn
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from typing import List, Tuple

# ---- Global constants ----
HEADERS = {"User-Agent": "Mozilla/5.0"}

# ---- FastAPI setup ----
app = FastAPI()
total_visits = 0
active_connections = set()

class StatsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        global total_visits
        total_visits += 1
        response = await call_next(request)
        return response

app.add_middleware(StatsMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="templates")

# ---- Root endpoint ----
@app.get("/")
async def read_index(request: Request):
    return templates.TemplateResponse("ok.html", {"request": request})

# ---- Helper functions ----
def parse_links_and_titles(page_content: str, pattern: str, title_class: str):
    soup = BeautifulSoup(page_content, "html.parser")
    links = [a["href"] for a in soup.find_all("a", href=True) if re.match(pattern, a["href"])]
    titles = [span.get_text() for span in soup.find_all("span", class_=title_class)]
    return links, titles

async def get_webpage_content(url: str, session: aiohttp.ClientSession):
    async with session.get(url, allow_redirects=True) as response:
        text = await response.text()
        return text, str(response.url), response.status

def _normalize(s: str) -> str:
    return "".join(s.lower().split())

# ---- Erome scrapers ----
def extract_album_links(page_content: str) -> List[str]:
    soup = BeautifulSoup(page_content, "html.parser")
    links = set()
    for a in soup.find_all("a", class_="album-link"):
        href = a.get("href")
        if href and href.startswith("https://www.erome.com/a/"):
            links.add(href)
    return list(links)

async def fetch_all_album_pages(username: str, max_pages: int = 10) -> List[str]:
    base = "https://www.erome.com/search"
    urls = set()
    page_urls = [
        f"{base}?q={urllib.parse.quote(username)}&page={i}"
        for i in range(1, max_pages + 1)
    ]
    async with aiohttp.ClientSession() as session:
        async def _fetch_page(u: str):
            text, _, status = await get_webpage_content(u, session)
            if status != 200 or not text:
                return []
            return extract_album_links(text)
        tasks = [asyncio.create_task(_fetch_page(u)) for u in page_urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    for res in results:
        if isinstance(res, list):
            urls.update(res)
    return list(urls)

async def fetch_image_urls(album_url: str, session: aiohttp.ClientSession) -> List[str]:
    page_content, base_url, _ = await get_webpage_content(album_url, session)
    soup = BeautifulSoup(page_content, "html.parser")
    return [
        urljoin(base_url, img["data-src"])
        for img in soup.find_all("div", class_="img")
        if img.get("data-src")
    ]

async def fetch_all_erome_image_urls(album_urls: List[str]) -> List[str]:
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        tasks = [asyncio.create_task(fetch_image_urls(url, session)) for url in album_urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    urls = {u for res in results if isinstance(res, list) for u in res if "/thumb/" not in u}
    return list(urls)

# ---- Bunkr scrapers ----
async def fetch_bunkr_gallery_images(username: str) -> List[str]:
    thumb_pattern = re.compile(r"/thumb/")
    async with aiohttp.ClientSession() as session:
        albums = []
        page = 1
        while True:
            search_url = f"https://bunkr-albums.io/?search={urllib.parse.quote(username)}&page={page}"
            text, _, status = await get_webpage_content(search_url, session)
            if status != 200 or not text:
                break
            links, titles = parse_links_and_titles(text, r"^https://bunkr\.cr/a/.*", "album-title")
            if not links:
                break
            albums.extend(links)
            page += 1

        image_page_urls = []
        async def _get_album_links(album_url: str):
            async with session.get(album_url) as resp:
                if resp.status != 200:
                    return []
                text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            out = []
            for a in soup.find_all("a", attrs={"aria-label": "download"}, href=True):
                href = a["href"]
                if href.startswith("/f/"):
                    out.append("https://bunkr.cr" + href)
                elif href.startswith("https://bunkr.cr/f/"):
                    out.append(href)
            return out

        tasks1 = [asyncio.create_task(_get_album_links(u)) for u in albums]
        pages_results = await asyncio.gather(*tasks1)
        for res in pages_results:
            image_page_urls.extend(res)

        async def _get_image_url(link: str):
            async with session.get(link) as resp:
                if resp.status != 200:
                    return None
                text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            img = soup.find("img", class_=lambda c: c and "object-cover" in c)
            return img.get("src") if img else None

        tasks2 = [asyncio.create_task(_get_image_url(u)) for u in image_page_urls]
        results2 = await asyncio.gather(*tasks2)
        valid = [u for u in results2 if u and not thumb_pattern.search(u)]

        async def _validate(u: str):
            try:
                async with session.get(u, headers={"Range": "bytes=0-0"}, allow_redirects=True) as r:
                    if r.status == 200:
                        return u
            except:
                pass
            return None

        tasks3 = [asyncio.create_task(_validate(u)) for u in valid]
        validated = await asyncio.gather(*tasks3)
        return list({u for u in validated if u})

# ---- Fapello scraper ----
async def fetch_fapello_page_media(page_url: str, session: aiohttp.ClientSession, username: str) -> dict:
    try:
        content, base, status = await get_webpage_content(page_url, session)
        if status != 200:
            return {"images": [], "videos": []}
        soup = BeautifulSoup(content, "html.parser")
        imgs = [
            img.get("src") or img.get("data-src")
            for img in soup.find_all("img")
            if img.get("src", "").startswith(f"https://fapello.com/content/") and f"/{username}/" in img.get("src", "")
        ]
        vids = [
            v["src"]
            for v in soup.find_all("source", type="video/mp4", src=True)
            if f"/{username}/" in v["src"]
        ]
        return {"images": list(set(imgs)), "videos": list(set(vids))}
    except:
        return {"images": [], "videos": []}

async def fetch_fapello_album_media(album_url: str) -> dict:
    media = {"images": [], "videos": []}
    parsed = urllib.parse.urlparse(album_url)
    username = parsed.path.strip("/").split("/")[0]
    async with aiohttp.ClientSession(headers={**HEADERS, "Referer": album_url}) as session:
        content, base, status = await get_webpage_content(album_url, session)
        if status != 200:
            return media
        soup = BeautifulSoup(content, "html.parser")
        pages = {
            urllib.parse.urljoin(base, a["href"])
            for a in soup.find_all("a", href=True)
            if urllib.parse.urljoin(base, a["href"]).startswith(album_url)
               and re.search(r"/\d+/?$", a["href"])
        }
        if not pages:
            pages = {album_url}
        tasks = [asyncio.create_task(fetch_fapello_page_media(p, session, username)) for p in pages]
        results = await asyncio.gather(*tasks)
        for res in results:
            media["images"].extend(res["images"])
            media["videos"].extend(res["videos"])
    media["images"] = list(set(media["images"]))
    media["videos"] = list(set(media["videos"]))
    return media

# ---- JPG5 scraper ----
async def extract_jpg5_album_media_urls(album_url: str) -> List[str]:
    urls = set()
    next_page = album_url.rstrip("/")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        while next_page:
            async with session.get(next_page, allow_redirects=True) as resp:
                if resp.status != 200:
                    break
                html = await resp.text()
            soup = BeautifulSoup(html, "html.parser")
            found = {img["src"] for img in soup.find_all("img", src=True) if "jpg5.su" in img["src"]}
            if not found or found.issubset(urls):
                break
            urls.update(found)
            nxt = soup.find("a", {"data-pagination": "next"})
            next_page = nxt["href"] if nxt and "href" in nxt.attrs else None
            if next_page and not next_page.startswith("http"):
                next_page = "https://jpg5.su" + next_page
    return list(urls)

# ---- NotFans scraper ----
async def fetch_notfans(search_term: str, debug: bool = False) -> Tuple[List[str], List[str]]:
    base = "https://notfans.com"
    encoded = urllib.parse.quote_plus(search_term)
    first_url = f"{base}/search/{encoded}/"
    term = search_term.lower()
    urls, titles = [], []
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        if debug: print(f"[NOTFANS] GET {first_url}")
        async with session.get(first_url, allow_redirects=True) as resp:
            if resp.status != 200:
                return [], []
            html = await resp.text()
        soup = BeautifulSoup(html, "html.parser")
        items = soup.select('a[href^="https://notfans.com/videos/"]')
        for a in items:
            t = a.find("strong", class_="title")
            if not t: continue
            title = t.get_text(strip=True)
            if term not in title.lower(): continue
            href = a["href"].strip()
            urls.append(href if href.startswith("http") else base + href)
            titles.append(title)
        params = [lnk["data-parameters"] for lnk in soup.select('a[data-action="ajax"][data-parameters]')]
        page_urls = [f"{first_url}?{p.replace(':','=').replace(';','&')}" for p in params]
        async def _fetch_page(u: str):
            try:
                async with session.get(u, allow_redirects=True) as r:
                    if r.status != 200:
                        return [], []
                    h = await r.text()
            except Exception as e:
                if debug: print(f"[NOTFANS] ERR {e}")
                return [], []
            sp = BeautifulSoup(h, "html.parser")
            us, ts = [], []
            for a in sp.select('a[href^="https://notfans.com/videos/"]'):
                t = a.find("strong", class_="title")
                if not t: continue
                title = t.get_text(strip=True)
                if term not in title.lower(): continue
                href = a["href"].strip()
                us.append(href if href.startswith("http") else base + href)
                ts.append(title)
            return us, ts
        tasks = [asyncio.create_task(_fetch_page(u)) for u in page_urls]
        for us, ts in await asyncio.gather(*tasks):
            urls.extend(us); titles.extend(ts)
    return urls, titles

# ---- Influencers scraper ----
async def fetch_influencers(term: str) -> Tuple[List[str], List[str]]:
    base = "https://influencersgonewild.com/"
    page = 1
    page_urls = []
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        while True:
            u = f"{base}?s={term}&paged={page}"
            async with session.get(u, allow_redirects=True) as r:
                text = await r.text()
            items = BeautifulSoup(text, "html.parser").find_all("a", class_="g1-frame")
            if not items:
                break
            page_urls.append(u)
            page += 1
        async def _fetch_page(u: str):
            us, ts = [], []
            async with session.get(u, allow_redirects=True) as r2:
                t2 = await r2.text()
            for a in BeautifulSoup(t2, "html.parser").find_all("a", class_="g1-frame"):
                href = a.get("href"); title = a.get("title") or a.text.strip()
                us.append(href); ts.append(title)
            return us, ts
        tasks = [asyncio.create_task(_fetch_page(u)) for u in page_urls]
        results = await asyncio.gather(*tasks)
    urls, titles = [], []
    for us, ts in results:
        urls.extend(us); titles.extend(ts)
    return urls, titles

# ---- Thothub scraper ----
async def fetch_thothub(term: str) -> Tuple[List[str], List[str]]:
    base = f"https://thothub.to/search/{term}/"
    page = 1
    page_urls = []
    seen = set()
    urls, titles = [], []
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        while True:
            u = f"{base}?page={page}"
            async with session.get(u, allow_redirects=True) as resp:
                if resp.status != 200:
                    break
                text = await resp.text()
            items = [a for a in BeautifulSoup(text, "html.parser").select('a[title]')
                     if not a.find("span", class_="line-private")]
            new_links = [a["href"] for a in items if a["href"] not in seen]
            if not new_links:
                break
            page_urls.append(u)
            for href in new_links:
                seen.add(href)
            page += 1

        async def _fetch_page(u: str):
            us, ts = [], []
            async with session.get(u, allow_redirects=True) as resp:
                if resp.status != 200:
                    return [], []
                html = await resp.text()
            for a in BeautifulSoup(html, "html.parser").select('a[title]'):
                if not a.find("span", class_="line-private"):
                    href = a["href"]; title = a["title"]
                    if href not in seen:
                        seen.add(href)
                        us.append(href); ts.append(title)
            return us, ts

        tasks = [asyncio.create_task(_fetch_page(u)) for u in page_urls]
        results = await asyncio.gather(*tasks)

    for us, ts in results:
        urls.extend(us); titles.extend(ts)
    return urls, titles

# ---- Dirtyship scraper ----
async def fetch_dirtyship(term: str) -> Tuple[List[str], List[str]]:
    base = "https://dirtyship.com"
    page = 1
    page_urls = []
    urls, titles = [], []
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        while True:
            u = f"{base}/page/{page}/?search_param=all&s={term}"
            async with session.get(u, allow_redirects=True) as resp:
                if resp.status != 200:
                    break
                text = await resp.text()
            items = BeautifulSoup(text, "html.parser").find_all("a", id="preview_image")
            if not items:
                break
            page_urls.append(u)
            page += 1

        async def _fetch_page(u: str):
            us, ts = [], []
            async with session.get(u, allow_redirects=True) as resp:
                if resp.status != 200:
                    return [], []
                html = await resp.text()
            for a in BeautifulSoup(html, "html.parser").find_all("a", id="preview_image"):
                href = a["href"]; title = a.get("title") or a.text.strip()
                us.append(href); ts.append(title)
            return us, ts

        tasks = [asyncio.create_task(_fetch_page(u)) for u in page_urls]
        results = await asyncio.gather(*tasks)

    for us, ts in results:
        urls.extend(us); titles.extend(ts)
    return urls, titles

# ---- Pimpbunny scraper ----
async def fetch_pimpbunny(term: str) -> Tuple[List[str], List[str]]:
    url = f"https://pimpbunny.com/search/{term}/"
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(url, allow_redirects=True) as resp:
            if resp.status != 200:
                return [], []
            html = await resp.text()
        us, ts = [], []
        for a in BeautifulSoup(html, "html.parser").find_all("a", class_="pb-item-link"):
            href = a["href"]; title = a.get("title") or a.text.strip()
            us.append(href); ts.append(title)
    return us, ts

# ---- Leakedzone scraper ----
async def fetch_leakedzone(term: str) -> Tuple[List[str], List[str]]:
    url = f"https://leakedzone.com/search?search={term}"
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(url, allow_redirects=True) as resp:
            if resp.status != 200:
                return [], []
            html = await resp.text()
        us, ts = [], []
        for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
            href = a["href"]
            if href.startswith("https://leakedzone.com/") and term.lower().replace(" ", "") in href.lower():
                title = a.get("title") or a.text.strip()
                us.append(href); ts.append(title)
    return us, ts

# ---- FanslyLeaked scraper ----
async def fetch_fanslyleaked(term: str) -> Tuple[List[str], List[str]]:
    base = "https://ww1.fanslyleaked.com"
    page = 1
    page_urls = []
    seen = set()
    urls, titles = [], []
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        while True:
            u = f"{base}/page/{page}/?s={term}"
            async with session.get(u, allow_redirects=True) as resp:
                if resp.status != 200:
                    break
                html = await resp.text()
            items = BeautifulSoup(html, "html.parser").find_all("a", href=True, title=True)
            new = False
            for a in items:
                href = a["href"]
                if href.startswith("/"):
                    href = base + href
                if href.startswith(base) and all(x not in href for x in ["/page/", "?s=", "#"]) and href not in seen:
                    seen.add(href); new = True
            if not new:
                break
            page_urls.append(u)
            page += 1

        async def _fetch(u: str):
            us, ts = [], []
            async with session.get(u, allow_redirects=True) as resp:
                if resp.status != 200:
                    return [], []
                html = await resp.text()
            for a in BeautifulSoup(html, "html.parser").find_all("a", href=True, title=True):
                href = a["href"]
                if href.startswith("/"):
                    href = base + href
                if href.startswith(base) and all(x not in href for x in ["/page/", "?s=", "#"]) and href not in seen:
                    seen.add(href); us.append(href); ts.append(a["title"])
            return us, ts

        tasks = [asyncio.create_task(_fetch(u)) for u in page_urls]
        results = await asyncio.gather(*tasks)

    for us, ts in results:
        urls.extend(us); titles.extend(ts)
    return urls, titles

# ---- GotAnyNudes scraper ----
async def fetch_gotanynudes(search_term: str) -> Tuple[List[str], List[str]]:
    query = search_term.replace(" ", "+")
    normalized = _normalize(search_term)
    page = 1
    page_urls = []
    urls, titles = [], []
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        while True:
            u = f"https://gotanynudes.com/?s={query}" if page == 1 else f"https://gotanynudes.com/page/{page}/?s={query}"
            async with session.get(u, allow_redirects=True) as resp:
                if resp.status != 200:
                    break
                html = await resp.text()
            found = any(normalized in _normalize(a["title"].strip())
                        for a in BeautifulSoup(html, "html.parser").find_all("a", class_="g1-frame", title=True, href=True))
            if not found:
                break
            page_urls.append(u)
            page += 1

        async def _fetch(u: str):
            us, ts = [], []
            async with session.get(u, allow_redirects=True) as resp:
                if resp.status != 200:
                    return [], []
                html = await resp.text()
            for a in BeautifulSoup(html, "html.parser").find_all("a", class_="g1-frame", title=True, href=True):
                title = a["title"].strip()
                if normalized in _normalize(title):
                    us.append(a["href"]); ts.append(title)
            return us, ts

        tasks = [asyncio.create_task(_fetch(u)) for u in page_urls]
        results = await asyncio.gather(*tasks)

    for us, ts in results:
        urls.extend(us); titles.extend(ts)
    return urls, titles

# ---- NSFW247 scraper ----
async def fetch_nsfw247(search_term: str) -> Tuple[List[str], List[str]]:
    query = search_term.replace(" ", "-")
    normalized = _normalize(search_term)
    base = f"https://nsfw247.to/search/{query}-0z5g7jn9"
    page = 1
    page_urls = []
    urls, titles = [], []
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        while True:
            u = base if page == 1 else f"{base}/page/{page}/"
            async with session.get(u, allow_redirects=True) as resp:
                if resp.status != 200:
                    break
                html = await resp.text()
            found = any(a["href"].startswith("https://nsfw247.to/") and normalized in _normalize(a.get_text(strip=True))
                        for a in BeautifulSoup(html, "html.parser").find_all("a", href=True))
            if not found:
                break
            page_urls.append(u)
            page += 1

        async def _fetch(u: str):
            us, ts = [], []
            async with session.get(u, allow_redirects=True) as resp:
                if resp.status != 200:
                    return [], []
                html = await resp.text()
            for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
                href = a["href"]; title = a.get_text(strip=True)
                if href.startswith("https://nsfw247.to/") and normalized in _normalize(title):
                    us.append(href); ts.append(title)
            return us, ts

        tasks = [asyncio.create_task(_fetch(u)) for u in page_urls]
        results = await asyncio.gather(*tasks)

    for us, ts in results:
        urls.extend(us); titles.extend(ts)
    return urls, titles

# ---- HornySimp scraper ----
async def fetch_hornysimp(search_term: str) -> Tuple[List[str], List[str]]:
    query = search_term.replace(" ", "+")
    normalized = _normalize(search_term)
    base1 = f"https://hornysimp.com/?s={query}"
    page = 1
    page_urls = []
    urls, titles = [], []
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        while True:
            u = base1 if page == 1 else f"https://hornysimp.com/?s={query}/?_page={page}"
            async with session.get(u, allow_redirects=True) as resp:
                if resp.status != 200:
                    break
                html = await resp.text()
            found = any("hornysimp.com" in a.get("href", "") and normalized in _normalize(a.get("title", "").strip())
                        for a in BeautifulSoup(html, "html.parser").find_all("a", href=True, title=True))
            if not found:
                break
            page_urls.append(u)
            page += 1

        async def _fetch(u: str):
            us, ts = [], []
            async with session.get(u, allow_redirects=True) as resp:
                if resp.status != 200:
                    return [], []
                html = await resp.text()
            for a in BeautifulSoup(html, "html.parser").find_all("a", href=True, title=True):
                href = a["href"]; title = a["title"].strip()
                if "hornysimp.com" in href and normalized in _normalize(title):
                    us.append(href); ts.append(title)
            return us, ts

        tasks = [asyncio.create_task(_fetch(u)) for u in page_urls]
        results = await asyncio.gather(*tasks)

    for us, ts in results:
        urls.extend(us); titles.extend(ts)
    return urls, titles

# ---- Porntn scraper ----
async def fetch_porntn(search_term: str) -> Tuple[List[str], List[str]]:
    query = search_term.replace(" ", "-")
    base = f"https://porntn.com/search/{query}"
    normalized = _normalize(search_term)
    page_urls = [base]
    urls, titles = [], []
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(base, allow_redirects=True) as resp:
            if resp.status != 200:
                return [], []
            html = await resp.text()
        soup = BeautifulSoup(html, "html.parser")
        offsets = []
        for a in soup.find_all("a", href="#videos", attrs={"data-parameters": True}):
            for part in a["data-parameters"].split(";"):
                if part.startswith("from:"):
                    _, off = part.split(":", 1)
                    if off.isdigit():
                        offsets.append(off)
        for off in offsets:
            page_urls.append(f"{base}/?from={off}")

        async def _fetch(u: str):
            us, ts = [], []
            async with session.get(u, allow_redirects=True) as resp:
                if resp.status != 200:
                    return [], []
                html2 = await resp.text()
            for a in BeautifulSoup(html2, "html.parser").find_all("a", href=True, title=True):
                href = a["href"]; title = a["title"].strip()
                if href.startswith("https://porntn.com/videos") and normalized in _normalize(title):
                    us.append(href); ts.append(title)
            return us, ts

        tasks = [asyncio.create_task(_fetch(u)) for u in page_urls]
        results = await asyncio.gather(*tasks)

    for us, ts in results:
        urls.extend(us); titles.extend(ts)
    return urls, titles

# ---- XXBrits scraper ----
async def fetch_xxbrits(search_term: str) -> Tuple[List[str], List[str]]:
    query = search_term.replace(" ", "")
    base = f"https://www.xxbrits.com/search/{query}-23cd7b/"
    normalized = _normalize(search_term)
    page_urls = [base]
    urls, titles = [], []
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(base, allow_redirects=True) as resp:
            if resp.status != 200:
                return [], []
            html = await resp.text()
        soup = BeautifulSoup(html, "html.parser")
        offsets = []
        for a in soup.find_all("a", href="#search", attrs={"data-parameters": True}):
            for part in a["data-parameters"].split(";"):
                if ":" in part:
                    _, v = part.split(":", 1)
                    if v.isdigit():
                        offsets.append(v)
        for off in offsets:
            page_urls.append(f"{base}?from={off}")

        async def _fetch(u: str):
            us, ts = [], []
            async with session.get(u, allow_redirects=True) as resp:
                if resp.status != 200:
                    return [], []
                html2 = await resp.text()
            for a in BeautifulSoup(html2, "html.parser").find_all("a", class_="item link-post", href=True, title=True):
                title = a["title"].strip(); href = a["href"]
                if normalized in _normalize(title):
                    us.append(href); ts.append(title)
            return us, ts

        tasks = [asyncio.create_task(_fetch(u)) for u in page_urls]
        results = await asyncio.gather(*tasks)

    for us, ts in results:
        urls.extend(us); titles.extend(ts)
    return urls, titles

# ---- BitchesGirls scraper ----
async def fetch_bitchesgirls(search_term: str) -> Tuple[List[str], List[str]]:
    query = search_term.replace(" ", "%20")
    normalized = _normalize(search_term)
    base = f"https://bitchesgirls.com/search/{query}/"
    page = 1
    page_urls = []
    urls, titles = [], []
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        while True:
            u = f"{base}{page}/"
            async with session.get(u, allow_redirects=True) as resp:
                if resp.status != 200:
                    break
                html = await resp.text()
            found = any(a.get("href", "").startswith("/onlyfans/") and normalized in _normalize(a.get_text(strip=True))
                        for a in BeautifulSoup(html, "html.parser").find_all("a", href=True))
            if not found:
                break
            page_urls.append(u)
            page += 1

        async def _fetch(u: str):
            us, ts = [], []
            async with session.get(u, allow_redirects=True) as resp:
                if resp.status != 200:
                    return [], []
                html2 = await resp.text()
            for a in BeautifulSoup(html2, "html.parser").find_all("a", href=True):
                href = a["href"]; text = a.get_text(strip=True)
                if href.startswith("/onlyfans/") and normalized in _normalize(text):
                    us.append(f"https://bitchesgirls.com{href}"); ts.append(text)
            return us, ts

        tasks = [asyncio.create_task(_fetch(u)) for u in page_urls]
        results = await asyncio.gather(*tasks)

    for us, ts in results:
        urls.extend(us); titles.extend(ts)
    return urls, titles

# ---- ThotsLife scraper ----
async def fetch_thotslife(term: str) -> Tuple[List[str], List[str]]:
    next_url = f"https://thotslife.com/?s={term}"
    page_urls = []
    seen = set()
    urls, titles = [], []
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        while next_url:
            page_urls.append(next_url)
            async with session.get(next_url, allow_redirects=True) as resp:
                if resp.status != 200:
                    break
                text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            load_more = soup.find("a", class_="g1-button g1-load-more", attrs={"data-g1-next-page-url": True})
            next_url = load_more["data-g1-next-page-url"] if load_more else None

        async def _fetch(u: str):
            us, ts = [], []
            async with session.get(u, allow_redirects=True) as resp:
                if resp.status != 200:
                    return [], []
                text2 = await resp.text()
            for a in BeautifulSoup(text2, "html.parser").find_all("a", class_="g1-frame"):
                href = a.get("href"); title = a.get("title") or a.text.strip()
                if href not in seen:
                    seen.add(href); us.append(href); ts.append(title)
            return us, ts

        tasks = [asyncio.create_task(_fetch(u)) for u in page_urls]
        results = await asyncio.gather(*tasks)

    for us, ts in results:
        urls.extend(us); titles.extend(ts)
    return urls, titles

# ---- API endpoints ----
@app.get("/api/erome-albums")
async def get_erome_albums(username: str):
    try:
        return {"albums": await fetch_all_album_pages(username)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/erome-gallery")
async def get_erome_gallery(query: str):
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            if query.startswith("http"):
                imgs = await fetch_image_urls(query, session)
            else:
                albums = await fetch_all_album_pages(query)
                imgs = await fetch_all_erome_image_urls(albums)
        return {"images": imgs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/bunkr-gallery")
async def get_bunkr_gallery(query: str):
    try:
        imgs = await fetch_bunkr_gallery_images(query)
        return {"images": imgs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/fapello-gallery")
async def get_fapello_gallery(album_url: str):
    if "fapello.com" not in album_url:
        raise HTTPException(status_code=400, detail="Invalid album URL")
    try:
        m = await fetch_fapello_album_media(album_url)
        return {"images": m["images"], "videos": m["videos"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/jpg5-gallery")
async def get_jpg5_gallery(album_url: str):
    try:
        return {"images": await extract_jpg5_album_media_urls(album_url)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/notfans")
async def get_notfans(search_term: str, debug: bool = False):
    urls, titles = await fetch_notfans(search_term, debug)
    return {"urls": urls, "titles": titles}

@app.get("/api/influencers")
async def get_influencers(term: str):
    urls, titles = await fetch_influencers(term)
    return {"urls": urls, "titles": titles}

@app.get("/api/thothub")
async def get_thothub(term: str):
    urls, titles = await fetch_thothub(term)
    return {"urls": urls, "titles": titles}

@app.get("/api/dirtyship")
async def get_dirtyship(term: str):
    urls, titles = await fetch_dirtyship(term)
    return {"urls": urls, "titles": titles}

@app.get("/api/pimpbunny")
async def get_pimpbunny(term: str):
    urls, titles = await fetch_pimpbunny(term)
    return {"urls": urls, "titles": titles}

@app.get("/api/leakedzone")
async def get_leakedzone(term: str):
    urls, titles = await fetch_leakedzone(term)
    return {"urls": urls, "titles": titles}

@app.get("/api/fanslyleaked")
async def get_fanslyleaked(term: str):
    urls, titles = await fetch_fanslyleaked(term)
    return {"urls": urls, "titles": titles}

@app.get("/api/gotanynudes")
async def get_gotanynudes(term: str):
    urls, titles = await fetch_gotanynudes(term)
    return {"urls": urls, "titles": titles}

@app.get("/api/nsfw247")
async def get_nsfw247(term: str):
    urls, titles = await fetch_nsfw247(term)
    return {"urls": urls, "titles": titles}

@app.get("/api/hornysimp")
async def get_hornysimp(term: str):
    urls, titles = await fetch_hornysimp(term)
    return {"urls": urls, "titles": titles}

@app.get("/api/porntn")
async def get_porntn(term: str):
    urls, titles = await fetch_porntn(term)
    return {"urls": urls, "titles": titles}

@app.get("/api/xxbrits")
async def get_xxbrits(term: str):
    urls, titles = await fetch_xxbrits(term)
    return {"urls": urls, "titles": titles}

@app.get("/api/bitchesgirls")
async def get_bitchesgirls(term: str):
    urls, titles = await fetch_bitchesgirls(term)
    return {"urls": urls, "titles": titles}

@app.get("/api/thotslife")
async def get_thotslife(term: str):
    urls, titles = await fetch_thotslife(term)
    return {"urls": urls, "titles": titles}

@app.get("/api/stats")
async def get_stats():
    return {"totalVisits": total_visits, "onlineUsers": len(active_connections)}

async def broadcast_stats():
    data = json.dumps({"totalVisits": total_visits, "onlineUsers": len(active_connections)})
    for ws in list(active_connections):
        try:
            await ws.send_text(data)
        except:
            active_connections.discard(ws)

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    active_connections.add(ws)
    await broadcast_stats()
    try:
        while True:
            await ws.receive_text()
            await broadcast_stats()
    except WebSocketDisconnect:
        active_connections.discard(ws)
        await broadcast_stats()

def start():
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))

if __name__ == "__main__":
    start()
