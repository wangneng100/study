"""Vocabulary notebook: look up unknown words, store them, review on the Ebbinghaus schedule."""
from app.core.registry import Tool

from . import store
from .routes import bp

tool = Tool(
    slug="vocab",
    name="单词本",
    description="输入不会的单词，自动翻译并记下，按艾宾浩斯间隔安排 8 次复习。",
    blueprint=bp,
    schema=store.SCHEMA,
    status=store.status,
    order=10,
)
