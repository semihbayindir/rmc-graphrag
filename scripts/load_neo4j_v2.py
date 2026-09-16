#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, os, re, sys, collections
import yaml
from neo4j import GraphDatabase

from zendesk_etl.config import settings  # noqa: F401  (.env yükler)

# --- artifact tipleme: LLM'siz, regex + sözlük ---
_JIRA = re.compile(r"^[A-Z]{2,}-\d+$")
_URL = re.compile(r"^https?://", re.I)
_DBOBJ = re.compile(r"^(dbo\.|#|[A-Z_]{3,}\.)|_TABLE$|^IX_", re.I)
_ERRCODE = re.compile(r"^[A-Z][A-Z0-9_]{5,}$")
_GENERIC_MIN_DEG = 50          # bu eşiği aşan artifact :Generic sayılır


def artifact_labels(name: str, api_names: set[str]) -> list[str]:
    n = name.strip()
    if _URL.match(n):
        return ["DocPage"]
    if _JIRA.match(n):
        return ["JiraIssue"]
    if n.lower() in api_names:
        return ["ApiMethod"]
    if _DBOBJ.search(n):
        return ["DbObject"]
    if _ERRCODE.match(n):
        return ["ErrorCode"]
    return ["ConfigParam"]


SCHEMA = [
    "CREATE CONSTRAINT t_id IF NOT EXISTS FOR (t:Ticket) REQUIRE t.id IS UNIQUE",
    "CREATE CONSTRAINT i_key IF NOT EXISTS FOR (i:Incident) REQUIRE (i.ticket_id, i.incident_id) IS UNIQUE",
    "CREATE CONSTRAINT m_name IF NOT EXISTS FOR (m:Module) REQUIRE m.name IS UNIQUE",
    "CREATE CONSTRAINT f_key IF NOT EXISTS FOR (f:Feature) REQUIRE (f.module, f.name) IS UNIQUE",
    "CREATE CONSTRAINT a_name IF NOT EXISTS FOR (a:Artifact) REQUIRE a.name IS UNIQUE",
    "CREATE CONSTRAINT te_name IF NOT EXISTS FOR (x:Team) REQUIRE x.name IS UNIQUE",
    "CREATE CONSTRAINT ch_name IF NOT EXISTS FOR (c:Channel) REQUIRE c.name IS UNIQUE",
    "CREATE CONSTRAINT ac_name IF NOT EXISTS FOR (a:Activity) REQUIRE a.name IS UNIQUE",
]
FULLTEXT = [
    ("incident_ft", "CREATE FULLTEXT INDEX incident_ft IF NOT EXISTS FOR (i:Incident) "
                    "ON EACH [i.symptom, i.findings, i.root_cause, i.resolution]"),
    ("artifact_ft", "CREATE FULLTEXT INDEX artifact_ft IF NOT EXISTS FOR (a:Artifact) "
                    "ON EACH [a.name]"),
]

