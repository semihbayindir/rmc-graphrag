#!/usr/bin/env python3
from __future__ import annotations

import argparse, os, sys, time
from neo4j import GraphDatabase

from zendesk_etl import openai_llm as llm


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=256)  # istek başına 2048 girdi / 300k token sınırının çok altında
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reset", action="store_true",
                    help="mevcut embedding'leri ve incident_vec index'ini silip baştan göm")
    args = ap.parse_args()

    model, dim = llm.embed_model(), llm.embed_dim()
    drv = GraphDatabase.driver(os.environ["NEO4J_V2_URI"],
                               auth=(os.environ["NEO4J_V2_USERNAME"], os.environ["NEO4J_V2_PASSWORD"]))
    db = os.environ["NEO4J_V2_DATABASE"]

    with drv.session(database=db) as s:
        if args.reset:
            s.run("DROP INDEX incident_vec IF EXISTS")
            n = s.run("MATCH (i:Incident) WHERE i.embedding IS NOT NULL "
                      "REMOVE i.embedding RETURN count(i) AS c").single()["c"]
            print(f"[reset] incident_vec silindi, {n:,} eski embedding kaldırıldı")
        else:
            idx = s.run("SHOW INDEXES YIELD name, options WHERE name = 'incident_vec' "
                        "RETURN options").single()
            old = idx and idx["options"]["indexConfig"].get("vector.dimensions")
            if old and old != dim:
                raise SystemExit(f"incident_vec boyutu {old}, istenen {dim}. Karışık vektör "
                                 f"üretmemek için --reset ile çalıştırın.")
        todo = [dict(r) for r in s.run("""
            MATCH (i:Incident) WHERE i.has_knowledge AND i.embedding IS NULL
            RETURN i.ticket_id AS t, i.incident_id AS n,
                   left(coalesce(i.symptom,'') + ' ' + coalesce(i.findings,'') + ' ' +
                        coalesce(i.resolution,''), 2000) AS txt
            ORDER BY t, n""")]
    if args.limit:
        todo = todo[: args.limit]
    print(f"[giriş] {len(todo):,} incident (has_knowledge, embedding'i yok) | model={model} dim={dim}")
    if not todo:
        print("[done] yapılacak yok"); return 0

    t0, done, tokens = time.time(), 0, 0
    with drv.session(database=db) as s:
        for b in range(0, len(todo), args.batch):
            chunk = todo[b:b + args.batch]
            for attempt in range(5):
                try:
                    vecs, used = llm.embed([c["txt"] or " " for c in chunk])
                    break
                except Exception:  # noqa: BLE001 — SDK geçici hataları zaten yeniden denedi
                    if attempt == 4:
                        raise
                    time.sleep(2 ** attempt)
            tokens += used
            rows = [{"t": c["t"], "n": c["n"], "v": v} for c, v in zip(chunk, vecs)]
            s.run("""UNWIND $rows AS row
                     MATCH (i:Incident {ticket_id: row.t, incident_id: row.n})
                     CALL db.create.setNodeVectorProperty(i, 'embedding', row.v)""", rows=rows)
            done += len(rows)
            el = time.time() - t0
            print(f"  {done:,}/{len(todo):,}  ({done/el:.0f}/s, {tokens:,} token)", flush=True)

    with drv.session(database=db) as s:
        s.run(f"""CREATE VECTOR INDEX incident_vec IF NOT EXISTS
                  FOR (i:Incident) ON (i.embedding)
                  OPTIONS {{indexConfig: {{`vector.dimensions`: {dim},
                                          `vector.similarity_function`: 'cosine'}}}}""")
        print(f"[index] incident_vec kuruldu (boyut={dim}, cosine)")
        n = s.run("MATCH (i:Incident) WHERE i.embedding IS NOT NULL RETURN count(i) AS c").single()["c"]
        print(f"[done] {n:,} incident'te embedding var | {tokens:,} token | {time.time()-t0:.0f}s")
    drv.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
