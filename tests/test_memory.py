from datetime import datetime, timedelta

from app.memory import Memory


def test_persistence_and_utc_timestamps(memory):
    cid = memory.create()["id"]
    message = memory.append(cid, "user", "My budget is $80.")
    reopened = Memory(memory.path)
    assert reopened.messages(cid)[0] == message
    assert datetime.fromisoformat(message["created_at"]).utcoffset() == timedelta(0)
    assert reopened.get(cid)["title"] == "My budget is $80."


def test_retrieval_finds_older_context_and_recent_turns(memory):
    cid = memory.create()["id"]
    budget = memory.append(cid, "user", "My telescope budget is $500.")
    for i in range(14):
        memory.append(cid, "user", f"Unrelated cooking discussion {i}")
    rows = memory.retrieve(cid, "What was my telescope budget?")
    assert budget["id"] in [r["id"] for r in rows]
    assert rows[-1]["content"] == "Unrelated cooking discussion 13"
    assert len(rows) <= 10


def test_isolation_and_cascade_delete(memory):
    a, b = memory.create()["id"], memory.create()["id"]
    memory.append(a, "user", "Private telescope budget")
    memory.append(b, "user", "Different account context")
    assert all("Private" not in m["content"] for m in memory.retrieve(b, "telescope"))
    assert memory.delete(a)
    assert memory.messages(a) == []
    assert len(memory.messages(b)) == 1


def test_retrieval_is_bounded_and_sql_input_is_data(memory):
    cid = memory.create()["id"]
    memory.append(cid, "user", "Robert'); DROP TABLE messages;--")
    assert memory.messages(cid)[0]["content"].startswith("Robert")
    assert memory.retrieve("' OR 1=1 --", "Robert") == []
