import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    openai_key: str = ""
    tavily_key: str = ""
    model: str = "gpt-4.1-mini"
    database: str = "data/recallsearch.sqlite3"

    @classmethod
    def load(cls):
        load_dotenv()
        return cls(os.getenv("OPENAI_API_KEY", ""), os.getenv("TAVILY_API_KEY", ""),
                   os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                   os.getenv("DATABASE_PATH", "data/recallsearch.sqlite3"))
