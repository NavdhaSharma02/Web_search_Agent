import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.agent import Agent
from app.memory import now
from app.providers import ProviderError


def text(answer, ids=None):
    return {"role":"assistant", "content":json.dumps({"answer":answer,"memory_ids":ids or []})}


def tool(query="SQLite architecture"):
    return {"role":"assistant", "content":None,"tool_calls":[{"id":"call_1","type":"function",
        "function":{"name":"web_search","arguments":json.dumps({"query":query})}}]}


RESULT = {"title":"SQLite", "url":"https://sqlite.org/about.html", "content":"SQLite is an in-process library.", "published_date":None}


class FakeProviders:
    def __init__(self, responses, results=None, error=None):
        self.responses=list(responses)
        self.results=[RESULT] if results is None else results
        self.error=error
        self.calls=[]
        self.searches=[]

    async def completion(self,messages,tools=None):
        self.calls.append((list(messages),tools))
        response=self.responses.pop(0)
        if isinstance(response,Exception):
            raise response
        return response

    async def search(self,query):
        self.searches.append(query)
        if self.error:
            raise self.error
        return self.results


def execute(memory, provider, cid, query):
    return asyncio.run(Agent(memory,provider).answer(cid,query))


def test_search_grounded_answer_and_persistent_evidence(memory):
    cid=memory.create()["id"]
    provider=FakeProviders([tool(),text("SQLite runs in-process [S1].")])
    reply=execute(memory,provider,cid,"How does SQLite run?")
    assert reply["metadata"]["mode"]=="search"
    assert reply["metadata"]["sources"][0]["url"]==RESULT["url"]
    assert reply["metadata"]["sources"][0]["retrieved_at"]
    assert len(provider.calls)==2 and provider.calls[1][1] is None
    assert len(memory.messages(cid))==2


def test_follow_up_receives_recent_context_and_resolves_search(memory):
    cid=memory.create()["id"]
    first=memory.append(cid,"user","Tell me about SQLite for my Python app.")
    memory.append(cid,"assistant","What would you like to know?")
    provider=FakeProviders([tool("SQLite Python app concurrency limitations"),text("It is in-process [S1].",[first["id"]])])
    reply=execute(memory,provider,cid,"What about its limitations?")
    prompt=json.loads(provider.calls[0][0][1]["content"])
    assert prompt["memory"][0]["text"]==first["content"]
    assert provider.searches==["SQLite Python app concurrency limitations"]
    assert reply["metadata"]["memories"][0]["id"]==first["id"]


def test_remembering_when_without_search(memory):
    cid=memory.create()["id"]
    past=memory.append(cid,"user","My budget is $80.")
    provider=FakeProviders([text(f'You told me your budget was $80 at {past["created_at"]}.',[past["id"]])])
    reply=execute(memory,provider,cid,"What was my budget and when did I say it?")
    assert not provider.searches
    assert len(provider.calls)==1
    assert reply["metadata"]["memories"][0]["created_at"]==past["created_at"]


def test_ambiguity_can_be_clarified_without_search(memory):
    cid=memory.create()["id"]
    provider=FakeProviders([text("Which Mercury do you mean: the planet or the element?")])
    reply=execute(memory,provider,cid,"Tell me about Mercury.")
    assert reply["content"].endswith("?") and not provider.searches


def test_reuses_fresh_evidence_without_search(memory):
    cid=memory.create()["id"]
    memory.append(cid,"assistant","SQLite is a library [S1].",{"sources":[dict(RESULT,id="S1",retrieved_at=now())]})
    provider=FakeProviders([text("The evidence says it is in-process [S1].")])
    reply=execute(memory,provider,cid,"Repeat that detail.")
    assert reply["metadata"]["mode"]=="cached_search"
    assert not provider.searches and len(provider.calls)==1


def test_stale_evidence_excluded(memory):
    cid=memory.create()["id"]
    old=(datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat()
    memory.append(cid,"assistant","Old result",{"sources":[dict(RESULT,id="S1",retrieved_at=old)]})
    provider=FakeProviders([tool(),text("It is a library [S1].")])
    execute(memory,provider,cid,"What is it today?")
    assert json.loads(provider.calls[0][0][1]["content"])["WEB_EVIDENCE"]==[]
    assert len(provider.searches)==1


@pytest.mark.parametrize("responses,results,error,expected",[
    ([tool()],[],None,"no usable evidence"),
    ([tool()],[RESULT],ProviderError("Web search is unavailable"),"unavailable"),
    ([ProviderError("Model unavailable")],None,None,"Model unavailable"),
    ([tool(),text("Unsupported [S99].")],None,None,"unverifiable citation"),
    ([{"content":"not JSON"}],None,None,"invalid response"),
    ([tool(),text("I know an unsupported fact.")],None,None,"do not establish"),
    ([tool(),tool()],None,None,"exceeded the search budget"),
])
def test_failure_cases_persist_without_fabrication(memory,responses,results,error,expected):
    cid=memory.create()["id"]
    provider=FakeProviders(responses,results,error)
    reply=execute(memory,provider,cid,"Question")
    assert expected in reply["content"]
    assert not reply["metadata"]["sources"]
    assert memory.messages(cid)[0]["content"]=="Question"
    assert len(provider.searches)<=1 and len(provider.calls)<=2


def test_other_conversation_never_enters_prompt(memory):
    a,b=memory.create()["id"],memory.create()["id"]
    memory.append(a,"user","SECRET budget $80")
    provider=FakeProviders([text("You have not told me a budget here.",[1])])
    reply=execute(memory,provider,b,"What was my budget?")
    assert "SECRET" not in json.dumps(provider.calls)
    assert reply["metadata"]["memories"]==[]


def test_unrecognized_tools_rejected(memory):
    cid=memory.create()["id"]
    call=tool();call["tool_calls"][0]["function"]["name"]="read_file"
    provider=FakeProviders([call])
    reply=execute(memory,provider,cid,"Read file")
    assert reply["metadata"]["mode"]=="error"
    assert not provider.searches


@pytest.mark.parametrize("calls", [[None], "bad", [{"function":None}],
    [{"function":{"name":"web_search","arguments":"{}"}}]])
def test_malformed_tool_calls_fail_gracefully(memory,calls):
    cid=memory.create()["id"]
    provider=FakeProviders([{"tool_calls":calls}])
    reply=execute(memory,provider,cid,"Question")
    assert reply["metadata"]["mode"]=="error"
    assert not provider.searches


def test_request_timeout_keeps_query_and_gives_retry_message(memory):
    cid=memory.create()["id"]
    provider=FakeProviders([TimeoutError()])
    reply=execute(memory,provider,cid,"A question")
    assert "timed out" in reply["content"]
    assert len(memory.messages(cid))==2


def test_search_query_length_and_extra_arguments_validated(memory):
    cid=memory.create()["id"]
    for arguments in [{"query":"x"*501},{"query":"valid","other":"extra"}, {"query":5}]:
        response=tool()
        response["tool_calls"][0]["function"]["arguments"]=json.dumps(arguments)
        provider=FakeProviders([response])
        reply=execute(memory,provider,cid,"Question")
        assert reply["metadata"]["mode"]=="error"
        assert not provider.searches
