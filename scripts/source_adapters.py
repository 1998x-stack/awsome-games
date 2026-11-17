#!/usr/bin/env python3
"""Schema-specific, metadata-only adapters for four approved upstream JSON indexes.

Adapters parse public metadata, not model provenance or software to execute.
Adding an upstream requires an explicit reviewed schema and test cases.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit


@dataclass(frozen=True)
class SourceAdapter:
    name: str
    url: str
    post_field: str
    id_field: str
    title_field: str
    category_field: str
    collection_key: str = ""
    play_field: str = ""
    repo_field: str = ""
    author_field: str = "author"

    def entries(self, payload: object) -> list:
        if self.collection_key:
            if not isinstance(payload, dict):
                raise ValueError("Expected JSON object for " + self.name)
            payload = payload.get(self.collection_key)
        if not isinstance(payload, list) or not payload:
            raise ValueError("Empty/invalid upstream JSON: " + self.name)
        if any(not isinstance(x, dict) for x in payload):
            raise ValueError("Upstream contains non-object record: " + self.name)
        return payload

    def normalize(self, raw: dict, index: int, source_url: str,
                  post_id_resolver: Callable[[str | None], str | None]) -> dict:
        if not isinstance(raw, dict):
            raise ValueError("Source record must be an object")
        author = raw.get(self.author_field) or ""
        if self.name == "VibeGamer":
            author = raw.get("maker_handle") or raw.get("maker") or ""
        if isinstance(author, dict):
            author = author.get("handle") or author.get("name") or ""
        if self.name == "VibeGamer":
            tags = raw.get("tags") or []
            if not isinstance(tags, list):
                raise ValueError("VibeGamer tags must be an array")
            category = " / ".join(str(tag) for tag in tags)
        else:
            category = raw.get(self.category_field) or ""
        id_value = raw.get(self.id_field)
        if id_value is None:
            id_value = index
        title = raw.get(self.title_field) or ""
        post_url = raw.get(self.post_field)
        source = source_url.replace("raw.githubusercontent.com/", "github.com/").replace("/main/", "/blob/main/", 1)
        return {"source":self.name,"source_id":str(id_value),
                "post_id":post_id_resolver(post_url),"post_url":post_url,
                "title":title,"title_zh":raw.get("title_zh") or raw.get("titleZh") or "",
                "category":category,"author":str(author or ""),
                "play_url":raw.get(self.play_field) if self.play_field else None,
                "repo_url":raw.get(self.repo_field) if self.repo_field else None,
                "source_url":source}


ADAPTERS = (
    SourceAdapter("FableList",
        "https://raw.githubusercontent.com/fengyiqicoder/awesome-fable-5.2/main/data/works.json",
        "post","id","title","section","", "url"),
    SourceAdapter("VibeGamer",
        "https://raw.githubusercontent.com/ummydev/awesome-claude-fable-games/main/data/games.json",
        "post_url","slug","name","tags","", "play_url","open_source_url"),
    SourceAdapter("DramaSo",
        "https://raw.githubusercontent.com/mofa-si/awesome-fable-5-2-videos/main/data/collection.json",
        "sourceUrl","id","title","category","entries"),
    SourceAdapter("Sandbase",
        "https://raw.githubusercontent.com/sandbase-lab/awesome-fable-5-2/main/data/videos.json",
        "postUrl","id","title","category"),
)
BY_NAME={x.name:x for x in ADAPTERS}
if len(BY_NAME)!=len(ADAPTERS):
    raise RuntimeError("Duplicate metadata adapter name")
for adapter in ADAPTERS:
    parsed=urlsplit(adapter.url)
    if parsed.scheme!="https" or parsed.hostname!="raw.githubusercontent.com" or parsed.username or parsed.password:
        raise RuntimeError("Unsafe metadata adapter URL: " + adapter.name)
