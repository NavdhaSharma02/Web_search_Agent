import asyncio

from fastapi.testclient import TestClient

from app.main import create_app
from app.providers import ProviderError


class Unavailable:
    async def completion(self,*args,**kwargs):
        raise ProviderError("Model unavailable. Please retry.")


def test_api_lifecycle_validation_and_errors(settings):
    with TestClient(create_app(settings,Unavailable())) as client:
        assert client.get("/").status_code==200
        assert client.get("/static/app.js").status_code==200
        assert client.get("/api/health").json()["configured"]
        cid=client.post("/api/conversations").json()["id"]
        endpoint=f"/api/conversations/{cid}/messages"
        for value in ["", "   ", "x"*4001, None]:
            assert client.post(endpoint,json={"message":value}).status_code==422
        assert client.get("/api/conversations/not-a-uuid/messages").status_code==422
        assert client.get("/api/conversations/00000000-0000-0000-0000-000000000000/messages").status_code==404
        reply=client.post(endpoint,json={"message":"What is new?"})
        assert reply.status_code==200
        assert reply.json()["metadata"]["mode"]=="error"
        assert len(client.get(endpoint).json())==2
        assert client.get("/api/conversations").json()[0]["title"]=="What is new?"
        assert client.delete(f"/api/conversations/{cid}").status_code==204
        assert client.get(endpoint).status_code==404


def test_origin_guard_and_security_headers(settings):
    with TestClient(create_app(settings,Unavailable())) as client:
        assert client.post("/api/conversations",headers={"Origin":"https://attacker.test"}).status_code==403
        assert client.post("/api/conversations",headers={"Origin":"http://testserver"}).status_code==201
        response=client.get("/")
        assert "script-src 'self'" in response.headers["Content-Security-Policy"]
        assert response.headers["X-Content-Type-Options"]=="nosniff"


def test_concurrent_turn_and_delete_rejected(settings):
    class Blocking:
        async def completion(self,*args,**kwargs):
            started.set()
            await release.wait()
            return {"content":'{"answer":"Hello", "memory_ids":[]}'}

    async def scenario():
        import httpx
        app=create_app(settings,Blocking())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://testserver") as client:
                cid=(await client.post("/api/conversations")).json()["id"]
                endpoint=f"/api/conversations/{cid}/messages"
                task=asyncio.create_task(client.post(endpoint,json={"message":"First"}))
                await started.wait()
                assert (await client.post(endpoint,json={"message":"Second"})).status_code==409
                assert (await client.delete(f"/api/conversations/{cid}")).status_code==409
                release.set()
                assert (await task).status_code==200
                assert len((await client.get(endpoint)).json())==2

    started,release=asyncio.Event(),asyncio.Event()
    asyncio.run(scenario())
