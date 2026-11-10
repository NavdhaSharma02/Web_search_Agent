import asyncio
import json

import httpx
import pytest

from app.providers import ProviderError, Providers, safe_url


def run(coro):
    return asyncio.run(coro)


def test_search_contract_filtering_and_dedup(settings):
    async def scenario():
        def handler(request):
            assert str(request.url) == "https://api.tavily.com/search"
            assert request.headers["Authorization"] == "Bearer test-tavily"
            payload = json.loads(request.content)
            assert payload["max_results"] == 5
            assert payload["include_answer"] is False
            return httpx.Response(200, json={"results": [
                {"title":"Official", "url":"https://example.org/docs", "content":"Verified snippet", "score":.9},
                {"url":"https://example.org/docs", "content":"Duplicate", "score":.8},
                {"url":"javascript:alert(1)", "content":"Malicious", "score":1},
                {"url":"https://weak.org", "content":"Unrelated", "score":.1},
                {"url":"https://empty.org", "content":"", "score":.9}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            results = await Providers(settings, client).search("test query")
        assert len(results) == 1
        assert results[0]["content"] == "Verified snippet"
    run(scenario())


@pytest.mark.parametrize("kind", ["timeout", "429", "500", "invalid", "schema", "bad-score"])
def test_search_failure(settings, kind):
    async def scenario():
        def handler(request):
            if kind == "timeout":
                raise httpx.ReadTimeout("secret provider diagnostic", request=request)
            if kind in {"429", "500"}:
                return httpx.Response(int(kind), text="secret key should not leak")
            if kind == "invalid":
                return httpx.Response(200, text="invalid json")
            if kind == "bad-score":
                return httpx.Response(200, json={"results":[{"url":"https://example.org", "content":"x", "score":"bad"}]})
            return httpx.Response(200, json={"results":None})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ProviderError, match="Web search is unavailable"):
                await Providers(settings, client).search("query")
    run(scenario())


def test_completion_exposes_only_one_tool_and_disables_storage(settings):
    from app.agent import TOOLS
    async def scenario():
        def handler(request):
            payload=json.loads(request.content)
            assert payload["store"] is False
            assert payload["parallel_tool_calls"] is False
            assert [t["function"]["name"] for t in payload["tools"]] == ["web_search"]
            return httpx.Response(200,json={"choices":[{"finish_reason":"stop", "message":{"content":'{"answer":"Hello"}'}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert "Hello" in (await Providers(settings, client).completion([], TOOLS))["content"]
    run(scenario())


@pytest.mark.parametrize("value", ["javascript:alert(1)", "data:text/html,hello", "https://", "https://user:pass@example.org", None, "http://["])
def test_unsafe_urls(value):
    assert not safe_url(value)


def test_missing_keys(settings):
    from dataclasses import replace
    async def scenario():
        async with httpx.AsyncClient() as client:
            provider=Providers(replace(settings,openai_key="",tavily_key=""),client)
            with pytest.raises(ProviderError,match="OpenAI API key is missing"):
                await provider.completion([])
            with pytest.raises(ProviderError,match="Tavily API key is missing"):
                await provider.search("query")
    run(scenario())
