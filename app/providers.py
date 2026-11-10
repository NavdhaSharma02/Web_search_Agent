import json
from urllib.parse import urlsplit

import httpx


class ProviderError(Exception):
    pass


def safe_url(value):
    try:
        if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 for c in value):
            return False
        url = urlsplit(value)
        return url.scheme in {"https", "http"} and bool(url.hostname) and url.username is None
    except (ValueError, TypeError):
        return False


class Providers:
    def __init__(self, settings, client):
        self.settings, self.client = settings, client

    async def completion(self, messages, tools=None):
        if not self.settings.openai_key:
            raise ProviderError("OpenAI API key is missing. Configure .env and restart the server.")
        payload = dict(model=self.settings.model, messages=messages, max_completion_tokens=1400,
                       response_format={"type": "json_object"}, store=False)
        if tools:
            payload.update(tools=tools, tool_choice="auto", parallel_tool_calls=False)
        try:
            response = await self.client.post("https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.openai_key}"}, json=payload, timeout=25)
            response.raise_for_status()
            data = response.json()
            if data["choices"][0].get("finish_reason") not in {"stop", "tool_calls"}:
                raise ValueError("incomplete completion")
            message = data["choices"][0]["message"]
            if not isinstance(message, dict):
                raise ValueError("invalid message")
            return message
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("The language model is unavailable or returned an invalid response. Please retry.") from exc

    async def search(self, query):
        if not self.settings.tavily_key:
            raise ProviderError("Tavily API key is missing. Configure .env and restart the server.")
        try:
            response = await self.client.post("https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {self.settings.tavily_key}"},
                json={"query": query, "search_depth": "basic", "max_results": 5,
                      "include_answer": False, "include_raw_content": False}, timeout=12)
            response.raise_for_status()
            raw = response.json()["results"]
            if not isinstance(raw, list):
                raise ValueError("invalid results")
            results, seen = [], set()
            for item in raw[:10]:
                url, content = item.get("url", ""), item.get("content", "")
                if not safe_url(url) or url in seen or not isinstance(content, str) or not content.strip():
                    continue
                if float(item.get("score", 0)) < 0.35:
                    continue
                seen.add(url)
                results.append(dict(title=str(item.get("title", url))[:200], url=url,
                                    content=content[:1800], published_date=item.get("published_date")))
            return results[:5]
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ProviderError("Web search is unavailable. Please retry in a moment.") from exc


def decode(text):
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (ValueError, TypeError) as exc:
        raise ProviderError("The model returned an invalid response. Please retry.") from exc
