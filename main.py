import os
import re
import json
import asyncio
import aiohttp
import secrets
import uvicorn
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Union, Dict, Tuple
from urllib.parse import urljoin
from fastapi import Depends
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, Depends, Body, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from aiohttp import ClientSession
from urllib.parse import quote_plus, urlencode
import urllib.parse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from starlette.middleware.base import BaseHTTPMiddleware
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from urllib.parse import quote, urljoin

# add a desktop‑style UA so fullporner doesn’t block us:
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/114.0.0.0 Safari/537.36"
}
# ─── Path setup ───────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent
USERS_FILE    = BASE_DIR / "users.json"
SERVERS_FILE  = BASE_DIR / "servers.json"
MODELS_FILE   = BASE_DIR / "models.json"
INVITES_FILE  = BASE_DIR / "invites.json"

# ─── Utility to load/save JSON ────────────────────────────────────────────────
def load_json(path: Path, default):
    if not path.exists():
        path.write_text(json.dumps(default, indent=2))
    return json.loads(path.read_text())

def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2))

# ─── FastAPI & Middleware ─────────────────────────────────────────────────────
app = FastAPI()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

class StatsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
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

# ─── Auth Configuration ───────────────────────────────────────────────────────
SECRET_KEY                 = os.getenv("SECRET_KEY", "change_this_to_a_random_secret")
ALGORITHM                  = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1000000

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire    = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

async def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    try:
        payload  = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise JWTError()
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid authentication credentials")
    users = load_json(USERS_FILE, {})
    if username not in users:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return username

# ─── Pydantic Models ─────────────────────────────────────────────────────────
class RegisterIn(BaseModel):
    username:   str
    password:   str
    invite_code: str

