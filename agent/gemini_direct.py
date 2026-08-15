"""GeminiDirect -- Direct synchronous HTTP client for Gemini Web.

Ported from gemini-web-to-api Go project + gemini_webapi library internals.
Uses curl_cffi synchronous Session with Chrome TLS fingerprint.

Key difference from gemini_webapi: NO async, NO threads, NO event loop.
Everything is synchronous and inline.

Protocol:
  1. GET gemini.google.com/app --> extract session tokens
  2. Upload images --> content-push.googleapis.com/upload
  3. POST StreamGenerate --> parse nested JSON response
"""

import json
import os
import random
import re
import uuid
from typing import List, Optional, Tuple

from curl_cffi.requests import Session, Cookies

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GEMINI_BASE = "https://gemini.google.com"
GOOGLE_BASE = "https://www.google.com/"
INIT_URL = f"{GEMINI_BASE}/app?hl=en"
STREAM_URL = (
    f"{GEMINI_BASE}/_/BardChatUi/data/"
    "assistant.lamda.BardFrontendService/StreamGenerate"
)
UPLOAD_URL = "https://content-push.googleapis.com/upload"

HEADERS_INIT = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "max-age=0",
    "Upgrade-Insecure-Requests": "1",
    "X-Same-Domain": "1",
}

HEADERS_POST = {
    "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
    "Origin": GEMINI_BASE,
    "Referer": f"{GEMINI_BASE}/",
    "X-Same-Domain": "1",
}

# Regex patterns
RE_AT       = re.compile(r'"SNlM0e":\s*"(.*?)"')
RE_AT_FB    = re.compile(r'\["SNlM0e","([^"]+)"\]')
RE_PUSH_ID  = re.compile(r'"qKIAYe":\s*"(.*?)"')
RE_BUILD    = re.compile(r'"cfb2h":\s*"(.*?)"')
RE_SESSION  = re.compile(r'"FdrFJe":\s*"(.*?)"')
RE_LANGUAGE = re.compile(r'"TuX5cc":\s*"(.*?)"')
RE_MODEL_ID = re.compile(r'gemini-[a-zA-Z0-9._-]+')


class GeminiDirectError(RuntimeError):
    pass


