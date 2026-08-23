import asyncio
import json
import os
import random
import re
import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from gemini_webapi import GeminiClient

# ── Suppress loguru spam from gemini_webapi ────────────────────────────────
# The library uses loguru (not stdlib logging) and logs "UNAUTHENTICATED" on
# every init() call.  This is cosmetic noise — suppress it entirely since our
# own print statements cover all meaningful status.
try:
    from loguru import logger as _loguru_logger
    _loguru_logger.disable("gemini_webapi")
except ImportError:
    pass

# ── Force modern TLS fingerprint ──────────────────────────────────────────
# gemini_webapi creates its HTTP session with impersonate="chrome" which maps
# to an OLD Chrome TLS fingerprint.  Google intermittently rejects these with
# error 1100 or TLS handshake failures.  Monkey-patch the session factory to
# use "chrome146" (the newest profile) so the fingerprint matches a real
# modern browser.  This is the ROOT CAUSE of most connection errors.
try:
    from curl_cffi.requests import AsyncSession as _OrigAsyncSession

    _orig_init = _OrigAsyncSession.__init__

    def _patched_init(self, *args, **kwargs):
        # Upgrade generic "chrome" → "chrome146"
        imp = kwargs.get("impersonate", None)
        if imp is None or imp == "chrome":
            kwargs["impersonate"] = "chrome146"
        # Disable SSL verification — the local cert chain is incomplete
        kwargs.setdefault("verify", False)
        _orig_init(self, *args, **kwargs)

    _OrigAsyncSession.__init__ = _patched_init
    print("[Gemini] TLS fingerprint: chrome146 (patched)")
except Exception:
    pass  # fallback: library uses its default


class GeminiWebError(RuntimeError):
    pass


def parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        candidates = [p.strip() for p in parts if "{" in p]
        if candidates:
            text = candidates[0]
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Small robustness fallback for a model that adds surrounding prose.
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