class UserIn(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type:   str

class ServerIn(BaseModel):
    name:        str
    description: str
    url:         str
    icon:        str

class ModelIn(BaseModel):
    name:      str
    endpoints: List[dict]

# ─── “Database” Helpers ───────────────────────────────────────────────────────
def load_servers() -> List[dict]:
    return load_json(SERVERS_FILE, [])

def save_servers(servers: List[dict]):
    save_json(SERVERS_FILE, servers)

def load_models() -> List[dict]:
    return load_json(MODELS_FILE, [])

def save_models(models: List[dict]):
    save_json(MODELS_FILE, models)


# ─── Routes ───────────────────────────────────────────────────────────────────
@app.get("/")
async def root(request: Request):
    return templates.TemplateResponse("ok.html", {"request": request})

# ---- Invite Codes (no auth) ----
@app.post("/api/invite-code", status_code=201)
async def generate_invite_code():
    """
    Public: generate a new invite code.
    """
    try:
        invites = load_json(INVITES_FILE, {})
        code = secrets.token_urlsafe(8)
        invites[code] = False
        save_json(INVITES_FILE, invites)
        return {"invite_code": code}
    except Exception as e:
        # this will show up in your server logs
        print("❌ generate_invite_code error:", repr(e))
        raise HTTPException(status_code=500, detail="Internal Server Error")

# ---- Auth Endpoints ----
@app.post("/api/register", status_code=201)
async def register(data: RegisterIn):
    """
    Register a new user *only* if they supply a valid, unused invite code.
    """
    # load and validate invite
    invites = load_json(INVITES_FILE, {})
    if data.invite_code not in invites:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid invite code")
    if invites[data.invite_code] is True:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invite code already used")

    # mark invite used
    invites[data.invite_code] = True
    save_json(INVITES_FILE, invites)

    # now create user
    users = load_json(USERS_FILE, {})
    if data.username in users:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Username already registered")

    users[data.username] = get_password_hash(data.password)
    save_json(USERS_FILE, users)
    return {"msg": "Registered"}

@app.post("/api/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    users  = load_json(USERS_FILE, {})
    hashed = users.get(form_data.username)
    if not hashed or not verify_password(form_data.password, hashed):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"}
        )
    token = create_access_token({"sub": form_data.username})
    return {"access_token": token, "token_type": "bearer"}

# ---- Servers Endpoints ----
@app.get("/api/servers")
async def get_servers():
    return load_servers()

@app.post("/api/servers", status_code=201)
async def add_server(srv: ServerIn):
    servers = load_servers()
    servers.append(srv.dict())
    save_servers(servers)
    return {"msg": "Server added"}

@app.delete("/api/servers/{server_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(
    server_name: str,
):
    servers   = load_servers()
    remaining = [s for s in servers if s["name"] != server_name]
    if len(remaining) == len(servers):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Server not found")
    save_servers(remaining)
    return

# ---- Models Endpoints ----
@app.get("/api/models", response_model=List[ModelIn])
async def get_models():
    return load_models()

@app.post("/api/models", status_code=201)
async def add_model(m: ModelIn):
    models = load_models()
    models.append(m.dict())
    save_models(models)
    return {"msg": "Model added"}

@app.delete("/api/models/{model_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(model_name: str):
    models = load_models()
    remaining = [m for m in models if m.get("name") != model_name]
    if len(remaining) == len(models):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Model not found")
    save_models(remaining)

# ─── FullPorner: single‐page fetch + detect last page ────────────────────────
async def fetch_fullporner_page(session: ClientSession, term: str, page: int):
    url = f"https://fullporner.com/search?q={quote_plus(term)}&p={page}"
    print(f"[DEBUG] fetch_fullporner_page: GET {url}")
    async with session.get(url, headers=HEADERS) as resp:
        print(f"[DEBUG] fetch_fullporner_page: response status={resp.status} for page {page}")
        text = await resp.text()

    soup = BeautifulSoup(text, "html.parser")

    # normalize by removing everything except a–z0–9
    normalized_term = re.sub(r'[^a-z0-9]', '', term.lower())
    print(f"[DEBUG] fetch_fullporner_page: normalized_term='{normalized_term}'")

    videos = []
    for a in soup.find_all("a", class_="popout", href=True):
        href = a["href"]
        title = a.get_text(strip=True)
        norm_title = re.sub(r'[^a-z0-9]', '', title.lower())

        # skip non‐video links
        if href in ("/", "/pornstars", "/category"):
            print(f"[DEBUG] skipping non-video href={href}")
            continue

        # check if normalized_term is _anywhere_ in normalized title
        if normalized_term not in norm_title:
            print(f"[DEBUG] skipping because '{normalized_term}' not in '{norm_title}' (from '{title}')")
            continue

        full_url = f"https://fullporner.com{href}"
        print(f"[DEBUG] found video '{title}' -> {full_url}")
        videos.append((full_url, title))

    print(f"[DEBUG] fetch_fullporner_page: page {page} collected {len(videos)} videos")

    # detect last page number on first page
    last_page = None
    if page == 1:
        nums = [
            int(p.get_text()) for p in soup.find_all("a", class_="page-link", href=True)
            if p.get_text().isdigit()
        ]
        if nums:
            last_page = max(nums)
            print(f"[DEBUG] detected last_page = {last_page}")

    return videos, last_page

# ─── FullPorner: aggregate across all pages ─────────────────────────────────
async def fetch_fullporner(term: str):
    print(f"[DEBUG] fetch_fullporner: starting for term '{term}'")
    async with aiohttp.ClientSession() as session:
        first_videos, last_page = await fetch_fullporner_page(session, term, 1)
        print(f"[DEBUG] first page returned {len(first_videos)} videos, last_page={last_page}")
        if not first_videos:
            print(f"[DEBUG] no videos on first page, aborting")
            return [], []

        all_videos = list(first_videos)
        if last_page and last_page > 1:
            print(f"[DEBUG] scheduling pages 2…{last_page}")
            tasks = [fetch_fullporner_page(session, term, p) for p in range(2, last_page + 1)]
            results = await asyncio.gather(*tasks)
            for idx, (vids, _) in enumerate(results, start=2):
                print(f"[DEBUG] page {idx} returned {len(vids)} videos")
                if not vids:
                    print(f"[DEBUG] stopping at page {idx} (no vids)")
                    break
                all_videos.extend(vids)

        print(f"[DEBUG] total videos fetched = {len(all_videos)}")
        urls, titles = zip(*all_videos) if all_videos else ([], [])
        return list(urls), list(titles)

@app.get("/api/fullporner-videos")
async def get_fullporner_videos(query: str):
    """
    Scrape all video URLs and titles for a search term from FullPorner (with pagination).
    * query: the search term (e.g. pornstar name)
    """
    print(f"[DEBUG] get_fullporner_videos: received query='{query}'")
    try:
        urls, titles = await fetch_fullporner(query)
        print(f"[DEBUG] returning {len(urls)} urls")
        return {"urls": urls, "titles": titles}
    except Exception as e:
        print(f"[ERROR] get_fullporner_videos: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── HQPorner: breadth‐first crawl up to max_pages/max_results ───────────────
async def scrape_hqporner(name: str, max_pages: int = 5, max_results: int = 100, debug: bool = False):
    print(f"[DEBUG] scrape_hqporner: start name='{name}', max_pages={max_pages}, max_results={max_results}")
    base = "https://hqporner.com"
    q = urlencode({'q': name})
    queue = [f"{base}/?{q}"]
    seen_urls = set()
    results_urls = []
    results_titles = []
    normalized_name = "".join(name.lower().split())

    async with ClientSession(headers=HEADERS) as session:
        for page_idx in range(max_pages):
            if not queue:
                print(f"[DEBUG] scrape_hqporner: queue empty at iteration {page_idx}, breaking")
                break
            if len(results_urls) >= max_results:
                print(f"[DEBUG] scrape_hqporner: reached max_results={max_results}, breaking")
                break

            url = queue.pop(0)
            print(f"[DEBUG] scrape_hqporner: fetching page #{page_idx+1} -> {url}")
            async with session.get(url) as resp:
                print(f"[DEBUG] scrape_hqporner: response status={resp.status}")
                html = await resp.text()
            soup = BeautifulSoup(html, 'html.parser')

            # stop if "no results" on first page
            if page_idx == 0 and soup.find(text=re.compile(r"Sorry, I can'?t find porn to your request", re.IGNORECASE)):
                print("[DEBUG] scrape_hqporner: no results on first page, aborting")
                return [], []

            found = 0
            for a in soup.select('a.click-trigger'):
                href = a.get('href', '')
                title = a.get_text(strip=True)
                if not href.startswith('/hdporn/'):
                    continue
                full_url = base + href
                norm_title = "".join(title.lower().split())
                if normalized_name in norm_title and full_url not in seen_urls:
                    seen_urls.add(full_url)
                    results_urls.append(full_url)
                    results_titles.append(title)
                    found += 1
                    print(f"[DEBUG] scrape_hqporner: found video '{title}' -> {full_url}")
                    if len(results_urls) >= max_results:
                        print(f"[DEBUG] scrape_hqporner: hit max_results limit")
                        break

            print(f"[DEBUG] scrape_hqporner: page #{page_idx+1} found {found} new videos")
            if page_idx == 0 and found == 0:
                print("[DEBUG] scrape_hqporner: no matches on first page, aborting")
                return [], []
            if found == 0:
                print(f"[DEBUG] scrape_hqporner: no new videos on page #{page_idx+1}, stopping")
                break

            # queue next page if available
            next_btn = soup.select_one('a.pagi-btn[href*="p="]')
            if next_btn:
                next_href = next_btn['href']
                full_next = base + next_href if next_href.startswith('/') else next_href
                if full_next not in queue:
                    queue.append(full_next)
                    print(f"[DEBUG] scrape_hqporner: queued next page -> {full_next}")

    print(f"[DEBUG] scrape_hqporner: total videos found = {len(results_urls)}")
    return results_urls, results_titles

@app.get("/api/hqporner-videos")
async def get_hqporner_videos(
    query: str,
    max_pages: int = 5,
    max_results: int = 100,
    debug: bool = False
):
    """
    Scrape video URLs and titles from HQPorner.
    * query: search term
    * max_pages: how many pages of search results to crawl (default 5)
    * max_results: cap on total videos returned (default 100)
    * debug: if true, prints debug logs
    """
    print(f"[DEBUG] get_hqporner_videos: received query='{query}', max_pages={max_pages}, max_results={max_results}, debug={debug}")
    try:
        urls, titles = await scrape_hqporner(query, max_pages, max_results, debug)
        print(f"[DEBUG] get_hqporner_videos: returning {len(urls)} urls")
        return {"urls": urls, "titles": titles}
    except Exception as e:
        print(f"[ERROR] get_hqporner_videos: {e}")
        raise HTTPException(status_code=500, detail=str(e))
# ——— PornXP fetch with pagination ———
async def fetch_pornxp(search_term: str):
    """Scrape all video URLs and titles for a pornstar tag from PornXP, across pagination."""
    tag = quote(search_term)
    page = 1
    all_urls, all_titles = [], []

    while True:
        url = f"https://pornxp.com/tags/{tag}" + (f"?page={page}" if page > 1 else "")
        print(f"[DEBUG] Fetching PornXP page {page}: {url}")
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(url) as resp:
                print(f"[DEBUG] Received response: status={resp.status} for page {page}")
                text = await resp.text()
        soup = BeautifulSoup(text, "html.parser")

        # find video links on this page
        links = soup.find_all("a", href=re.compile(r"^/videos/\d+"))
        if not links:
            print(f"[DEBUG] No video links found on page {page}, stopping pagination")
            break

        print(f"[DEBUG] Found {len(links)} video links on page {page}")
        for a in links:
            href = a.get("href")
            full_url = urljoin("https://pornxp.com", href)
            parent = a.parent
            title_div = parent.find("div", class_="item_title")
            title = title_div.get_text(strip=True) if title_div else "No title"
            print(f"[DEBUG] Page {page} video: {full_url}, title: '{title}'")
            all_urls.append(full_url)
            all_titles.append(title)

        # check if there is a next page link by finding pagination anchor with ?page=N+1
        next_link = soup.find("a", href=re.compile(rf"/tags/{tag}\?page={page+1}"))
        if next_link:
            print(f"[DEBUG] Next page {page+1} exists, continuing")
            page += 1
            await asyncio.sleep(0.1)  # polite crawl
        else:
            print(f"[DEBUG] No next page link found after page {page}, ending pagination")
            break

    print(f"[DEBUG] Total PornXP videos scraped: {len(all_urls)}")
    return all_urls, all_titles

def parse_links_and_titles(page_content, pattern, title_class):
    soup = BeautifulSoup(page_content, 'html.parser')
    links = [
        a['href'] for a in soup.find_all('a', href=True)
        if re.match(pattern, a['href'])
    ]
    filtered_links = [link for link in links if link not in IGNORED_LINKS]
    titles = [
        span.get_text() for span in soup.find_all('span', class_=title_class)
    ]

    print(f"DEBUG: Parsed Links - {filtered_links}")
    print(f"DEBUG: Extracted Titles - {titles}")

    return filtered_links, titles

async def get_webpage_content(url: str, session: aiohttp.ClientSession):
    async with session.get(url, allow_redirects=True) as response:
        text = await response.text()
        return text, str(response.url), response.status

VIDEO_THUMB = (
    "https://media.discordapp.net/attachments/"
    "1343576085098664020/1364464992593772644/raw.png"
    "?ex=680bbecc&is=680a6d4c&hm=f5b308c94c60411147c99b5672fb4230791da9c202cce9a2cd5285ebbaa95a02"
    "&=&format=webp&quality=lossless&width=882&height=882"
)

async def get_webpage_content(url: str, session: aiohttp.ClientSession):
    """
    Returns (text, base_url, status_code).
    """
    async with session.get(url) as resp:
        text = await resp.text()
        return text, str(resp.url), resp.status

def extract_album_links(page_content: str) -> List[str]:
    soup = BeautifulSoup(page_content, "html.parser")
    links = {
        a["href"]
        for a in soup.find_all("a", class_="album-link")
        if a.get("href", "").startswith("https://www.erome.com/a/")
    }
    return list(links)

async def fetch_all_album_pages(username: str, max_pages: int = 10) -> List[str]:
    all_links = set()
    async with aiohttp.ClientSession() as session:
        for page in range(1, max_pages + 1):
            search_url = (
                f"https://www.erome.com/search?q="
                f"{urllib.parse.quote(username)}&page={page}"
            )
            text, _, status = await get_webpage_content(search_url, session)
            if status != 200 or not text:
                break
            all_links.update(extract_album_links(text))
    return list(all_links)

async def fetch_image_urls(album_url: str, session: aiohttp.ClientSession) -> List[str]:
    page_content, base_url, _ = await get_webpage_content(album_url, session)
    soup = BeautifulSoup(page_content, "html.parser")
    return [
        urljoin(base_url, img["data-src"])
        for img in soup.find_all("div", class_="img")
        if img.get("data-src") and "/thumb/" not in img["data-src"]
    ]

# ——— UPDATED ———
async def fetch_video_urls(album_url: str, session: aiohttp.ClientSession) -> List[Dict[str, str]]:
    """
    Returns a list of {"url": <video_url>, "thumbnail": <thumbnail_url>}.
    Tries to extract the <video poster="..."> attribute; falls back to VIDEO_THUMB.
    """
    page_content, base_url, _ = await get_webpage_content(album_url, session)
    soup = BeautifulSoup(page_content, "html.parser")

    videos = []
    # Look for <video> tags (with optional poster attr) and their <source> children
    for video_tag in soup.find_all("video"):
        # Determine thumbnail: use poster attr if present, else fallback
        poster_attr = video_tag.get("poster")
        if poster_attr:
            # Make poster absolute URL if needed
            thumbnail_url = urljoin(base_url, poster_attr)
        else:
            thumbnail_url = VIDEO_THUMB

        # Find the first MP4 <source> inside this <video>
        source = video_tag.find("source", {"type": "video/mp4", "src": True})
        if not source:
            continue

        raw_src = source["src"].split("?", 1)[0]
        full_url = urljoin(base_url, raw_src)

        videos.append({
            "url": full_url,
            "thumbnail": thumbnail_url
        })

    return videos

async def fetch_all_erome_media(
    album_urls: List[str]
) -> List[Union[str, Dict[str, str]]]:
    """
    Fetches both image URLs (as plain strings) and video dicts
    from all Erome albums; returns a de-duplicated, ordered list.
    """
    async with aiohttp.ClientSession() as session:
        # For each album, gather image & video fetches in parallel
        tasks = [
            asyncio.gather(
                fetch_image_urls(url, session),
                fetch_video_urls(url, session),
                return_exceptions=False
            )
            for url in album_urls
        ]
        results = await asyncio.gather(*tasks)

    # Flatten into one list
    all_items: List[Union[str, Dict[str, str]]] = []
    for imgs, vids in results:
        all_items.extend(imgs)
        all_items.extend(vids)

    # Dedupe by URL, preserving first-seen order
    seen_urls = set()
    unique_media: List[Union[str, Dict[str, str]]] = []
    for item in all_items:
        url = item["url"] if isinstance(item, dict) else item
        if url not in seen_urls:
            seen_urls.add(url)
            unique_media.append(item)

    return unique_media


IGNORED_LINKS = [
    "https://bunkr-albums.io/", "https://bunkr-albums.io/topvideos",
    "https://bunkr-albums.io/topalbums", "https://bunkr-albums.io/topfiles",
    "https://bunkr-albums.io/topimages"
]

async def get_all_album_links_from_search(username: str, page: int = 1):
    search_url = f"https://bunkr-albums.io/?search={urllib.parse.quote(username)}&page={page}"
    print(f"DEBUG: Bunkr search page {page} URL → {search_url}")
    async with aiohttp.ClientSession() as session:
        async with session.get(search_url) as resp:
            print(f"DEBUG: GET {search_url} → status {resp.status}")
            if resp.status != 200:
                return []
            text = await resp.text()

    links, titles = parse_links_and_titles(
        text,
        r"^https://bunkr\.cr/a/.*",
        "album-title"
    )
    print(f"DEBUG: Found {len(links)} links and {len(titles)} titles on page {page}")

    # If titles list is shorter (or empty), pad with empty strings
    if len(titles) < len(links):
        titles += [""] * (len(links) - len(titles))

    # Now zip will include *all* links
    return [{"url": u, "title": t} for u, t in zip(links, titles)]


async def get_image_links_from_album(album_url: str, session: aiohttp.ClientSession):
    print(f"DEBUG: Fetching Bunkr album page → {album_url}")
    async with session.get(album_url) as resp:
        print(f"DEBUG: GET {album_url} → status {resp.status}")
        if resp.status != 200:
            return []
        text = await resp.text()
    soup = BeautifulSoup(text, "html.parser")
    out = []
    for a in soup.find_all("a", attrs={"aria-label": "download"}, href=True):
        href = a["href"]
        full = "https://bunkr.cr" + href if href.startswith("/f/") else href
        out.append(full)
    print(f"DEBUG: Found {len(out)} raw download links in album")
    return out

async def get_image_url_from_link(link: str, session: aiohttp.ClientSession) -> str:
    print(f"[DEBUG] Opening image page link: {link}")
    try:
        async with session.get(link) as response:
            if response.status != 200:
                print(f"[DEBUG] Received {response.status} for link: {link}. Skipping.")
                return None
            text = await response.text()
    except Exception as e:
        print(f"[DEBUG] Error fetching image page {link}: {e}")
        return None

    soup = BeautifulSoup(text, 'html.parser')
    img_tag = soup.find('img', class_=lambda x: x and "object-cover" in x)
    if img_tag:
        image_url = img_tag.get('src')
        print(f"[DEBUG] Found image URL: {image_url} for page link: {link}")
        try:
            async with session.head(image_url) as head_response:
                if head_response.status != 200:
                    print(f"[DEBUG] HEAD request for image URL {image_url} returned status {head_response.status}. Skipping.")
                    return None
        except Exception as e:
            print(f"[DEBUG] Error during HEAD check for image URL {image_url}: {e}. Skipping.")
            return None
        return image_url

    print(f"[DEBUG] No image tag found on page: {link}")
    return None

IGNORED_LINKS = [
    "https://bunkr-albums.io/", "https://bunkr-albums.io/topvideos",
    "https://bunkr-albums.io/topalbums", "https://bunkr-albums.io/topfiles",
    "https://bunkr-albums.io/topimages"
]

async def get_all_album_links_from_search(username: str, page: int = 1):
    search_url = f"https://bunkr-albums.io/?search={urllib.parse.quote(username)}&page={page}"
    print(f"DEBUG: Bunkr search page {page} URL → {search_url}")
    async with aiohttp.ClientSession() as session:
        async with session.get(search_url) as resp:
            print(f"DEBUG: GET {search_url} → status {resp.status}")
            if resp.status != 200:
                return []
            text = await resp.text()

    links, titles = parse_links_and_titles(
        text,
        r"^https://bunkr\.cr/a/.*",
        "album-title"
    )
    print(f"DEBUG: Found {len(links)} links and {len(titles)} titles on page {page}")

    # If titles list is shorter (or empty), pad with empty strings
    if len(titles) < len(links):
        titles += [""] * (len(links) - len(titles))

    # Return the links, even if titles are missing
    return [{"url": u, "title": t} for u, t in zip(links, titles)]

async def fetch_bunkr_gallery_images(username: str) -> List[str]:
    print(f"DEBUG: Starting Bunkr gallery fetch for '{username}'")
    async with aiohttp.ClientSession() as session:
        albums = await get_all_album_links_from_search(username)
        print(f"DEBUG: Got {len(albums)} album(s) to scan for images")
        tasks = []
        for alb in albums:
            album_url = alb["url"]
            # Skip the ignored links
            if album_url in IGNORED_LINKS:
                print(f"DEBUG: Skipping ignored link: {album_url}")
                continue

            print(f"DEBUG: Fetching image links for album: {album_url}")
            album_links = await get_image_links_from_album(album_url, session)
            print(f"DEBUG: Found {len(album_links)} image page links in album")
            for link in album_links:
                tasks.append(get_image_url_from_link(link, session))
        
        # Gather all image URLs
        results = await asyncio.gather(*tasks)
        valid = [u for u in results if u]  # Filter out None values

        # Validate the URLs to check if they are still accessible
        validated = await asyncio.gather(*(validate_url(u, session) for u in valid))
        final_urls = list({u for u in validated if u})

        print(f"DEBUG: {len(final_urls)} image URLs validated successfully")
        return final_urls

async def validate_url(url: str, session: aiohttp.ClientSession):
    try:
        print(f"DEBUG: Validating URL → {url}")
        async with session.get(url, headers={"Range": "bytes=0-0"}, allow_redirects=True) as r:
            print(f"DEBUG: HEAD-like GET {url} → status {r.status}")
            if r.status == 206:
                return url
    except Exception as e:
        print(f"DEBUG: Error validating {url}: {e}")
    return None

thumb_pattern = re.compile(r"/thumb/")

async def fetch_fapello_page_media(page_url: str, session: aiohttp.ClientSession, username: str) -> dict:
    print(f"[DEBUG] Entering fetch_fapello_page_media: page_url={page_url}, username={username}")
    try:
        content, base, status = await get_webpage_content(page_url, session)
        print(f"[DEBUG] get_webpage_content returned status={status}, base={base}, content_length={len(content) if content else 0}")
        if status != 200:
            print(f"[DEBUG] Non-200 status for {page_url}, returning empty media")
            return {"images": [], "videos": []}

        soup = BeautifulSoup(content, "html.parser")

        raw_imgs = soup.find_all("img")
        imgs = []
        for img in raw_imgs:
            src = img.get("src") or img.get("data-src")
            if not src:
                continue
            if src.startswith("https://fapello.com/content/") and f"/{username}/" in src:
                imgs.append(src)
        print(f"[DEBUG] Found {len(imgs)} raw image URLs on page")

        raw_vids = soup.find_all("source", type="video/mp4", src=True)
        vids = []
        for v in raw_vids:
            src = v["src"]
            if f"/{username}/" in src:
                vids.append(src)
        print(f"[DEBUG] Found {len(vids)} raw video URLs on page")

        unique_imgs = list(set(imgs))
        unique_vids = list(set(vids))
        print(f"[DEBUG] Deduplicated to {len(unique_imgs)} images and {len(unique_vids)} videos")

        return {"images": unique_imgs, "videos": unique_vids}

    except Exception as e:
        print(f"[ERROR] Exception in fetch_fapello_page_media for {page_url}: {e}")
        return {"images": [], "videos": []}


async def fetch_fapello_album_media(album_url: str) -> dict:
    print(f"[DEBUG] Entering fetch_fapello_album_media: album_url={album_url}")
    media = {"images": [], "videos": []}

    parsed = urllib.parse.urlparse(album_url)
    username = parsed.path.strip("/").split("/")[0]
    print(f"[DEBUG] Parsed username={username} from URL")

    async with aiohttp.ClientSession(headers={**HEADERS, "Referer": album_url}) as session:
        content, base, status = await get_webpage_content(album_url, session)
        print(f"[DEBUG] get_webpage_content for album returned status={status}, base={base}, content_length={len(content) if content else 0}")
        if status != 200:
            print(f"[DEBUG] Non-200 status for album {album_url}, returning empty media")
            return media

        soup = BeautifulSoup(content, "html.parser")
        anchors = soup.find_all("a", href=True)
        pages = {
            urllib.parse.urljoin(base, a["href"])
            for a in anchors
            if urllib.parse.urljoin(base, a["href"]).startswith(album_url)
               and re.search(r"/\d+/?$", a["href"])
        }
        print(f"[DEBUG] Discovered {len(pages)} page URLs in album")

        if not pages:
            pages = {album_url}
            print(f"[DEBUG] No numbered pages found, defaulting to album_url only")

        tasks = [fetch_fapello_page_media(p, session, username) for p in pages]
        print(f"[DEBUG] Scheduling {len(tasks)} page-media fetch tasks")
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for idx, res in enumerate(results):
            if isinstance(res, Exception):
                print(f"[ERROR] Task {idx} raised exception: {res}")
                continue
            media["images"].extend(res.get("images", []))
            media["videos"].extend(res.get("videos", []))

    media["images"] = list(set(media["images"]))
    media["videos"] = list(set(media["videos"]))
    print(f"[DEBUG] Final aggregated media count: {len(media['images'])} images, {len(media['videos'])} videos")
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
        items = soup.select('a[href^="https://notfans.com/videos/"]')
        if debug: print(f"[NOTFANS] Found {len(items)} on page1")
        for a in items:
            t = a.find("strong", class_="title")
            if not t: continue
            title = t.get_text(strip=True)
            if term not in title.lower(): continue
            href = a["href"].strip()
            urls.append(href if href.startswith("http") else base + href)
            titles.append(title)
        # pagination via AJAX parameters
        params = [lnk["data-parameters"] for lnk in soup.select('a[data-action="ajax"][data-parameters]')]
        page_urls = []
        for p in params:
            qs = p.replace(":", "=").replace(";", "&")
            page_urls.append(f"{first_url}?{qs}")
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
                us.append(href if href.startswith("http") else base + href)
                ts.append(title)
            return us, ts
        tasks = [asyncio.create_task(_fetch_page(u)) for u in page_urls]
        for us, ts in await asyncio.gather(*tasks):
            urls.extend(us); titles.extend(ts)
    if debug: print(f"[NOTFANS] Total {len(urls)}")
    return urls, titles

async def fetch_influencers(term: str) -> Tuple[List[str], List[str]]:
    urls, titles, page = [], [], 1
    async with aiohttp.ClientSession() as session:
        while True:
            url = f"https://influencersgonewild.com/?s={term}&paged={page}"
            print(f"[influencers] {url}")
            # kick off the GET
            get_task = asyncio.create_task(session.get(url))
            # wait for it via gather
            response, = await asyncio.gather(get_task)
            # then kick off the text() call
            text_task = asyncio.create_task(response.text())
            # and gather its result
            text, = await asyncio.gather(text_task)

            soup = BeautifulSoup(text, "html.parser")
            items = soup.find_all("a", class_="g1-frame")
            if not items:
                break
            for a in items:
                href = a.get("href")
                title = a.get("title") or a.text.strip()
                urls.append(href)
                titles.append(title)
            page += 1
    return urls, titles


async def fetch_thothub(term: str) -> Tuple[List[str], List[str]]:
    urls, titles, seen, page = [], [], set(), 1
    async with aiohttp.ClientSession() as session:
        while True:
            url = f"https://thothub.to/search/{term}/?page={page}"
            print(f"[thothub] {url}")
            # kick off the GET
            get_task = asyncio.create_task(session.get(url))
            # wait for the response
            response, = await asyncio.gather(get_task)
            # kick off the text() extraction
            text_task = asyncio.create_task(response.text())
            # gather the text
            text, = await asyncio.gather(text_task)

            soup = BeautifulSoup(text, "html.parser")
            items = [
                a for a in soup.select('a[title]')
                if not a.find("span", class_="line-private")
            ]
            new = False
            for a in items:
                href, title = a["href"], a["title"]
                if href in seen:
                    continue
                seen.add(href)
                urls.append(href)
                titles.append(title)
                new = True
            if not new:
                break
            page += 1
    return urls, titles


async def fetch_dirtyship(term: str) -> Tuple[List[str], List[str]]:
    urls, titles, page = [], [], 1
    async with aiohttp.ClientSession() as session:
        while True:
            url = f"https://dirtyship.com/page/{page}/?search_param=all&s={term}"
            print(f"[dirtyship] {url}")
            get_task = asyncio.create_task(session.get(url))
            response, = await asyncio.gather(get_task)
            text_task = asyncio.create_task(response.text())
            text, = await asyncio.gather(text_task)

            soup = BeautifulSoup(text, "html.parser")
            items = soup.find_all("a", id="preview_image")
            if not items:
                break
            for a in items:
                href = a["href"]
                title = a.get("title") or a.text.strip()
                urls.append(href); titles.append(title)
            page += 1
    return urls, titles

async def fetch_pimpbunny(term: str) -> Tuple[List[str], List[str]]:
    urls, titles = [], []
    url = f"https://pimpbunny.com/search/{term}/"
    async with aiohttp.ClientSession() as session:
        print(f"[pimpbunny] {url}")
        get_task = asyncio.create_task(session.get(url))
        response, = await asyncio.gather(get_task)
        text_task = asyncio.create_task(response.text())
        text, = await asyncio.gather(text_task)

        soup = BeautifulSoup(text, "html.parser")
        for a in soup.find_all("a", class_="pb-item-link"):
            href = a["href"]
            title = a.get("title") or a.text.strip()
            urls.append(href); titles.append(title)
    return urls, titles

async def fetch_leakedzone(term: str) -> Tuple[List[str], List[str]]:
    urls, titles = [], []
    url = f"https://leakedzone.com/search?search={term}"
    async with aiohttp.ClientSession() as session:
        print(f"[leakedzone] {url}")
        get_task = asyncio.create_task(session.get(url))
        response, = await asyncio.gather(get_task)
        text_task = asyncio.create_task(response.text())
        text, = await asyncio.gather(text_task)

        soup = BeautifulSoup(text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("https://leakedzone.com/") and term.lower().replace(" ", "") in href.lower():
                title = a.get("title") or a.text.strip()
                urls.append(href); titles.append(title)
    return urls, titles

async def fetch_fanslyleaked(term: str) -> Tuple[List[str], List[str]]:
    urls, titles, seen, page = [], [], set(), 1
    async with aiohttp.ClientSession() as session:
        while True:
            url = f"https://ww1.fanslyleaked.com/page/{page}/?s={term}"
            print(f"[fanslyleaked] {url}")
            get_task = asyncio.create_task(session.get(url))
            response, = await asyncio.gather(get_task)
            text_task = asyncio.create_task(response.text())
            text, = await asyncio.gather(text_task)

            soup = BeautifulSoup(text, "html.parser")
            items = soup.find_all("a", href=True, title=True)
            new = False
            for a in items:
                href, title = a["href"], a["title"]
                if href.startswith("/"):
                    href = "https://ww1.fanslyleaked.com" + href
                if not href.startswith("https://ww1.fanslyleaked.com/"):
                    continue
                if any(x in href for x in ["/page/", "?s=", "#"]):
                    continue
                if href in seen:
                    continue
                seen.add(href); urls.append(href); titles.append(title)
                new = True
            if not new:
                break
            page += 1
    return urls, titles

def _normalize(s: str) -> str:
    return "".join(s.lower().split())

async def fetch_gotanynudes(search_term: str) -> Tuple[List[str], List[str]]:
    query = search_term.replace(" ", "+")
    page = 1
    urls, titles = [], []
    normalized = _normalize(search_term)
    async with aiohttp.ClientSession() as session:
        while True:
            url = (
                f"https://gotanynudes.com/?s={query}"
                if page == 1
                else f"https://gotanynudes.com/page/{page}/?s={query}"
            )
            print(f"[gotanynudes] {url}")
            get_task = asyncio.create_task(session.get(url))
            response, = await asyncio.gather(get_task)
            text_task = asyncio.create_task(response.text())
            html, = await asyncio.gather(text_task)

            soup = BeautifulSoup(html, "html.parser")
            found = 0
            for a in soup.find_all("a", class_="g1-frame", title=True, href=True):
                title = a["title"].strip()
                if normalized in _normalize(title):
                    href = a["href"]
                    urls.append(href); titles.append(title)
                    found += 1
            nxt = soup.find("a", class_="g1-load-more", attrs={"data-g1-next-page-url": True})
            if not nxt or found == 0:
                break
            page += 1
    return urls, titles

async def fetch_nsfw247(search_term: str) -> Tuple[List[str], List[str]]:
    query = search_term.replace(" ", "-")
    normalized = _normalize(search_term)
    base = f"https://nsfw247.to/search/{query}-0z5g7jn9"
    urls, titles, page = [], [], 1
    async with aiohttp.ClientSession() as session:
        while True:
            url = base if page == 1 else f"{base}/page/{page}/"
            print(f"[nsfw247] {url}")
            get_task = asyncio.create_task(session.get(url))
            response, = await asyncio.gather(get_task)
            text_task = asyncio.create_task(response.text())
            html, = await asyncio.gather(text_task)

            soup = BeautifulSoup(html, "html.parser")
            found = 0
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not href.startswith("https://nsfw247.to/"):
                    continue
                title = a.get_text(strip=True)
                if normalized in _normalize(title):
                    urls.append(href); titles.append(title); found += 1
            if found == 0:
                break
            page += 1
    return urls, titles

async def fetch_hornysimp(search_term: str) -> Tuple[List[str], List[str]]:
    query = search_term.replace(" ", "+")
    normalized = _normalize(search_term)
    urls, titles, page = [], [], 1
    async with aiohttp.ClientSession() as session:
        while True:
            url = (
                f"https://hornysimp.com/?s={query}"
                if page == 1
                else f"https://hornysimp.com/?s={query}/?_page={page}"
            )
            print(f"[hornysimp] {url}")
            get_task = asyncio.create_task(session.get(url))
            response, = await asyncio.gather(get_task)
            text_task = asyncio.create_task(response.text())
            html, = await asyncio.gather(text_task)

            soup = BeautifulSoup(html, "html.parser")
            found = 0
            for a in soup.find_all("a", href=True, title=True):
                href = a["href"]; title = a["title"].strip()
                if "hornysimp.com" in href and normalized in _normalize(title):
                    urls.append(href); titles.append(title); found += 1
            if found == 0:
                break
            page += 1
    return urls, titles

async def fetch_porntn(search_term: str) -> Tuple[List[str], List[str]]:
    query = search_term.replace(" ", "-")
    base = f"https://porntn.com/search/{query}"
    normalized = _normalize(search_term)
    urls, titles = [], []
    async with aiohttp.ClientSession() as session:
        print(f"[porntn] GET {base}")
        get_task = asyncio.create_task(session.get(base))
        response, = await asyncio.gather(get_task)
        text_task = asyncio.create_task(response.text())
        html, = await asyncio.gather(text_task)

        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True, title=True):
            href, title = a["href"], a["title"].strip()
            if href.startswith("https://porntn.com/videos") and normalized in _normalize(title):
                urls.append(href); titles.append(title)
        offsets = []
        for a in soup.find_all("a", href="#videos", attrs={"data-parameters": True}):
            for part in a["data-parameters"].split(";"):
                if part.startswith("from:"):
                    _, off = part.split(":", 1)
                    if off.isdigit():
                        offsets.append(off)
        for off in offsets:
            page_url = f"{base}/?from={off}"
            print(f"[porntn] GET {page_url}")
            get_task = asyncio.create_task(session.get(page_url))
            response, = await asyncio.gather(get_task)
            text_task = asyncio.create_task(response.text())
            html2, = await asyncio.gather(text_task)

            soup2 = BeautifulSoup(html2, "html.parser")
            found = 0
            for a in soup2.find_all("a", href=True, title=True):
                href, title = a["href"], a["title"].strip()
                if href.startswith("https://porntn.com/videos") and normalized in _normalize(title):
                    urls.append(href); titles.append(title); found += 1
            if found == 0:
                break
    return urls, titles

async def fetch_xxbrits(search_term: str) -> Tuple[List[str], List[str]]:
    query = search_term.replace(" ", "")
    base = f"https://www.xxbrits.com/search/{query}-23cd7b/"
    normalized = _normalize(search_term)
    urls, titles = [], []
    async with aiohttp.ClientSession() as session:
        print(f"[xxbrits] GET {base}")
        get_task = asyncio.create_task(session.get(base))
        response, = await asyncio.gather(get_task)
        text_task = asyncio.create_task(response.text())
        html, = await asyncio.gather(text_task)

        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", class_="item link-post", href=True, title=True):
            title, href = a["title"].strip(), a["href"]
            if normalized in _normalize(title):
                urls.append(href); titles.append(title)
        offsets = []
        for a in soup.find_all("a", href="#search", attrs={"data-parameters": True}):
            for part in a["data-parameters"].split(";"):
                if ":" in part:
                    k, v = part.split(":", 1)
                    if v.isdigit():
                        offsets.append(v)
        for off in offsets:
            page_url = f"{base}?from={off}"
            print(f"[xxbrits] GET {page_url}")
            get_task = asyncio.create_task(session.get(page_url))
            response, = await asyncio.gather(get_task)
            text_task = asyncio.create_task(response.text())
            html2, = await asyncio.gather(text_task)

            soup2 = BeautifulSoup(html2, "html.parser")
            found = 0
            for a in soup2.find_all("a", class_="item link-post", href=True, title=True):
                title, href = a["title"].strip(), a["href"]
                if normalized in _normalize(title):
                    urls.append(href); titles.append(title); found += 1
            if found == 0:
                break
    return urls, titles

async def fetch_bitchesgirls(search_term: str) -> Tuple[List[str], List[str]]:
    query = search_term.replace(" ", "%20")
    normalized = _normalize(search_term)
    urls, titles, page = [], [], 1
    async with aiohttp.ClientSession() as session:
        while True:
            url = f"https://bitchesgirls.com/search/{query}/{page}/"
            print(f"[bitchesgirls] {url}")
            get_task = asyncio.create_task(session.get(url))
            response, = await asyncio.gather(get_task)
            text_task = asyncio.create_task(response.text())
            html, = await asyncio.gather(text_task)

            soup = BeautifulSoup(html, "html.parser")
            found = 0
            for a in soup.find_all("a", href=True):
                href = a["href"]; text = a.get_text(strip=True)
                if href.startswith("/onlyfans/") and normalized in _normalize(text):
                    full = f"https://bitchesgirls.com{href}"
                    urls.append(full); titles.append(text); found += 1
            if found == 0:
                break
            page += 1
    return urls, titles

async def fetch_thotslife(term: str) -> Tuple[List[str], List[str]]:
    urls, titles, seen = [], [], set()
    next_url = f"https://thotslife.com/?s={term}"
    async with aiohttp.ClientSession() as session:
        while next_url:
            print(f"[thotslife] {next_url}")
            get_task = asyncio.create_task(session.get(next_url))
            response, = await asyncio.gather(get_task)
            text_task = asyncio.create_task(response.text())
            text, = await asyncio.gather(text_task)

            soup = BeautifulSoup(text, "html.parser")
            items = soup.find_all("a", class_="g1-frame")
            found = False
            for a in items:
                href = a.get("href"); title = a.get("title") or a.text.strip()
                if href in seen:
                    continue
                seen.add(href); urls.append(href); titles.append(title); found = True
            load_more = soup.find("a", class_="g1-button g1-load-more", attrs={"data-g1-next-page-url": True})
            if not load_more or not found:
                break
            next_url = load_more["data-g1-next-page-url"]
    return urls, titles


# ---- API endpoints for existing scrapers ----

@app.get("/api/erome-albums")
async def get_erome_albums(username: str):
    try:
        return {"albums": await fetch_all_album_pages(username)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

import traceback
from fastapi import HTTPException

@app.get("/api/erome-gallery")
async def get_erome_gallery(query: str):
    try:
        print(f"DEBUG: received query = {query!r}")

        # build album list
        if query.startswith("http"):
            albums = [query]
        else:
            albums = await fetch_all_album_pages(query)
        print(f"DEBUG: fetched album links = {albums}")

        # fetch media
        media = await fetch_all_erome_media(albums)
        print(f"DEBUG: fetched media count = {len(media)}")

        return {"images": media}

    except Exception as e:
        # full traceback to the console/log
        traceback.print_exc()
        # include the message so the client sees something more descriptive
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")
# ─── FastAPI endpoint ────────────────────────────────────────────────────────
@app.get("/api/pornxp-videos")
async def get_pornxp_videos(query: str):
    """
    Scrape all video URLs and titles for a pornstar tag from PornXP (with pagination).
    * query: the pornstar tag to search for
    """
    try:
        urls, titles = await fetch_pornxp(query)
        return {"urls": urls, "titles": titles}
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
        images = await fetch_bunkr_gallery_images(query)
        return {"images": images}
    except Exception as e:
        print(f"[DEBUG] Error: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing Bunkr gallery: {e}")
# Fapello Gallery: no changes needed, but ensure it's registered
@app.get("/api/fapello-gallery")
async def get_fapello_gallery(album_url: str):
    print(f"[DEBUG] get_fapello_gallery called with album_url={album_url}")
    # If the caller passed just a username, build the full URL
    if not album_url.startswith("http"):
        original = album_url
        album_url = f"https://fapello.com/{album_url}"
        print(f"[DEBUG] Converted username '{original}' to full URL: {album_url}")

    if "fapello.com" not in album_url:
        print(f"[ERROR] Invalid album URL: {album_url}")
        raise HTTPException(status_code=400, detail="Invalid album URL")

    try:
        m = await fetch_fapello_album_media(album_url)
        print(f"[DEBUG] Returning {len(m['images'])} images and {len(m['videos'])} videos for {album_url}")
        return {"images": m["images"], "videos": m["videos"]}
    except Exception as e:
        print(f"[ERROR] Exception in get_fapello_gallery: {e}")
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

# ---- Run ----
def start():
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))

if __name__ == "__main__":
    start()