INGEST = """
UNWIND $rows AS row
MERGE (t:Ticket {id: row.ticket_id})
  SET t.subject = row.subject, t.status = row.status, t.priority = row.priority,
      t.created_at = datetime(row.created_at), t.updated_at = datetime(row.updated_at),
      t.tags = row.tags, t.zendesk_group_id = row.group_id, t.comment_count = row.comment_count
FOREACH (tm IN row.owner_team |
  MERGE (g:Team {name: tm}) MERGE (t)-[:OWNED_BY]->(g))
FOREACH (inc IN row.incidents |
  MERGE (i:Incident {ticket_id: row.ticket_id, incident_id: inc.incident_id})
    SET i.symptom = inc.symptom, i.findings = inc.findings,
        i.root_cause = inc.root_cause, i.resolution = inc.resolution,
        i.outcome = inc.outcome, i.created_at = datetime(row.created_at),
        i.has_knowledge = inc.has_knowledge
  MERGE (t)-[:CONTAINS_INCIDENT]->(i)
  FOREACH (tm IN inc.teams |
    MERGE (g2:Team {name: tm}) MERGE (i)-[:SOURCED_FROM]->(g2))
  FOREACH (mo IN inc.module |
    MERGE (m:Module {name: mo}) SET m.suite = inc.suite
    FOREACH (fe IN inc.feature |
      MERGE (f:Feature {module: mo, name: fe}) MERGE (f)-[:PART_OF]->(m)
      MERGE (i)-[:AFFECTS]->(f)))
  FOREACH (c IN inc.channel | MERGE (ch:Channel {name: c}) MERGE (i)-[:VIA_CHANNEL]->(ch))
  FOREACH (a IN inc.activity | MERGE (ac:Activity {name: a}) MERGE (i)-[:HAS_ACTIVITY]->(ac))
  FOREACH (art IN inc.artifacts |
    MERGE (x:Artifact {name: art.name}) SET x.kind = art.kind
    MERGE (i)-[:MENTIONS]->(x))
)
"""


