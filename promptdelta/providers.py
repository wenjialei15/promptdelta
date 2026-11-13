"""Recorded replay and a small non-streaming Chat Completions adapter."""
import ipaddress
import json
import math
import socket
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .core import ConfigError, strict_json


class ProviderError(RuntimeError):
    pass


class RecordedProvider:
    def __init__(self, responses):
        if not isinstance(responses, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in responses.items()):
            raise ConfigError("Recorded responses must map case IDs to text strings")
        self.responses = responses

    def complete(self, case_id, prompt):
        if case_id not in self.responses:
            raise ProviderError("No recorded response for case: " + case_id)
        return {"text": self.responses[case_id], "usage": None}

    def metadata(self):
        return {"type": "recorded", "model": "recorded-fixture"}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class ChatProvider:
    def __init__(self, base_url, model, api_key="", timeout=30):
        try:
            url = urlsplit(base_url)
            url.port  # Validate malformed port numbers before any request.
        except (ValueError, TypeError, AttributeError) as exc:
            raise ConfigError("Invalid API base URL") from exc
        if url.scheme not in ("https", "http") or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ConfigError("Base URL must be an HTTP(S) URL without credentials, query or fragment")
        if url.scheme == "http":
            try:
                local = ipaddress.ip_address(url.hostname).is_loopback
            except ValueError:
                local = url.hostname == "localhost"
            if not local:
                raise ConfigError("Use HTTPS for remote APIs; HTTP is supported only on localhost")
        if not isinstance(model, str) or not model.strip():
            raise ConfigError("API mode needs --model")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 300 or not math.isfinite(timeout):
            raise ConfigError("Timeout must be between 0 and 300 seconds")
        self.endpoint = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.opener = build_opener(NoRedirect())

    def metadata(self):
        # Endpoint, headers and keys are intentionally absent from exported files.
        return {"type": "api", "model": self.model}

    def complete(self, case_id, prompt):
        body = json.dumps({"model": self.model, "messages": [{"role": "user", "content": prompt}], "stream": False}, allow_nan=False).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        request = Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise ProviderError("API response exceeds 2 MiB")
            payload = strict_json(raw.decode("utf-8"))
            choice = payload["choices"][0]
            if choice.get("finish_reason") not in ("stop", None):
                raise ProviderError("API response was truncated, refused or requested a tool; text-only output required")
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise ProviderError("API did not return text content")
            usage = payload.get("usage")
            if isinstance(usage, dict):
                usage = {k: v for k, v in usage.items() if k in ("prompt_tokens", "completion_tokens", "total_tokens") and type(v) is int and v >= 0}
            else:
                usage = None
            return {"text": content, "usage": usage}
        except HTTPError as exc:
            # Never persist error bodies: gateways sometimes echo credentials.
            raise ProviderError("API HTTP {}; verify credentials, endpoint and model".format(exc.code)) from None
        except (URLError, TimeoutError, socket.timeout, OSError, HTTPException):
            raise ProviderError("API connection failed or timed out") from None
        except (ValueError, KeyError, IndexError, TypeError, AttributeError, RecursionError):
            raise ProviderError("Invalid Chat Completions response") from None