class GeminiDirectClient:
    """GeminiDirect — synchronous Gemini Web client ported from Go.

No gemini_webapi dependency. Uses curl_cffi for Chrome TLS fingerprinting.
Supports HTTP/HTTPS proxy via HTTP_PROXY / HTTPS_PROXY env vars.
"""

    def __init__(self, psid: str, psidts: str = "", timeout: float = 120):
        self.psid = psid.strip()
        self.psidts = psidts.strip()
        self.timeout = timeout

        # Session fields (populated by init)
        self.access_token: Optional[str] = None
        self.push_id = "feeds/mcudyrk2a4khkz"
        self.build_label = ""
        self.session_id = ""
        self.language = "en"
        self.available_models: List[str] = []
        self._reqid: int = random.randint(10000, 99999)

        # Proxy support (college/corporate networks)
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or ""
        proxies = {"https": proxy, "http": proxy} if proxy else None
        if proxy:
            # Mask password in log
            display = proxy
            if "@" in proxy:
                display = proxy.split("@")[-1]
            print(f"[GeminiDirect] Using proxy: {display}")

        # curl_cffi synchronous session with Chrome fingerprint
        self._session = Session(
            impersonate="chrome131",
            verify=False,
            allow_redirects=True,
            proxies=proxies,
        )

    # -- Initialization ----------------------------------------------------

    def init(self):
        """Initialize: fetch session tokens from Gemini web page."""
        # Step 1: Preflight google.com (gathers NID cookie etc.)
        try:
            self._session.get(GOOGLE_BASE, timeout=15)
        except Exception:
            pass

        # Step 2: Set auth cookies
        self._session.cookies.set(
            "__Secure-1PSID", self.psid, domain=".google.com"
        )
        if self.psidts:
            self._session.cookies.set(
                "__Secure-1PSIDTS", self.psidts, domain=".google.com"
            )

        # Step 3: Hit gemini.google.com (gathers more cookies)
        try:
            self._session.get(f"{GEMINI_BASE}/?hl=en", timeout=15)
        except Exception:
            pass

        # Step 4: GET /app?hl=en -- extract session data
        r = self._session.get(INIT_URL, headers=HEADERS_INIT, timeout=30)
        r.raise_for_status()
        body = r.text

        # Extract session fields
        m = RE_AT.search(body)
        if not m:
            m = RE_AT_FB.search(body)
        # CRITICAL: use empty string, never None — curl_cffi sends
        # the literal string "None" which Google rejects as 1100
        self.access_token = m.group(1) if m else ""

        m = RE_BUILD.search(body)
        self.build_label = m.group(1) if m else ""

        m = RE_SESSION.search(body)
        self.session_id = m.group(1) if m else ""

        m = RE_PUSH_ID.search(body)
        self.push_id = m.group(1) if m else "feeds/mcudyrk2a4khkz"

        m = RE_LANGUAGE.search(body)
        self.language = m.group(1) if m else "en"

        # Verify at least build_label or session_id was found
        if not self.build_label and not self.session_id:
            raise GeminiDirectError(
                "Could not extract session data. Cookies may be expired.\n"
                "Run `python setup_gemini.py` to refresh cookies."
            )

        # Discover available models
        self.available_models = self._discover_models(body)
        self._reqid = random.randint(10000, 99999)

        at_str = f"...{self.access_token[-8:]}" if self.access_token else "(empty)"
        print(f"[GeminiDirect] Session OK -- at={at_str}")
        print(f"[GeminiDirect] Build: {self.build_label}")
        print(f"[GeminiDirect] Models: {', '.join(self.available_models[:5])}")

    def reinit(self):
        """Re-initialize session (refresh cookies and tokens)."""
        print("[GeminiDirect] Refreshing session...")
        self._session.cookies.clear()
        self.init()

    def _discover_models(self, html: str) -> List[str]:
        """Extract model IDs from the page HTML."""
        seen = set()
        result = []
        for m in RE_MODEL_ID.finditer(html):
            name = m.group(0)
            if name not in seen and re.match(r'^gemini-(\d|advanced)', name):
                seen.add(name)
                result.append(name)
        return result or ["gemini-2.5-flash"]

    # -- Image Upload ------------------------------------------------------

    def upload_image(
        self, image_bytes: bytes, filename: str, mime: str
    ) -> str:
        """Upload an image and return the file ID."""
        from curl_cffi import CurlMime

        mp = CurlMime()
        mp.addpart(
            name="file",
            filename=filename,
            content_type=mime,
            data=image_bytes,
        )
        r = self._session.post(
            UPLOAD_URL,
            headers={
                "X-Tenant-Id": "bard-storage",
                "Push-ID": self.push_id,
            },
            multipart=mp,
            timeout=60,
        )
        r.raise_for_status()
        file_id = r.text.strip()
        if not file_id:
            raise GeminiDirectError("Image upload returned empty file ID.")
        return file_id

    # -- Content Generation ------------------------------------------------

    def generate(
        self,
        prompt: str,
        model: str = "",
        images: Optional[List[Tuple[bytes, str]]] = None,
        temporary: bool = True,
    ) -> str:
        """Generate content and return response text."""
        if not model:
            model = (
                self.available_models[0]
                if self.available_models
                else "gemini-2.5-flash"
            )

        # Upload images if present
        file_entries = []
        if images:
            for i, (img_bytes, mime) in enumerate(images):
                ext = "jpg" if "jpeg" in mime else "png"
                fname = f"screenshot_{i}.{ext}"
                file_id = self.upload_image(img_bytes, fname, mime)
                file_entries.append([[file_id], fname])

        # Build message content (index 0)
        if file_entries:
            msg_content = [prompt, 0, None, file_entries, None, None, 0]
        else:
            msg_content = [prompt]

        # Build 69-element inner request array (Google's protobuf structure)
        request_uuid = str(uuid.uuid4()).upper()

        inner = [None] * 69
        inner[0] = msg_content
        inner[1] = [self.language]
        inner[2] = ["", "", "", None, None, None, None, None, None, ""]
        inner[3] = model
        inner[6] = [1]
        inner[7] = 1
        inner[10] = 1
        inner[11] = 0
        inner[17] = [[0]]
        inner[18] = 0
        inner[27] = 1
        inner[30] = [4]
        inner[41] = [1]
        if temporary:
            inner[45] = 1
        inner[53] = 0
        inner[59] = request_uuid
        inner[61] = []
        if temporary:
            inner[67] = 0
        inner[68] = 2

        inner_json = json.dumps(inner, ensure_ascii=False)
        outer_json = json.dumps([None, inner_json], ensure_ascii=False)

        # URL params (matches gemini_webapi format)
        self._reqid += 100000
        params = {
            "hl": self.language,
            "_reqid": self._reqid,
            "rt": "c",
        }
        if self.build_label:
            params["bl"] = self.build_label
        if self.session_id:
            params["f.sid"] = self.session_id

        # Headers
        headers = {
            **HEADERS_POST,
            "x-goog-ext-525005358-jspb": f'["{request_uuid}",1]',
        }

        # Form data (matches gemini_webapi format exactly)
        # access_token must be string (empty string OK, but NOT None)
        at_value = self.access_token if self.access_token else ""
        form_data = {
            "at": at_value,
            "f.req": json.dumps(
                [None, inner_json]
            ),
        }

        r = self._session.post(
            STREAM_URL,
            params=params,
            headers=headers,
            data=form_data,
            timeout=self.timeout,
        )

        if r.status_code != 200:
            raise GeminiDirectError(
                f"Failed to generate contents. Status: {r.status_code}"
            )

        return self._parse_response(r.text)

    # -- Response Parsing --------------------------------------------------

    def _parse_response(self, raw: str) -> str:
        """Parse Gemini's streaming response format into clean text."""
        lines = raw.split("\n")
        all_text = []

        for line in lines:
            line = line.strip()
            if line.startswith(")]}'"):
                line = line[4:].strip()
            if not line:
                continue

            try:
                root = json.loads(line)
            except json.JSONDecodeError:
                continue

            if not isinstance(root, list):
                continue

            # Check for errors
            self._check_bard_error(root)

            # Extract payload
            for item in root:
                if not isinstance(item, list) or len(item) < 3:
                    continue
                payload_str = item[2] if isinstance(item[2], str) else None
                if not payload_str:
                    continue

                try:
                    payload = json.loads(payload_str)
                except json.JSONDecodeError:
                    continue

                if not isinstance(payload, list) or len(payload) < 5:
                    continue

                candidates = payload[4]
                if not isinstance(candidates, list) or not candidates:
                    continue

                choice = candidates[0]
                if not isinstance(choice, list) or len(choice) < 2:
                    continue

                text_list = choice[1]
                if isinstance(text_list, list) and text_list:
                    text = text_list[0]
                    if isinstance(text, str) and text.strip():
                        text = self._strip_thinking(text)
                        all_text.append(text)

        if not all_text:
            raise GeminiDirectError("No text found in Gemini response.")

        return all_text[-1]

    def _check_bard_error(self, root):
        """Check for BardErrorInfo in the response."""
        raw = json.dumps(root)
        if "BardErrorInfo" in raw:
            raise GeminiDirectError(f"Gemini returned BardError: {raw[:300]}")

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """Remove <thought>...</thought> tags from response."""
        text = re.sub(r'<thought>.*?</thought>', '', text, flags=re.DOTALL)
        return text.strip()

    # -- Cleanup -----------------------------------------------------------

    def close(self):
        """Close the HTTP session."""
        try:
            self._session.close()
        except Exception:
            pass
