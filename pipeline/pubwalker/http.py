"""One cached GET for every remote source. Responses land in data/cache/http/<sha>.json so a
re-run never touches the network. 429/5xx retry with backoff."""
import hashlib
import json
import os
import time

import httpx
from dotenv import load_dotenv

from . import DATA

load_dotenv(DATA.parent / ".env")
CACHE = DATA / "cache" / "http"
UA = f"pubwalker/0.1 (mailto:{os.getenv('OPENALEX_MAILTO') or os.getenv('NCBI_EMAIL') or 'unknown'})"


def get(url, params=None, headers=None, *, text=False):
    key = hashlib.sha256(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
    path = CACHE / (key + (".txt" if text else ".json"))
    if path.exists():
        return path.read_text() if text else json.loads(path.read_text())
    for attempt in range(6):
        r = httpx.get(url, params=params, headers={"User-Agent": UA, **(headers or {})}, timeout=60)
        if r.status_code in (429, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        break
    else:
        r.raise_for_status()
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(r.text)
    return r.text if text else r.json()


def openalex(path, **params):
    if key := os.getenv("OPENALEX_API_KEY"):
        params["api_key"] = key
    if mailto := os.getenv("OPENALEX_MAILTO"):
        params["mailto"] = mailto
    return get("https://api.openalex.org" + path, params)


def s2(path, **params):
    h = {"x-api-key": k} if (k := os.getenv("S2_API_KEY")) else {}
    return get("https://api.semanticscholar.org/graph/v1" + path, params, h)


def epmc(path, **params):
    return get("https://www.ebi.ac.uk/europepmc/webservices/rest" + path, params, text=path.endswith("fullTextXML"))


def ncbi(tool, **params):
    """E-utilities; returns text (efetch XML) or JSON depending on retmode."""
    if key := os.getenv("NCBI_API_KEY"):
        params["api_key"] = key
    if email := os.getenv("NCBI_EMAIL"):
        params["email"] = email
    return get(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/{tool}.fcgi", params, text=params.get("retmode") != "json")