def confirm(uri: str, db: str) -> bool:
    print("\n" + "=" * 66)
    print("  DİKKAT — TÜM VERİ SİLİNECEK")
    print(f"  hedef : {uri}")
    print(f"  db    : {db}")
    print("=" * 66)
    return input("  Devam etmek için hedef URI'yi birebir yazın: ").strip() == uri


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--incidents", default="data/graph_ready_v3.jsonl")
    ap.add_argument("--modmap", default="data/module_map.jsonl")
    ap.add_argument("--facets", default="data/facets_llm.jsonl")
    ap.add_argument("--tickets", nargs="+", default=[
        "data/normalized/from_dump.jsonl", "data/normalized/from_api.jsonl",
        "data/normalized/tickets_method_d.jsonl"])
    ap.add_argument("--ontology", default="ontology/v1.yaml")
    ap.add_argument("--batch", type=int, default=300)
    ap.add_argument("--wipe", action="store_true", help="onay ister")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    for k in ("NEO4J_V2_URI", "NEO4J_V2_USERNAME", "NEO4J_V2_PASSWORD", "NEO4J_V2_DATABASE"):
        if not os.environ.get(k):
            raise SystemExit(f"Eksik ortam değişkeni: {k}")
    uri = os.environ["NEO4J_V2_URI"]; db = os.environ["NEO4J_V2_DATABASE"]

    ont = yaml.safe_load(open(args.ontology, encoding="utf-8"))
    suite = {m["name"]: m["suite"] for m in ont["modules"]}
    api_names = set()
    try:
        a = json.load(open("data/api_reference.json", encoding="utf-8"))
        api_names = {str(x).lower() for x in (a if isinstance(a, list) else a.keys())}
    except Exception:
        pass

    modmap, facets = {}, {}
    for l in open(args.modmap, encoding="utf-8"):
        r = json.loads(l); modmap[(r["ticket_id"], r["incident_id"])] = r["module"]
    for l in open(args.facets, encoding="utf-8"):
        r = json.loads(l); facets[(r["ticket_id"], r["incident_id"])] = r
    meta = {}
    for p in args.tickets:
        for l in open(p, encoding="utf-8"):
            r = json.loads(l); meta.setdefault(r["id"], r)
    print(f"[girdi] {len(meta):,} bilet · {len(modmap):,} modül eşlemesi · {len(facets):,} facet")

    # artifact derecesi -> :Generic bayrağı
    deg = collections.Counter()
    for l in open(args.incidents, encoding="utf-8"):
        for i in json.loads(l)["incidents"]:
            for a in dict.fromkeys(x.strip() for x in i["technical_artifacts"] if (x or "").strip()):
                deg[a] += 1
    generic = {a for a, d in deg.items() if d >= _GENERIC_MIN_DEG}
    print(f"[artifact] {len(deg):,} tekil · {len(generic)} tanesi :Generic (derece >= {_GENERIC_MIN_DEG})")

    rows, viol = [], 0
    for l in open(args.incidents, encoding="utf-8"):
        r = json.loads(l); t = meta.get(r["ticket_id"])
        if not t:
            continue
        incs = []
        for i in r["incidents"]:
            k = (r["ticket_id"], i["incident_id"])
            none = i["outcome"] == "none"
            # outcome=none ise metin alanları boşaltılır.
            if none and ((i["findings"] or "").strip() or (i["resolution"] or "").strip()):
                viol += 1
            mod = None if none else modmap.get(k)
            f = facets.get(k, {})
            arts = []
            for a in dict.fromkeys(x.strip() for x in i["technical_artifacts"] if (x or "").strip()):
                a = a[:4000]
                lbl = artifact_labels(a, api_names)[0]
                arts.append({"name": a, "kind": "Generic" if a in generic else lbl})
            incs.append({
                "incident_id": i["incident_id"], "symptom": i["symptom"],
                "findings": "" if none else (i["findings"] or ""),
                "root_cause": "" if none else (i["root_cause"] or ""),
                "resolution": "" if none else (i["resolution"] or ""),
                "outcome": i["outcome"], "has_knowledge": not none,
                "module": [mod] if mod else [],
                "suite": suite.get(mod, ""),
                "feature": [i["affected_component"]["sub_component"]] if mod and i["affected_component"]["sub_component"] else [],
                "teams": r.get("source_teams", []),
                "channel": f.get("channel", []), "activity": f.get("activity", []),
                "artifacts": arts,
            })
        rows.append({
            "ticket_id": r["ticket_id"], "subject": t.get("subject") or "",
            "status": t.get("status"), "priority": t.get("priority"),
            "created_at": t.get("created_at"), "updated_at": t.get("updated_at"),
            "tags": t.get("tags", []), "group_id": t.get("group_id"),
            "comment_count": t.get("comment_count", 0),
            "owner_team": r.get("source_teams", [])[:1],
            "incidents": incs,
        })
    if args.limit:
        rows = rows[: args.limit]
    print(f"[hazır] {len(rows):,} bilet · {sum(len(x['incidents']) for x in rows):,} incident "
          f"· {viol} kural ihlali temizlendi")

    drv = GraphDatabase.driver(uri, auth=(os.environ["NEO4J_V2_USERNAME"], os.environ["NEO4J_V2_PASSWORD"]))
    drv.verify_connectivity()
    print(f"[bağlantı] {uri} (db={db}) OK")
    with drv.session(database=db) as s:
        if args.wipe:
            if not confirm(uri, db):
                print("  iptal edildi."); return 1
            while True:
                d = s.run("MATCH (n) WITH n LIMIT 10000 DETACH DELETE n RETURN count(n) AS c").single()["c"]
                if d == 0:
                    break
            print("  [wipe] tamam")
        for c in SCHEMA:
            s.run(c)
        for _, q in FULLTEXT:
            s.run(q)
        print(f"[şema] {len(SCHEMA)} constraint + {len(FULLTEXT)} full-text index")
        for n in range(0, len(rows), args.batch):
            s.run(INGEST, rows=rows[n:n + args.batch])
            print(f"  {min(n+args.batch, len(rows)):,}/{len(rows):,}", flush=True)
        print("\n=== DOĞRULAMA ===")
        for r in s.run("MATCH (n) UNWIND labels(n) AS l RETURN l AS label, count(*) AS c ORDER BY c DESC"):
            print(f"  {r['label']:<14}{r['c']:>8,}")
        print("  --")
        for r in s.run("MATCH ()-[x]->() RETURN type(x) AS t, count(*) AS c ORDER BY c DESC"):
            print(f"  {r['t']:<20}{r['c']:>8,}")
    drv.close()
    print("\n[done]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
