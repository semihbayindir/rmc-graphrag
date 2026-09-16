#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

from neo4j import GraphDatabase

from zendesk_etl import openai_llm as llm

SRC = "data/api_docs_v2.jsonl"
EMBED_CHARS = 4000   # embedding girdisi: başlık + özet + metnin başı
EMBED_BATCH = 64

SCHEMA = [
    "CREATE CONSTRAINT apidoc_id IF NOT EXISTS FOR (d:ApiDoc) REQUIRE d.id IS UNIQUE",
    "CREATE FULLTEXT INDEX apidoc_ft IF NOT EXISTS FOR (d:ApiDoc) "
    "ON EACH [d.method, d.service, d.summary, d.text]",
]

UPSERT = """
UNWIND $rows AS row
MERGE (d:ApiDoc {id: row.id})
WITH d, row, (d.text_hash = row.text_hash AND d.embed_model = row.embed_model) AS unchanged
SET d.protocol = row.protocol, d.service = row.service, d.method = row.method,
    d.summary = row.summary, d.url = row.url, d.text = row.text, d.chars = row.chars,
    d.page_id = row.page_id, d.text_hash = row.text_hash, d.embed_model = row.embed_model
FOREACH (_ IN CASE WHEN unchanged THEN [] ELSE [1] END | REMOVE d.embedding)
"""


def embed_input(d: dict) -> str:
    head = " ".join(x for x in (d["protocol"], d["service"], d["method"] or "") if x)
    return f"{head}\n{d['summary']}\n{d['text']}"[:EMBED_CHARS]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    docs = [json.loads(line) for line in open(args.src, encoding="utf-8") if line.strip()]
    model, dim = llm.embed_model(), llm.embed_dim()
    for d in docs:
        d["text_hash"] = hashlib.sha1(embed_input(d).encode("utf-8")).hexdigest()
        d["embed_model"] = f"{model}:{dim}"
    ids = [d["id"] for d in docs]

    drv = GraphDatabase.driver(os.environ["NEO4J_V2_URI"],
                               auth=(os.environ["NEO4J_V2_USERNAME"], os.environ["NEO4J_V2_PASSWORD"]))
    db = os.environ["NEO4J_V2_DATABASE"]
    print(f"[giriş] {len(docs)} bölüm ({sum(1 for d in docs if d['method'])} metot) | "
          f"{os.environ['NEO4J_V2_URI']} | embedding {model}:{dim}")

    with drv.session(database=db) as s:
        existing = {r["id"]: (r["h"], r["m"], r["e"]) for r in s.run(
            "MATCH (d:ApiDoc) RETURN d.id AS id, d.text_hash AS h, d.embed_model AS m, "
            "d.embedding IS NOT NULL AS e")}
        idx = s.run("SHOW INDEXES YIELD name, options WHERE name = 'apidoc_vec' RETURN options").single()
        old_dim = idx and idx["options"]["indexConfig"].get("vector.dimensions")
        artifacts = {}
        for r in s.run("MATCH (a:Artifact) RETURN a.name AS n"):
            artifacts.setdefault(r["n"].lower(), []).append(r["n"])

    to_embed = [d for d in docs if existing.get(d["id"]) != (d["text_hash"], d["embed_model"], True)]
    stale = sorted(set(existing) - set(ids))
    links = [{"id": d["id"], "name": n} for d in docs if d["method"]
             for n in artifacts.get(d["method"].lower(), [])]
    est_tokens = sum(len(embed_input(d)) for d in to_embed) / 3.2
    print(f"[plan] yeni {sum(1 for i in ids if i not in existing)} | embedding gereken {len(to_embed)} "
          f"(~{est_tokens / 1e3:.0f}k token, ~${est_tokens * 0.13 / 1e6:.3f}) | silinecek eski {len(stale)} | "
          f"DESCRIBES bağı {len(links)} ({len({l['id'] for l in links})} bölüm)")
    if old_dim and old_dim != dim:
        print(f"[uyarı] apidoc_vec boyutu {old_dim}, istenen {dim}: index yeniden kurulacak")
    if args.dry_run:
        drv.close()
        return 0

    t0, tokens = time.time(), 0
    with drv.session(database=db) as s:
        for q in SCHEMA:
            s.run(q)
        if old_dim and old_dim != dim:
            s.run("DROP INDEX apidoc_vec IF EXISTS")
        s.run(UPSERT, rows=docs)
        if stale:
            s.run("MATCH (d:ApiDoc) WHERE d.id IN $ids DETACH DELETE d", ids=stale)

        for b in range(0, len(to_embed), EMBED_BATCH):
            chunk = to_embed[b:b + EMBED_BATCH]
            vecs, used = llm.embed([embed_input(d) for d in chunk])
            tokens += used
            s.run("""UNWIND $rows AS row MATCH (d:ApiDoc {id: row.id})
                     CALL db.create.setNodeVectorProperty(d, 'embedding', row.v)""",
                  rows=[{"id": d["id"], "v": v} for d, v in zip(chunk, vecs)])
            print(f"  embedding {min(b + EMBED_BATCH, len(to_embed))}/{len(to_embed)}", flush=True)

        s.run(f"""CREATE VECTOR INDEX apidoc_vec IF NOT EXISTS FOR (d:ApiDoc) ON (d.embedding)
                  OPTIONS {{indexConfig: {{`vector.dimensions`: {dim},
                                          `vector.similarity_function`: 'cosine'}}}}""")
        s.run("MATCH (:ApiDoc)-[r:DESCRIBES]->() DELETE r")
        s.run("""UNWIND $rows AS row
                 MATCH (d:ApiDoc {id: row.id}) MATCH (a:Artifact {name: row.name})
                 MERGE (d)-[:DESCRIBES]->(a)""", rows=links)
        s.run("CALL db.awaitIndexes(300)")
        r = s.run("""MATCH (d:ApiDoc)
                     RETURN count(d) AS n, sum(CASE WHEN d.embedding IS NULL THEN 0 ELSE 1 END) AS e,
                            size([(x:ApiDoc)-[:DESCRIBES]->() | x]) AS l""").single()
    drv.close()
    print(f"[done] {r['n']} ApiDoc | embedding'li {r['e']} | DESCRIBES {r['l']} | "
          f"{tokens:,} token (~${tokens * 0.13 / 1e6:.4f}) | {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
