#!/usr/bin/env python3
"""Self-check for native KB retrieval tuning and reranker forwarding."""
import argparse
import io
import json
from contextlib import redirect_stdout
from types import SimpleNamespace

import call


def main() -> None:
    assert call._unit_interval("0") == 0.0
    assert call._unit_interval("1") == 1.0
    try:
        call._unit_interval("1.1")
        raise AssertionError("out-of-range value must fail")
    except argparse.ArgumentTypeError:
        pass
    assert call._rerank_top_k("128") == 128
    try:
        call._rerank_top_k("2049")
        raise AssertionError("out-of-range rerank top-k must fail")
    except argparse.ArgumentTypeError:
        pass

    captured = {}
    original_kb_ids = call._kb_ids_for_action
    original_api_json = call._api_json

    def fake_api_json(method, path, tok, **kwargs):
        captured.update(method=method, path=path, body=kwargs["json_body"])
        return {
            "chunks": [{
                "chunk_id": "c1",
                "doc_id": "d1",
                "docnm_kwd": "demo.md",
                "content_with_weight": "demo",
                "similarity": 0.8,
                "vector_similarity": 0.7,
                "term_similarity": 0.9,
            }]
        }

    call._kb_ids_for_action = lambda args, tok: ["kb1"]
    call._api_json = fake_api_json
    try:
        args = SimpleNamespace(
            query="demo",
            exact=False,
            doc_ids="d1",
            top_k=3,
            similarity_threshold=0.2,
            vector_similarity_weight=0.6,
            rerank_id="demo-reranker",
            rerank_top_k=128,
            insecure=False,
            raw=True,
        )
        output = io.StringIO()
        with redirect_stdout(output):
            call.do_search_document_native(args, {})
    finally:
        call._kb_ids_for_action = original_kb_ids
        call._api_json = original_api_json

    assert captured["path"] == "/v1/chunk/retrieval_test"
    assert captured["body"]["similarity_threshold"] == 0.2
    assert captured["body"]["vector_similarity_weight"] == 0.6
    assert captured["body"]["rerank_id"] == "demo-reranker"
    assert captured["body"]["top_k"] == 128
    assert captured["body"]["size"] == 3
    result = json.loads(output.getvalue())
    settings = result["metadata"]["retrieval_settings"]
    assert settings["keyword_similarity_weight"] == 0.4
    assert settings["rerank_enabled"] is True
    assert settings["rerank_top_k"] == 128
    assert settings["similarity_component"] == "reranker"
    assert result["metadata"]["items"][0]["similarity"] == 0.8
    print("ok")


if __name__ == "__main__":
    main()