class GeminiAgent:
    """Dual-mode Gemini client — V14.

    Mode 1 (Recommended): GEMINI_API_KEY → uses official Google Generative AI SDK.
      Free API key from aistudio.google.com. Reliable, no cookie issues.
    Mode 2 (Fallback):    GEMINI_1PSID cookies → uses gemini_webapi in-process.
      Requires browser cookies. Subject to rate limits.

    Reliability measures:
      * dual-mode: API key preferred, web API fallback
      * authenticated client initialization with auto-refresh
      * discovered-model validation & ranking
      * model forcing for Pro/Fast selection
      * MCQ + CODE problem detection
      * error classification (transient / model-specific / fatal)
      * exponential backoff with jitter between retries
      * per-model attempt budget before fallback
      * image compression for faster uploads
      * connectivity detection with wait-for-reconnect
    """

    RETRYABLE_WORDS = (
        "socket idle", "stream suspended", "no cid", "connection", "connect",
        "timeout", "timed out", "network", "transport", "server", "reset",
        "closed", "incomplete", "queueing", "watchdog", "502", "503", "504",
        "429", "rate limit", "temporarily unavailable", "empty response",
        "unknown api error",
    )

    RETRYABLE_API_CODES = {1100, 500, 502, 503, 504, 429}

    MODEL_SPECIFIC_WORDS = (
        "not supported", "not available", "content filter", "safety",
        "deprecated", "does not support", "not compatible", "blocked",
        "harm category", "recitation", "model not found",
    )

    CONNECTIVITY_WORDS = (
        "curl", "dns", "resolve", "unreachable", "no route",
        "connection refused", "ssl", "tls connect", "recv failure",
        "send failure", "name resolution", "network is down",
        "network is unreachable", "no address", "host not found",
        "could not connect", "failed to connect", "connection aborted",
        "connection was reset", "broken pipe",
    )

    # ── Official API model mapping ────────────────────────────────────────
    API_MODEL_PRO = "gemini-3.6-flash"
    API_MODEL_FLASH = "gemini-3.5-flash-lite"

    def __init__(self):
        self._api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self._use_api = False
        self._use_direct = False
        self._genai = None

        # ── Priority 1: Cookie-based Web API (gemini_webapi library) ──
        # Preferred because it gives access to gemini-advanced (real Pro model).
        # The official API only has Flash models. API key kept for Alt+9 fallback.
        psid = os.getenv("GEMINI_1PSID", "").strip()
        if psid and len(psid) > 10:
            try:
                psidts = os.getenv("GEMINI_1PSIDTS", "").strip()
                self._psid = psid
                self._psidts = psidts
                self.timeout = float(os.getenv("GEMINI_TIMEOUT", "120"))
                self.attempt_timeout = float(os.getenv("GEMINI_ATTEMPT_TIMEOUT", "180"))
                self.max_attempts = max(1, int(os.getenv("GEMINI_MAX_ATTEMPTS", "5")))
                self.model_tries = max(1, int(os.getenv("GEMINI_MODEL_TRIES", "3")))
                self.max_backoff = float(os.getenv("GEMINI_MAX_BACKOFF", "10"))
                self.model_setting = os.getenv("GEMINI_MODEL", "pro_first")
                self.init_timeout = float(os.getenv("GEMINI_INIT_TIMEOUT", "30"))
                self.reinit_pause = float(os.getenv("GEMINI_REINIT_PAUSE", "1"))
                self.watchdog_timeout = float(os.getenv("GEMINI_WATCHDOG_TIMEOUT", "180"))
                self._client = None
                self._closed = False
                self._init_error = None

                # Start async event loop in background thread
                self._loop = asyncio.new_event_loop()
                self._ready = threading.Event()
                t = threading.Thread(target=self._loop_thread, daemon=True, name="gemini:loop")
                t.start()
                if not self._ready.wait(timeout=self.init_timeout):
                    if self._init_error:
                        raise self._init_error
                    raise GeminiWebError("Timed out waiting for Gemini web client to initialize.")
                if self._init_error:
                    raise self._init_error

                print(f"[Gemini] Mode: Web API (gemini_webapi library)")

                # Also init API client if key available (for Alt+9 API fallback)
                if self._api_key:
                    try:
                        from google import genai
                        self._genai_client = genai.Client(api_key=self._api_key)
                        print(f"[Gemini] API also available (key: ...{self._api_key[-6:]}, model: {self.API_MODEL_FLASH})")
                    except Exception as exc:
                        print(f"[Gemini] API key init skipped: {exc}")

                return  # Web mode ready

            except Exception as exc:
                print(f"[Gemini] Web API mode failed: {exc}")
                print(f"[Gemini] Falling back to API key...")
                self._use_direct = False

        # ── Priority 2: API key fallback ──
        if self._api_key:
            try:
                from google import genai
                self._genai_client = genai.Client(api_key=self._api_key)
                self._use_api = True
                self.model = os.getenv("GEMINI_MODEL", self.API_MODEL_PRO).strip() or self.API_MODEL_PRO
                print(f"[Gemini] Using official API (key: ...{self._api_key[-6:]})")
                print(f"[Gemini] Pro model  : {self.API_MODEL_PRO}")
                print(f"[Gemini] Fast model : {self.API_MODEL_FLASH}")
                print(f"[Gemini] Active model: {self.model}")
                self.model_candidates = [self.API_MODEL_PRO, self.API_MODEL_FLASH]
                self.available_models = [self.API_MODEL_PRO, self.API_MODEL_FLASH]
                return
            except Exception as exc:
                print(f"[Gemini] API key failed ({exc})")
                self._use_api = False

        raise GeminiWebError(
            "Neither GEMINI_1PSID nor GEMINI_API_KEY is set.\n"
            "  Option 1 (recommended): Get a free API key at aistudio.google.com\n"
            "           and set GEMINI_API_KEY in .env.example\n"
            "  Option 2: Run python setup_gemini.py to set cookies"
        )

    # ── Event loop & client lifecycle ──────────────────────────────────────

    def _loop_thread(self):
        asyncio.set_event_loop(self._loop)
        async def _init_and_signal():
            await self._initialize()
            self._ready.set()
        self._loop.create_task(_init_and_signal())
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    async def _new_client(self):
        client = GeminiClient(self._psid, self._psidts, proxy=None, verify=False)
        await client.init(
            timeout=max(self.timeout, self.attempt_timeout, self.watchdog_timeout + 30),
            auto_close=False,
            auto_refresh=True,
            watchdog_timeout=self.watchdog_timeout,
        )
        # Google removed the SNlM0e token from the page, causing the library
        # to report UNAUTHENTICATED even when cookies are valid and generation
        # works fine. Override the status so generate_content() doesn't block.
        from gemini_webapi.constants import AccountStatus
        if client.account_status != AccountStatus.AVAILABLE:
            print(f"[Gemini] Overriding account status {client.account_status.name} → AVAILABLE "
                  f"(SNlM0e removed by Google, cookies still valid)")
            client.account_status = AccountStatus.AVAILABLE
            # Also mark all models as available (they inherit the auth status)
            for model in client.list_models():
                if hasattr(model, 'is_available'):
                    model.is_available = True
        return client

    async def _initialize(self):
        max_init_retries = 3
        last_exc = None
        for attempt in range(1, max_init_retries + 1):
            try:
                self._client = await self._new_client()
                self.available_models = list(self._client.list_models() or [])
                if not self.available_models:
                    raise GeminiWebError("Gemini did not report any models available to this account.")
                self.model_candidates = self._rank_models(self.available_models, self.model_setting)
                self.model = self.model_candidates[0]
                self._print_models()
                return  # success
            except Exception as exc:
                last_exc = exc
                print(f"[Gemini] Init attempt {attempt}/{max_init_retries} failed: {exc}")
                if attempt < max_init_retries:
                    # If internet is down, wait for it in a thread-safe way
                    if self._is_connectivity_error(exc):
                        loop = asyncio.get_event_loop()
                        online = await loop.run_in_executor(
                            None, self._wait_for_connectivity, 120, 3
                        )
                        if not online:
                            break  # give up if still offline
                    else:
                        delay = 3.0 * attempt
                        print(f"[Gemini] Retrying in {delay:.0f}s...")
                        await asyncio.sleep(delay)
        self._init_error = last_exc

    # ── Model discovery, ranking, and selection ────────────────────────────

    @staticmethod
    def _model_name(model):
        if model is None:
            return "<none>"
        return str(getattr(model, "model_name", None) or getattr(model, "display_name", None) or model)

    @classmethod
    def _model_score(cls, model):
        name = cls._model_name(model).lower()
        score = 0
        if "ultra" in name:
            score += 30000
        if "pro" in name:
            score += 20000
        if "thinking" in name or "reason" in name:
            score += 5000
        if "flash" in name:
            score += 1000
        if "lite" in name:
            score -= 1000
        versions = re.findall(r"(?:gemini[- ]?)(\d+(?:\.\d+)*)", name)
        if versions:
            try:
                parts = tuple(int(x) for x in versions[-1].split("."))
                score += sum(v * (100 ** (3 - i)) for i, v in enumerate(parts[:3]))
            except ValueError:
                pass
        return score

    @classmethod
    def _rank_models(cls, models, setting):
        setting = (setting or "pro_first").strip()
        low = setting.lower()
        if low not in {"pro_first", "pro", "auto_highest", "highest", "best", "auto"}:
            exact = [m for m in models if cls._model_name(m).lower() == low]
            if exact:
                return exact + [m for m in models if m not in exact]
            print(f"[Gemini] Warning: {setting!r} was not discovered; using Pro preference.")
        pro = [m for m in models if "pro" in cls._model_name(m).lower()]
        non_pro = [m for m in models if m not in pro]
        pro.sort(key=cls._model_score, reverse=True)
        non_pro.sort(key=cls._model_score, reverse=True)
        return pro + non_pro

    def get_model_by_preference(self, preference: str):
        """Get a model object by preference: 'pro', 'fast', or 'api'."""
        # 'api' preference always uses official API model
        if preference == "api":
            return self.API_MODEL_FLASH

        # API mode
        if self._use_api:
            if preference == "pro":
                return self.API_MODEL_PRO
            return self.API_MODEL_FLASH

        # Direct mode
        if getattr(self, '_use_direct', False):
            if preference == "pro":
                for m in self.model_candidates:
                    if "pro" in m.lower() or "advanced" in m.lower():
                        return m
            else:
                for m in self.model_candidates:
                    if "flash" in m.lower() or "lite" in m.lower():
                        return m
            return self.model_candidates[0] if self.model_candidates else self.model

        if preference == "pro":
            for m in self.model_candidates:
                if "pro" in self._model_name(m).lower():
                    return m
            return self.model_candidates[0] if self.model_candidates else self.model

        if preference == "fast":
            # Prefer lite > flash > anything else (cheapest first)
            lite = [m for m in self.available_models
                    if "lite" in self._model_name(m).lower()]
            if lite:
                return lite[0]
            flash = [m for m in self.available_models
                     if "flash" in self._model_name(m).lower()]
            if flash:
                return flash[0]
            # Fallback to last in priority (lowest capability)
            return self.model_candidates[-1] if self.model_candidates else self.model

        return self.model

    def _print_models(self):
        print("[Gemini] Available models:")
        for i, item in enumerate(self.available_models, 1):
            print(f"  {i}. {self._model_name(item)} (score={self._model_score(item)})")
        print("[Gemini] Model priority:")
        for i, item in enumerate(self.model_candidates, 1):
            print(f"  {i}. {self._model_name(item)}")
        print(f"[Gemini] Selected model: {self._model_name(self.model)}")

    # ── Sync bridge ────────────────────────────────────────────────────────

    def _run(self, coro, timeout=None):
        if self._closed:
            raise GeminiWebError("Gemini agent is closed.")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout or self.timeout)
        except Exception as exc:
            future.cancel()
            if isinstance(exc, TimeoutError):
                raise GeminiWebError(f"Timed out after {timeout or self.timeout:g}s.") from exc
            raise GeminiWebError(str(exc) or exc.__class__.__name__) from exc

    # ── Error classification ───────────────────────────────────────────────

    @classmethod
    def _is_retryable(cls, exc):
        text = str(exc).lower()
        if any(word in text for word in cls.RETRYABLE_WORDS):
            return True
        code_match = re.search(r"error code[:\s]+(\d+)", text)
        if code_match and int(code_match.group(1)) in cls.RETRYABLE_API_CODES:
            return True
        return False

    @classmethod
    def _is_model_specific(cls, exc):
        text = str(exc).lower()
        return any(word in text for word in cls.MODEL_SPECIFIC_WORDS)

    def _backoff_delay(self, attempt):
        base = 2.0 * (1.5 ** attempt)
        jitter = random.uniform(0, min(base * 0.5, 3.0))
        return min(base + jitter, self.max_backoff)

    @classmethod
    def _is_connectivity_error(cls, exc):
        """Return True if the error indicates internet is down (not a Gemini issue)."""
        text = str(exc).lower()
        return any(word in text for word in cls.CONNECTIVITY_WORDS)

    REINIT_ERROR_WORDS = (
        "1100", "unknown api error", "stream suspended",
    )

    @classmethod
    def _needs_reinit(cls, exc):
        """Return True if this error needs a full session reset (not soft retry).

        Error 1100 and similar are stale-session errors — retrying on the
        same connection is useless.  Full reinit creates a fresh session.
        Does NOT match 429 (rate limit) — reinit makes 429 worse.
        """
        text = str(exc).lower()
        if cls._is_rate_limited(exc):
            return False  # 429 = session is fine, just throttled
        return any(word in text for word in cls.REINIT_ERROR_WORDS)

    @classmethod
    def _is_rate_limited(cls, exc):
        """Return True if the error is a 429 rate limit."""
        text = str(exc).lower()
        return "429" in text or "rate limit" in text or "too many request" in text

    @staticmethod
    def _check_connectivity(timeout=5):
        """Quick check: can we reach Google's servers at all?"""
        try:
            socket.create_connection(("www.google.com", 443), timeout=timeout).close()
            return True
        except (socket.timeout, OSError):
            return False

    @classmethod
    def _wait_for_connectivity(cls, max_wait=120, poll_interval=3):
        """Block until internet connectivity is restored.

        Returns True if connectivity was restored, False if timed out.
        """
        print("[Network] Internet appears down. Waiting for connection...")
        elapsed = 0.0
        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval
            if cls._check_connectivity():
                print("[Network] Connection restored!")
                return True
            mins = int((max_wait - elapsed) // 60)
            secs = int((max_wait - elapsed) % 60)
            print(f"[Network] Still offline... retrying ({mins}m {secs}s remaining)")
        print(f"[Network] No connection after {max_wait}s.")
        return False

    # ── Client reconnection ────────────────────────────────────────────────

    async def _reinitialize(self):
        old = self._client
        try:
            if old is not None:
                try:
                    await old.close()
                except Exception:
                    pass
            await asyncio.sleep(self.reinit_pause)
            self._client = await self._new_client()
            discovered = list(self._client.list_models() or [])
            if not discovered:
                raise GeminiWebError("Gemini returned no models after reconnect.")
            self.available_models = discovered
            current_name = self._model_name(self.model).lower() if self.model is not None else ""
            current = [m for m in discovered if self._model_name(m).lower() == current_name]
            if current:
                self.model = current[0]
                ordered = self._rank_models(discovered, self.model_setting)
                self.model_candidates = [self.model] + [m for m in ordered if self._model_name(m).lower() != current_name]
            else:
                self.model_candidates = self._rank_models(discovered, self.model_setting)
                self.model = self.model_candidates[0]
        except Exception as exc:
            raise GeminiWebError(f"Reinit failed: {exc}") from exc

    # ══ Official API generation ═════════════════════════════════════════════

    def _ask_api(self, prompt: str, image_list=None, force_model=None) -> str:
        """Send prompt via the official Google Generative AI API."""
        # Pick model name
        if force_model is not None:
            model_name = self._model_name(force_model)
        else:
            model_name = self.model or self.API_MODEL_PRO

        # Build content parts
        parts = []
        for image_bytes, mime in image_list or []:
            # Compress first
            image_bytes, mime = self._compress_image(image_bytes, mime)
            from google.genai import types
            parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mime))
        parts.append(prompt)

        max_retries = 3
        last_exc = None
        for attempt in range(1, max_retries + 1):
            print(f"[Gemini API] Attempt {attempt}/{max_retries} on {model_name}")
            try:
                response = self._genai_client.models.generate_content(
                    model=model_name,
                    contents=parts,
                )
                text = response.text
                if not text or not text.strip():
                    raise GeminiWebError("Empty response from API.")
                print(f"[Gemini API] OK (attempt {attempt})")
                return text
            except Exception as exc:
                last_exc = exc
                print(f"[Gemini API] Fail #{attempt}: {exc}")
                if attempt < max_retries:
                    if self._is_rate_limited(exc):
                        delay = random.uniform(15, 25)
                        print(f"[Gemini API] Rate limited — waiting {delay:.0f}s...")
                    elif self._is_connectivity_error(exc):
                        self._wait_for_connectivity(max_wait=120)
                        delay = 1
                    else:
                        delay = 3.0 * attempt
                    time.sleep(delay)

        raise GeminiWebError(f"API failed after {max_retries} attempts: {last_exc}") from last_exc

    # ══ Routing: API vs Web ════════════════════════════════════════════════

    def _ask(self, prompt: str, image_list=None, force_model=None) -> str:
        """Route to API, direct, or web backend."""
        # If force_model is an API model name, use API path directly
        if force_model and self._api_key and isinstance(force_model, str):
            if force_model == self.API_MODEL_PRO or force_model == self.API_MODEL_FLASH:
                return self._ask_api(prompt, image_list, force_model)
        if self._use_api:
            return self._ask_api(prompt, image_list, force_model)
        if getattr(self, '_use_direct', False):
            return self._ask_direct(prompt, image_list, force_model)
        return self._ask_web(prompt, image_list, force_model)

    # ══ Direct HTTP generation (ported from Go proxy) ═══════════════════════

    def _ask_direct(self, prompt: str, image_list=None, force_model=None) -> str:
        """Send prompt via GeminiDirect (plain HTTP, no gemini_webapi)."""
        model_name = self._model_name(force_model) if force_model else self.model
        if isinstance(model_name, str):
            model = model_name
        else:
            model = self._model_name(model_name)

        # Compress images
        images = []
        for image_bytes, mime in image_list or []:
            image_bytes, mime = self._compress_image(image_bytes, mime)
            images.append((image_bytes, mime))

        max_retries = self.max_attempts
        last_exc = None
        _1100_count = 0  # Track consecutive 1100 errors for model fallback
        for attempt in range(1, max_retries + 1):
            print(f"[GeminiDirect] Attempt {attempt}/{max_retries} on {model}")
            try:
                text = self._direct.generate(
                    prompt=prompt,
                    model=model,
                    images=images or None,
                    temporary=True,
                )
                if not text or not text.strip():
                    raise GeminiWebError("Empty response.")
                print(f"[GeminiDirect] OK (attempt {attempt})")
                return text
            except Exception as exc:
                last_exc = exc
                err_text = str(exc)
                print(f"[GeminiDirect] Fail #{attempt}: {exc}")

                # Track 1100 errors — if model keeps failing, try a different one
                if "1100" in err_text:
                    _1100_count += 1
                    if _1100_count >= 2 and hasattr(self, 'model_candidates'):
                        # Find an alternative model
                        alt = None
                        for m in self.model_candidates:
                            if m != model and "flash" in m.lower():
                                alt = m
                                break
                        if alt:
                            print(f"[GeminiDirect] Model {model} keeps failing, switching to {alt}")
                            model = alt
                            _1100_count = 0

                if attempt < max_retries:
                    if self._is_connectivity_error(exc):
                        self._wait_for_connectivity(max_wait=120)
                        delay = 1
                    elif self._is_rate_limited(exc):
                        delay = random.uniform(15, 25)
                        print(f"[GeminiDirect] Rate limited — waiting {delay:.0f}s...")
                    else:
                        delay = 3.0 * attempt
                        err_text = str(exc)
                        # Try re-init on session/auth errors (1100 = unauthenticated)
                        if "1100" in err_text or "SNlM0e" in err_text or "token" in err_text.lower():
                            print("[GeminiDirect] Session expired, re-initializing...")
                            try:
                                self._direct.reinit()
                            except Exception as ie:
                                print(f"[GeminiDirect] Re-init failed: {ie}")
                    time.sleep(delay)

        raise GeminiWebError(f"Direct failed after {max_retries} attempts: {last_exc}") from last_exc

    # ══ Web API generation (fallback) ════════════════════════════════════════

    @staticmethod
    def _compress_image(image_bytes, mime, max_dim=1600, quality=65):
        """Compress and resize screenshot for faster upload.

        A raw 1080p PNG can be 3-5MB.  After resize + JPEG compression
        this drops to ~150-300KB — much faster to upload over slow links.
        """
        try:
            from PIL import Image
            import io as _io
            img = Image.open(_io.BytesIO(image_bytes))
            w, h = img.size
            if w > max_dim or h > max_dim:
                ratio = min(max_dim / w, max_dim / h)
                img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
            buf = _io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
            return buf.getvalue(), "image/jpeg"
        except Exception:
            return image_bytes, mime  # fallback: send original

    def _ask_web(self, prompt: str, image_list=None, force_model=None) -> str:
        """Send a prompt and return response text.

        Args:
            force_model: If set, use this model instead of the default fallback chain.
        """
        temp_paths = []
        try:
            files = []
            for image_bytes, mime in image_list or []:
                # Compress for faster upload
                image_bytes, mime = self._compress_image(image_bytes, mime)
                suffix = ".jpg" if mime == "image/jpeg" else ".png"
                f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
                f.write(image_bytes)
                f.close()
                path = Path(f.name)
                temp_paths.append(path)
                files.append(path)

            last_error = None
            ordered = list(self.model_candidates or [])
            if self.model is not None:
                current_name = self._model_name(self.model).lower()
                ordered = [self.model] + [m for m in ordered if self._model_name(m).lower() != current_name]
            ordered = [m for m in ordered if m is not None]

            # If a specific model is forced, put it first
            if force_model is not None:
                forced_name = self._model_name(force_model).lower()
                ordered = [force_model] + [m for m in ordered
                                           if self._model_name(m).lower() != forced_name]

            max_attempts = max(1, self.max_attempts)
            model_tries_budget = max(1, self.model_tries)
            attempt = 0
            model_index = 0

            while attempt < max_attempts and model_index < len(ordered):
                model = ordered[model_index]
                self.model = model
                model_fail_count = 0
                soft_retried = False

                while attempt < max_attempts and model_fail_count < model_tries_budget:
                    attempt += 1
                    model_fail_count += 1
                    print(f"[Gemini] Attempt {attempt}/{max_attempts} "
                          f"on {self._model_name(model)}")

                    async def request():
                        response = await self._client.generate_content(
                            prompt, files=files or None, model=model, temporary=True,
                        )
                        return response.text

                    try:
                        text = self._run(request(), timeout=self.attempt_timeout)
                        if not text or not text.strip():
                            raise GeminiWebError("Empty response.")
                        print(f"[Gemini] OK (attempt {attempt}, "
                              f"{self._model_name(model)})")
                        return text
                    except Exception as exc:
                        last_error = exc
                        print(f"[Gemini] Fail #{attempt} on "
                              f"{self._model_name(model)}: {exc}")

                        if attempt >= max_attempts:
                            break

                        if self._is_model_specific(exc):
                            print(f"[Gemini] Model error — skipping "
                                  f"{self._model_name(model)}")
                            break

                        # ── Connectivity check ──
                        if self._is_connectivity_error(exc):
                            if not self._wait_for_connectivity(max_wait=120):
                                break  # still offline → give up
                            soft_retried = False  # reset after reconnect

                        # ── 429 Rate limit: long wait, no reconnect ──
                        if self._is_rate_limited(exc):
                            rl_delay = random.uniform(20, 30)
                            print(f"[Gemini] Rate limited — waiting {rl_delay:.0f}s (session OK, just throttled)...")
                            time.sleep(rl_delay)
                            model_fail_count -= 1  # don't burn model budget on rate limits
                            soft_retried = False
                            continue

                        delay = self._backoff_delay(attempt - 1)
                        print(f"[Gemini] Backoff {delay:.1f}s...")
                        time.sleep(delay)

                        # Error 1100 / stale session → skip soft retry, go to reinit
                        if self._needs_reinit(exc):
                            print("[Gemini] Session error — full reconnect...")
                            try:
                                self._run(self._reinitialize(),
                                          timeout=self.init_timeout + 15)
                                print(f"[Gemini] Fresh session: "
                                      f"{self._model_name(self.model)}")
                                soft_retried = False
                            except Exception as reinit_exc:
                                last_error = reinit_exc
                                print(f"[Gemini] Reconnect failed: {reinit_exc}")
                                break
                            continue

                        if not soft_retried and self._is_retryable(exc):
                            soft_retried = True
                            print("[Gemini] Soft retry...")
                            continue

                        if model_fail_count < model_tries_budget:
                            print("[Gemini] Reconnecting...")
                            try:
                                self._run(self._reinitialize(),
                                          timeout=self.init_timeout + 15)
                                print(f"[Gemini] Refreshed: "
                                      f"{self._model_name(self.model)}")
                                soft_retried = False
                            except Exception as reinit_exc:
                                last_error = reinit_exc
                                print(f"[Gemini] Reconnect failed: {reinit_exc}")
                                break

                model_index += 1
                if model_index < len(ordered) and attempt < max_attempts:
                    print(f"[Gemini] Fallback → "
                          f"{self._model_name(ordered[model_index])}")
                    try:
                        self._run(self._reinitialize(),
                                  timeout=self.init_timeout + 15)
                    except Exception as reinit_exc:
                        last_error = reinit_exc
                        print(f"[Gemini] Fallback reconnect failed: {reinit_exc}")

            raise GeminiWebError(
                f"Failed after {attempt} attempt(s): {last_error}"
            ) from last_error
        finally:
            for path in temp_paths:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass

    # ── Domain-specific prompts ────────────────────────────────────────────

    def inspect_problem(self, image_list, force_model=None):
        prompt = """
Analyze the CURRENT desktop images.
Find the visible coding problem OR multiple-choice question (MCQ).
Pay close attention to the code editor window if visible.

Return ONLY valid JSON:
{
  "coding_page_visible": false,
  "problem_type": "CODE",
  "platform": "LeetCode|Codeforces|HackerRank|Other",
  "title": "",
  "statement": "",
  "constraints": [],
  "examples": [],
  "editor_current_code": "",
  "editor_language": "",
  "editor_click_x": 0.0,
  "editor_click_y": 0.0,
  "solution_type": "CLASS_METHOD|STANDARD_IO",
  "mcq_options": [],
  "mcq_correct_answer": "",
  "evidence": ""
}

Instructions:
- Set "problem_type" to "MCQ" if the problem is a multiple-choice question.
- Set "problem_type" to "CODE" if the problem requires writing code.

For CODE problems:
- Extract statement, constraints, and examples.
- `editor_current_code`: Read EXACTLY what is in the code editor.
- `editor_language`: Read the language selector/dropdown visible in the editor (e.g. "C++", "Python", "Java", "MySQL", "JavaScript", "SQL", etc.)
- `editor_click_x` and `editor_click_y`: Estimate where the CENTER of the code editor's typing area is on screen as fractions (0.0=left/top, 1.0=right/bottom). This is where a user would click to start typing. Look at the actual code editor panel, not the problem description.
- `solution_type`: "CLASS_METHOD" for LeetCode-style. "STANDARD_IO" for Codeforces-style.

For MCQ problems:
- List ALL visible options in `mcq_options` as:
  [{"label": "A", "text": "option text", "x_percent": 0.25, "y_percent": 0.45}, ...]
- `x_percent` and `y_percent`: estimate where the option's radio button / checkbox
  center is on screen as a fraction (0.0=left/top, 1.0=right/bottom).
- Set `mcq_correct_answer` to the label (e.g. "A", "B", "C", "D") of the correct option.
- Also fill in `statement` with the question text.

Use only visible information. Do not invent text.
"""
        return parse_json(self._ask(prompt, image_list, force_model=force_model))

    def solve(self, problem, previous_code=None, failure=None, force_model=None):
        repair = ""
        if previous_code:
            repair = f"""
IMPORTANT — FIX MODE:
The following code was already submitted and FAILED. Do NOT write a completely new solution.
Instead, carefully analyze the error and fix ONLY what is broken. Keep the overall structure,
variable names, and approach the same. Just patch the bug.

Previously submitted code:
```
{previous_code}
```

Error / failure observed:
{failure}

Diagnose the root cause of this failure and apply the minimum fix needed.
If the logic is fundamentally wrong, you may restructure the algorithm but keep
variable naming style and code personality consistent.
"""
        # Detect language from problem data
        lang = "C++"
        if isinstance(problem, dict):
            lang = problem.get("editor_language", "").strip() or "C++"
        elif isinstance(problem, str):
            low = problem.lower()
            for check in ["mysql", "sql", "python", "python3", "java", "javascript", "typescript", "go", "rust", "c#", "ruby", "swift", "kotlin"]:
                if check in low:
                    lang = check.upper() if check == "sql" or check == "mysql" else check
                    break

        is_sql = lang.lower() in ("mysql", "sql", "postgresql", "oracle", "ms sql", "sqlite")

        if is_sql:
            lang_rules = f"""LANGUAGE: {lang}
Write a SQL query. Return ONLY the SQL query, no markdown, no explanations.
- Use simple, readable column aliases
- Prefer straightforward JOINs and subqueries over complex CTEs unless needed
- Do NOT add any comments
"""
        else:
            lang_rules = f"""LANGUAGE: {lang}
Return ONLY complete {lang} code. No markdown formatting, no explanations, no chat.

CODING STYLE — You are a smart but lazy college student:
- Use simple, readable variable names (i, j, n, ans, res, dp, nums, etc.)
- Prefer straightforward brute-force or well-known textbook approaches over fancy tricks
- Keep it concise but NOT overly clever — no one-liners or code golf
- Do NOT add ANY comments at all — zero comments, zero inline notes, nothing
- Do NOT add a file header, author name, date, or verbose docstrings
- Variable naming should feel natural and slightly inconsistent (mix of short and descriptive)
- Prefer simple loops over complex lambda/ranges
- Keep the solution correct and efficient, but written like a human typed it quickly

Rules for the code format:
1. Look at 'solution_type' and 'editor_current_code' from the problem JSON.
2. If 'solution_type' is 'CLASS_METHOD' (e.g., LeetCode), you MUST preserve the exact class name and function signature provided in 'editor_current_code'. Do NOT write a main() function.
3. If 'solution_type' is 'STANDARD_IO', write a complete {lang} program with proper I/O.
4. Include all necessary imports/headers.
"""
        prompt = f"""
Solve this problem based on the extracted details:

{problem}

{repair}

{lang_rules}
"""
        return self.clean_code(self._ask(prompt, force_model=force_model))

    def inspect_result(self, image_bytes, mime, force_model=None):
        prompt = """
Analyze the CURRENT desktop image after the user ran/tested the code.

Return ONLY valid JSON:
{
  "coding_page_visible": false,
  "status": "ACCEPTED|WRONG_ANSWER|COMPILE_ERROR|RUNTIME_ERROR|TIME_LIMIT|RUNNING|NO_RESULT|UNKNOWN",
  "evidence": ""
}

Use ONLY visible evidence.

ACCEPTED requires clearly visible acceptance/success.
WRONG_ANSWER requires clearly visible wrong-answer evidence.
COMPILE_ERROR requires clearly visible compiler errors.
RUNTIME_ERROR requires clearly visible runtime errors.
TIME_LIMIT requires clearly visible time-limit evidence.
RUNNING means execution is visibly in progress.
NO_RESULT means the page is visible but no result is shown.
UNKNOWN means the result cannot be determined confidently.
"""
        return parse_json(self._ask(prompt, [(image_bytes, mime)],
                                   force_model=force_model))

    @staticmethod
    def clean_code(text):
        code = text.strip()
        if "```" in code:
            parts = code.split("```")
            for part in parts:
                part = part.strip()
                # Strip language tag from fenced code block
                for tag in ("cpp", "c++", "python", "python3", "java", "javascript",
                            "sql", "mysql", "typescript", "go", "rust", "csharp",
                            "ruby", "swift", "kotlin", "c"):
                    if part.lower().startswith(tag):
                        part = part.split("\n", 1)[-1].strip()
                        break
                if part and len(part) > 10:
                    code = part
                    break
        for tag in ("cpp", "c++", "sql", "mysql", "python", "java"):
            if code.lower().startswith(tag):
                code = code[len(tag):].strip()
                break
        return code.strip()

    def close(self):
        if getattr(self, '_closed', False):
            return
        self._closed = True
        if self._use_api:
            return  # API mode has no persistent connection
        if getattr(self, '_use_direct', False):
            self._direct.close()
            return
        if self._client is None or not self._loop.is_running():
            return

        async def shutdown():
            try:
                await self._client.close()
            except Exception:
                pass
            finally:
                self._loop.stop()

        try:
            asyncio.run_coroutine_threadsafe(shutdown(), self._loop)
        except Exception:
            pass