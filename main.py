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
from fastapi.staticfiles import StaticFiles
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
app.mount("/static", StaticFiles(directory="static"), name="static")
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

# ---- Existing scrapers: Erome, Bunkr, Fapello, JPG5 ----

def extract_album_links(page_content: str) -> List[str]:
    soup = BeautifulSoup(page_content, "html.parser")
    links = set()
    for a in soup.find_all("a", class_="album-link"):
        href = a.get("href")
        if href and href.startswith("https://www.erome.com/a/"):
            links.add(href)
    return list(links)

async def fetch_all_album_pages(username: str, max_pages: int = 10) -> List[str]:
    all_links = set()
    async with aiohttp.ClientSession() as session:
        for page in range(1, max_pages + 1):
            search_url = f"https://www.erome.com/search?q={urllib.parse.quote(username)}&page={page}"
            text, _, status = await get_webpage_content(search_url, session)
            if status != 200 or not text:
                break
            for link in extract_album_links(text):
                all_links.add(link)
    return list(all_links)

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
        tasks = [fetch_image_urls(url, session) for url in album_urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    urls = {u for res in results if isinstance(res, list) for u in res if "/thumb/" not in u}
    return list(urls)

async def get_album_links_from_search(username: str, page: int = 1):
    search_url = f"https://bunkr-albums.io/?search={urllib.parse.quote(username)}&page={page}"
    async with aiohttp.ClientSession() as session:
        async with session.get(search_url) as resp:
            if resp.status != 200:
                return []
            text = await resp.text()
    links, titles = parse_links_and_titles(text, r"^https://bunkr\.cr/a/.*", "album-title")
    return [{"url": u, "title": t} for u, t in zip(links, titles)]

async def get_all_album_links_from_search(username: str):
    albums, page = [], 1
    while True:
        page_albums = await get_album_links_from_search(username, page)
        if not page_albums:
            break
        albums.extend(page_albums)
        # detect next page
        text, _, _ = await get_webpage_content(
            f"https://bunkr-albums.io/?search={urllib.parse.quote(username)}&page={page}",
            aiohttp.ClientSession(),
        )
        soup = BeautifulSoup(text, "html.parser")
        nxt = soup.find("a", href=re.compile(rf"\?search={re.escape(username)}&page={page+1}"), class_="btn btn-sm btn-main")
        if not nxt:
            break
        page += 1
    return albums

async def get_image_links_from_album(album_url: str, session: aiohttp.ClientSession):
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

async def get_image_url_from_link(link: str, session: aiohttp.ClientSession):
    async with session.get(link) as resp:
        if resp.status != 200:
            return None
        text = await resp.text()
    soup = BeautifulSoup(text, "html.parser")
    img = soup.find("img", class_=lambda c: c and "object-cover" in c)
    return img.get("src") if img else None

async def validate_url(url: str, session: aiohttp.ClientSession):
    try:
        async with session.get(url, headers={"Range": "bytes=0-0"}, allow_redirects=True) as r:
            if r.status == 200:
                return url
    except:
        pass
    return None

thumb_pattern = re.compile(r"/thumb/")

async def fetch_bunkr_gallery_images(username: str) -> List[str]:
    async with aiohttp.ClientSession() as session:
        albums = await get_all_album_links_from_search(username)
        tasks = []
        for alb in albums:
            for link in await get_image_links_from_album(alb["url"], session):
                tasks.append(get_image_url_from_link(link, session))
        results = await asyncio.gather(*tasks)
        valid = [u for u in results if u and not thumb_pattern.search(u)]
        validated = await asyncio.gather(*(validate_url(u, session) for u in valid))
        return list({u for u in validated if u})

async def fetch_fapello_page_media(page_url: str, session: aiohttp.ClientSession, username: str) -> dict:
    try:
        content, base, status = await get_webpage_content(page_url, session)
        if status != 200:
            return {"images": [], "videos": []}
        soup = BeautifulSoup(content, "html.parser")
        imgs = [img.get("src") or img.get("data-src")
                for img in soup.find_all("img")
                if img.get("src", "").startswith(f"https://fapello.com/content/") and f"/{username}/" in img.get("src", "")]
        vids = [v["src"] for v in soup.find_all("source", type="video/mp4", src=True)
                if f"/{username}/" in v["src"]]
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
        pages = {urllib.parse.urljoin(base, a["href"])
                 for a in soup.find_all("a", href=True)
                 if urllib.parse.urljoin(base, a["href"]).startswith(album_url) and re.search(r"/\d+/?$", a["href"])}
        if not pages:
            pages = {album_url}
        tasks = [fetch_fapello_page_media(p, session, username) for p in pages]
        for res in await asyncio.gather(*tasks):
            media["images"].extend(res["images"])
            media["videos"].extend(res["videos"])
    media["images"] = list(set(media["images"]))
    media["videos"] = list(set(media["videos"]))
    return media

async def extract_jpg5_album_media_urls(album_url: str) -> List[str]:
    urls = set()
    next_page = album_url.rstrip("/")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        while next_page:
            async with session.get(next_page) as resp:
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

# ---- New functions ----

async def fetch_notfans(search_term: str, debug: bool = False) -> Tuple[List[str], List[str]]:
    base = "https://notfans.com"
    encoded = urllib.parse.quote_plus(search_term)
    first_url = f"{base}/search/{encoded}/"
    term = search_term.lower()
    urls, titles = [], []

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        if debug: print(f"[NOTFANS] GET {first_url}")
        async with session.get(first_url) as resp:
            if resp.status != 200:
                return [], []
            html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        # collect page-1 results
        for a in soup.select('a[href^="https://notfans.com/videos/"]'):
            t = a.find("strong", class_="title")
            if not t: continue
            title = t.get_text(strip=True)
            if term not in title.lower(): continue
            href = a["href"].strip()
            urls.append(href)
            titles.append(title)

        # build all subsequent page URLs
        params = [lnk["data-parameters"] for lnk in soup.select('a[data-action="ajax"][data-parameters]')]
        page_urls = []
        for p in params:
            qs = p.replace(":", "=").replace(";", "&")
            page_urls.append(f"{first_url}?{qs}")

        # define per-page fetch
        async def _fetch_page(u: str):
            if debug: print(f"[NOTFANS] GET {u}")
            try:
                async with session.get(u) as r:
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
                us.append(href)
                ts.append(title)
            return us, ts

        # fetch all pages concurrently
        tasks = [asyncio.create_task(_fetch_page(u)) for u in page_urls]
        for us, ts in await asyncio.gather(*tasks):
            urls.extend(us)
            titles.extend(ts)

    if debug: print(f"[NOTFANS] Total {len(urls)}")
    return urls, titles

async def fetch_influencers(term: str) -> Tuple[List[str], List[str]]:
    urls, titles = [], []
    async with aiohttp.ClientSession() as session:
        # first gather all page URLs by probing until empty
        page = 1
        page_urls = []
        while True:
            u = f"https://influencersgonewild.com/?s={term}&paged={page}"
            async with session.get(u) as r:
                text = await r.text()
            soup = BeautifulSoup(text, "html.parser")
            items = soup.find_all("a", class_="g1-frame")
            if not items:
                break
            page_urls.append(u)
            page += 1

        # define worker
        async def _fetch(u: str):
            local_urls, local_titles = [], []
            async with session.get(u) as r:
                html = await r.text()
            sp = BeautifulSoup(html, "html.parser")
            for a in sp.find_all("a", class_="g1-frame"):
                href = a.get("href")
                title = a.get("title") or a.text.strip()
                local_urls.append(href)
                local_titles.append(title)
            return local_urls, local_titles

        # fetch all pages concurrently
        tasks = [asyncio.create_task(_fetch(u)) for u in page_urls]
        for us, ts in await asyncio.gather(*tasks):
            urls.extend(us)
            titles.extend(ts)

    return urls, titles

async def fetch_thothub(term: str) -> Tuple[List[str], List[str]]:
    base = "https://thothub.to/search"
    urls, titles, seen = [], [], set()

    async with aiohttp.ClientSession() as session:
        # collect first page to find total pages via "page" nav links
        first_url = f"{base}/{term}/?page=1"
        async with session.get(first_url) as r:
            html = await r.text()
        soup = BeautifulSoup(html, "html.parser")
        page_links = soup.select('a[href*="?page="]')
        pages = {int(a["href"].split("page=")[-1]) for a in page_links if a["href"].split("page=")[-1].isdigit()}
        pages.add(1)

        # worker
        async def _fetch(pg: int):
            u = f"{base}/{term}/?page={pg}"
            async with session.get(u) as r:
                h = await r.text()
            sp = BeautifulSoup(h, "html.parser")
            local_urls, local_titles = [], []
            for a in sp.select('a[title]'):
                if a.find("span", class_="line-private"):
                    continue
                href, title = a["href"], a["title"]
                if href in seen:
                    continue
                seen.add(href)
                local_urls.append(href)
                local_titles.append(title)
            return local_urls, local_titles

        tasks = [asyncio.create_task(_fetch(pg)) for pg in sorted(pages)]
        for us, ts in await asyncio.gather(*tasks):
            urls.extend(us)
            titles.extend(ts)

    return urls, titles

async def fetch_dirtyship(term: str) -> Tuple[List[str], List[str]]:
    urls, titles = [], []
    async with aiohttp.ClientSession() as session:
        # determine how many pages
        page = 1
        page_urls = []
        while True:
            u = f"https://dirtyship.com/page/{page}/?search_param=all&s={term}"
            async with session.get(u) as r:
                html = await r.text()
            soup = BeautifulSoup(html, "html.parser")
            if not soup.find_all("a", id="preview_image"):
                break
            page_urls.append(u)
            page += 1

        async def _fetch(u: str):
            local_urls, local_titles = [], []
            async with session.get(u) as r:
                h = await r.text()
            sp = BeautifulSoup(h, "html.parser")
            for a in sp.find_all("a", id="preview_image"):
                href = a["href"]
                title = a.get("title") or a.text.strip()
                local_urls.append(href)
                local_titles.append(title)
            return local_urls, local_titles

        tasks = [asyncio.create_task(_fetch(u)) for u in page_urls]
        for us, ts in await asyncio.gather(*tasks):
            urls.extend(us)
            titles.extend(ts)

    return urls, titles

async def fetch_pimpbunny(term: str) -> Tuple[List[str], List[str]]:
    url = f"https://pimpbunny.com/search/{term}/"
    urls, titles = [], []

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as r:
            html = await r.text()
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", class_="pb-item-link"):
            href = a["href"]
            title = a.get("title") or a.text.strip()
            urls.append(href)
            titles.append(title)

    return urls, titles

async def fetch_leakedzone(term: str) -> Tuple[List[str], List[str]]:
    url = f"https://leakedzone.com/search?search={term}"
    urls, titles = [], []

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as r:
            html = await r.text()
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("https://leakedzone.com/") and term.lower().replace(" ", "") in href.lower():
                title = a.get("title") or a.text.strip()
                urls.append(href)
                titles.append(title)

    return urls, titles

async def fetch_fanslyleaked(term: str) -> Tuple[List[str], List[str]]:
    urls, titles, seen = [], [], set()
    async with aiohttp.ClientSession() as session:
        page = 1
        page_urls = []
        while True:
            u = f"https://ww1.fanslyleaked.com/page/{page}/?s={term}"
            async with session.get(u) as r:
                html = await r.text()
            soup = BeautifulSoup(html, "html.parser")
            items = soup.find_all("a", href=True, title=True)
            if not items:
                break
            page_urls.append(u)
            page += 1

        async def _fetch(u: str):
            local_urls, local_titles = [], []
            async with session.get(u) as r:
                h = await r.text()
            sp = BeautifulSoup(h, "html.parser")
            for a in sp.find_all("a", href=True, title=True):
                href, title = a["href"], a["title"]
                if href.startswith("/"):
                    href = "https://ww1.fanslyleaked.com" + href
                if not href.startswith("https://ww1.fanslyleaked.com/"):
                    continue
                if any(x in href for x in ["/page/", "?s=", "#"]):
                    continue
                if href in seen:
                    continue
                seen.add(href)
                local_urls.append(href)
                local_titles.append(title)
            return local_urls, local_titles

        tasks = [asyncio.create_task(_fetch(u)) for u in page_urls]
        for us, ts in await asyncio.gather(*tasks):
            urls.extend(us)
            titles.extend(ts)

    return urls, titles

# Utility to normalize strings
def _normalize(s: str) -> str:
    return "".join(s.lower().split())

async def fetch_gotanynudes(search_term: str) -> Tuple[List[str], List[str]]:
    query = search_term.replace(" ", "+")
    page = 1
    urls, titles = [], []
    normalized = _normalize(search_term)

    async with aiohttp.ClientSession() as session:
        page_urls = []
        while True:
            u = (
                f"https://gotanynudes.com/?s={query}"
                if page == 1
                else f"https://gotanynudes.com/page/{page}/?s={query}"
            )
            async with session.get(u) as r:
                html = await r.text()
            sp = BeautifulSoup(html, "html.parser")
            found = 0
            for a in sp.find_all("a", class_="g1-frame", title=True, href=True):
                title = a["title"].strip()
                if normalized in _normalize(title):
                    found += 1
            if found == 0:
                break
            page_urls.append(u)
            page += 1

        async def _fetch(u: str):
            local_urls, local_titles = [], []
            async with session.get(u) as r:
                h = await r.text()
            sp = BeautifulSoup(h, "html.parser")
            for a in sp.find_all("a", class_="g1-frame", title=True, href=True):
                title = a["title"].strip()
                if normalized in _normalize(title):
                    local_urls.append(a["href"])
                    local_titles.append(title)
            return local_urls, local_titles

        tasks = [asyncio.create_task(_fetch(u)) for u in page_urls]
        for us, ts in await asyncio.gather(*tasks):
            urls.extend(us)
            titles.extend(ts)

    return urls, titles

async def fetch_nsfw247(search_term: str) -> Tuple[List[str], List[str]]:
    query = search_term.replace(" ", "-")
    normalized = _normalize(search_term)
    base = f"https://nsfw247.to/search/{query}-0z5g7jn9"
    urls, titles = [], []

    async with aiohttp.ClientSession() as session:
        page = 1
        page_urls = []
        while True:
            u = base if page == 1 else f"{base}/page/{page}/"
            async with session.get(u) as r:
                html = await r.text()
            sp = BeautifulSoup(html, "html.parser")
            found = sum(1 for a in sp.find_all("a", href=True)
                        if a["href"].startswith("https://nsfw247.to/") and normalized in _normalize(a.get_text(strip=True)))
            if found == 0:
                break
            page_urls.append(u)
            page += 1

        async def _fetch(u: str):
            local_urls, local_titles = [], []
            async with session.get(u) as r:
                h = await r.text()
            sp = BeautifulSoup(h, "html.parser")
            for a in sp.find_all("a", href=True):
                href = a["href"]
                title = a.get_text(strip=True)
                if href.startswith("https://nsfw247.to/") and normalized in _normalize(title):
                    local_urls.append(href)
                    local_titles.append(title)
            return local_urls, local_titles

        tasks = [asyncio.create_task(_fetch(u)) for u in page_urls]
        for us, ts in await asyncio.gather(*tasks):
            urls.extend(us)
            titles.extend(ts)

    return urls, titles

async def fetch_hornysimp(search_term: str) -> Tuple[List[str], List[str]]:
    query = search_term.replace(" ", "+")
    normalized = _normalize(search_term)
    urls, titles = [], []

    async with aiohttp.ClientSession() as session:
        page = 1
        page_urls = []
        while True:
            u = (f"https://hornysimp.com/?s={query}"
                 if page == 1
                 else f"https://hornysimp.com/?s={query}/?_page={page}")
            async with session.get(u) as r:
                html = await r.text()
            sp = BeautifulSoup(html, "html.parser")
            found = sum(1 for a in sp.find_all("a", href=True, title=True)
                        if "hornysimp.com" in a["href"] and normalized in _normalize(a["title"]))
            if found == 0:
                break
            page_urls.append(u)
            page += 1

        async def _fetch(u: str):
            local_urls, local_titles = [], []
            async with session.get(u) as r:
                h = await r.text()
            sp = BeautifulSoup(h, "html.parser")
            for a in sp.find_all("a", href=True, title=True):
                href, title = a["href"], a["title"].strip()
                if "hornysimp.com" in href and normalized in _normalize(title):
                    local_urls.append(href)
                    local_titles.append(title)
            return local_urls, local_titles

        tasks = [asyncio.create_task(_fetch(u)) for u in page_urls]
        for us, ts in await asyncio.gather(*tasks):
            urls.extend(us)
            titles.extend(ts)

    return urls, titles

async def fetch_porntn(search_term: str) -> Tuple[List[str], List[str]]:
    query = search_term.replace(" ", "-")
    base = f"https://porntn.com/search/{query}"
    normalized = _normalize(search_term)
    urls, titles = [], []

    async with aiohttp.ClientSession() as session:
        # find all offsets
        async with session.get(base) as r:
            html = await r.text()
        soup = BeautifulSoup(html, "html.parser")
        offsets = [part.split(":",1)[1]
                   for a in soup.find_all("a", href="#videos", attrs={"data-parameters": True})
                   for part in a["data-parameters"].split(";")
                   if part.startswith("from:")]

        page_urls = [base] + [f"{base}/?from={off}" for off in offsets]

        async def _fetch(u: str):
            local_urls, local_titles = [], []
            async with session.get(u) as r:
                h = await r.text()
            sp = BeautifulSoup(h, "html.parser")
            for a in sp.find_all("a", href=True, title=True):
                href, title = a["href"], a["title"].strip()
                if href.startswith("https://porntn.com/videos") and normalized in _normalize(title):
                    local_urls.append(href)
                    local_titles.append(title)
            return local_urls, local_titles

        tasks = [asyncio.create_task(_fetch(u)) for u in page_urls]
        for us, ts in await asyncio.gather(*tasks):
            urls.extend(us)
            titles.extend(ts)

    return urls, titles

async def fetch_xxbrits(search_term: str) -> Tuple[List[str], List[str]]:
    query = search_term.replace(" ", "")
    base = f"https://www.xxbrits.com/search/{query}-23cd7b/"
    normalized = _normalize(search_term)
    urls, titles = [], []

    async with aiohttp.ClientSession() as session:
        async with session.get(base) as r:
            html = await r.text()
        soup = BeautifulSoup(html, "html.parser")
        offsets = [part for a in soup.find_all("a", href="#search", attrs={"data-parameters": True})
                   for part in a["data-parameters"].split(";")
                   if ":" in part and part.split(":",1)[1].isdigit()]
        page_urls = [base] + [f"{base}?from={off}" for off in offsets]

        async def _fetch(u: str):
            local_urls, local_titles = [], []
            async with session.get(u) as r:
                h = await r.text()
            sp = BeautifulSoup(h, "html.parser")
            for a in sp.find_all("a", class_="item link-post", href=True, title=True):
                title, href = a["title"].strip(), a["href"]
                if normalized in _normalize(title):
                    local_urls.append(href)
                    local_titles.append(title)
            return local_urls, local_titles

        tasks = [asyncio.create_task(_fetch(u)) for u in page_urls]
        for us, ts in await asyncio.gather(*tasks):
            urls.extend(us)
            titles.extend(ts)

    return urls, titles

async def fetch_bitchesgirls(search_term: str) -> Tuple[List[str], List[str]]:
    query = search_term.replace(" ", "%20")
    normalized = _normalize(search_term)
    urls, titles = [], []

    async with aiohttp.ClientSession() as session:
        page = 1
        page_urls = []
        while True:
            u = f"https://bitchesgirls.com/search/{query}/{page}/"
            async with session.get(u) as r:
                html = await r.text()
            sp = BeautifulSoup(html, "html.parser")
            found = sum(1 for a in sp.find_all("a", href=True)
                        if a["href"].startswith("/onlyfans/") and normalized in _normalize(a.get_text(strip=True)))
            if found == 0:
                break
            page_urls.append(u)
            page += 1

        async def _fetch(u: str):
            local_urls, local_titles = [], []
            async with session.get(u) as r:
                h = await r.text()
            sp = BeautifulSoup(h, "html.parser")
            for a in sp.find_all("a", href=True):
                href = a["href"]
                text = a.get_text(strip=True)
                if href.startswith("/onlyfans/") and normalized in _normalize(text):
                    local_urls.append(f"https://bitchesgirls.com{href}")
                    local_titles.append(text)
            return local_urls, local_titles

        tasks = [asyncio.create_task(_fetch(u)) for u in page_urls]
        for us, ts in await asyncio.gather(*tasks):
            urls.extend(us)
            titles.extend(ts)

    return urls, titles

async def fetch_thotslife(term: str) -> Tuple[List[str], List[str]]:
    urls, titles, seen = [], [], set()
    next_url = f"https://thotslife.com/?s={term}"

    async with aiohttp.ClientSession() as session:
        page_urls = []
        # first pass: gather all “load more” URLs
        while next_url:
            async with session.get(next_url) as r:
                html = await r.text()
            sp = BeautifulSoup(html, "html.parser")
            page_urls.append(next_url)
            load_more = sp.find("a", class_="g1-button g1-load-more", attrs={"data-g1-next-page-url": True})
            if not load_more:
                break
            next_url = load_more["data-g1-next-page-url"]

        async def _fetch(u: str):
            local_urls, local_titles = [], []
            async with session.get(u) as r:
                h = await r.text()
            sp = BeautifulSoup(h, "html.parser")
            for a in sp.find_all("a", class_="g1-frame"):
                href = a["href"]
                title = a.get("title") or a.text.strip()
                if href not in seen:
                    seen.add(href)
                    local_urls.append(href)
                    local_titles.append(title)
            return local_urls, local_titles

        tasks = [asyncio.create_task(_fetch(u)) for u in page_urls]
        for us, ts in await asyncio.gather(*tasks):
            urls.extend(us)
            titles.extend(ts)

    return urls, titles

# --------------------------------------------------------------
# Orchestrator: run *all* of the above in parallel for one term
# --------------------------------------------------------------
async def fetch_all_sites(term: str, debug: bool = False) -> Tuple[List[str], List[str]]:
    funcs = [
        lambda: fetch_notfans(term, debug),
        lambda: fetch_influencers(term),
        lambda: fetch_thothub(term),
        lambda: fetch_dirtyship(term),
        lambda: fetch_pimpbunny(term),
        lambda: fetch_leakedzone(term),
        lambda: fetch_fanslyleaked(term),
        lambda: fetch_gotanynudes(term),
        lambda: fetch_nsfw247(term),
        lambda: fetch_hornysimp(term),
        lambda: fetch_porntn(term),
        lambda: fetch_xxbrits(term),
        lambda: fetch_bitchesgirls(term),
        lambda: fetch_thotslife(term),
    ]
    tasks = [asyncio.create_task(f()) for f in funcs]
    results = await asyncio.gather(*tasks)

    all_urls, all_titles = [], []
    for urls, titles in results:
        all_urls.extend(urls)
        all_titles.extend(titles)

    return all_urls, all_titles
# ---- API endpoints for existing scrapers ----

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

# Bunkr Albums: use `query` param to match front-end
@app.get("/api/bunkr-albums")
async def get_bunkr_albums(query: str):
    try:
        albums = await get_all_album_links_from_search(query)
        return {"albums": albums}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Bunkr Gallery: already expects `query`
@app.get("/api/bunkr-gallery")
async def get_bunkr_gallery(query: str):
    try:
        async with aiohttp.ClientSession() as session:
            if query.startswith("http"):
                pages = await get_image_links_from_album(query, session)
                tasks = [get_image_url_from_link(u, session) for u in pages]
                res = await asyncio.gather(*tasks)
                imgs = [u for u in res if u and not thumb_pattern.search(u)]
            else:
                imgs = await fetch_bunkr_gallery_images(query)
        return {"images": imgs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Fapello Gallery: no changes needed, but ensure it's registered
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

# ---- API endpoints for new scrapers ----

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

# ---- Stats & WebSocket ----
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

# ---- Run ----
def start():
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))

if __name__ == "__main__":
    start()
