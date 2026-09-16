from __future__ import annotations

import os
import re
from typing import Optional

import logging

from neo4j import GraphDatabase

# queryNodes kullanım dışı uyarısı susturuluyor; SEARCH desteklenince VECTOR sorgusu güncellenmeli.
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

_LUCENE = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')

RETRIEVE = """
CALL db.index.fulltext.queryNodes('incident_ft', $query) YIELD node AS i, score
WHERE i.has_knowledge
WITH i, score LIMIT 300
OPTIONAL MATCH (i)-[:AFFECTS]->(f:Feature)-[:PART_OF]->(m:Module)
OPTIONAL MATCH (i)-[:VIA_CHANNEL]->(ch:Channel)
OPTIONAL MATCH (i)-[:HAS_ACTIVITY]->(ac:Activity)
OPTIONAL MATCH (i)-[:SOURCED_FROM]->(tm:Team)
WITH i, score, m, f,
     collect(DISTINCT ch.name) AS kanallar,
     collect(DISTINCT ac.name) AS faaliyetler,
     collect(DISTINCT tm.name) AS ekipler
WITH i, m, f, kanallar, faaliyetler, ekipler,
     score
     * (CASE WHEN $module   IS NULL OR m.name = $module        THEN 1.0 ELSE $pen_mod END)
     * (CASE WHEN $channel  IS NULL OR $channel  IN kanallar   THEN 1.0 ELSE $pen_ch  END)
     * (CASE WHEN $activity IS NULL OR $activity IN faaliyetler THEN 1.0 ELSE $pen_ac END)
     * (CASE WHEN i.created_at >= datetime() - duration('P18M') THEN $boost_fresh ELSE 1.0 END)
     AS s
ORDER BY s DESC LIMIT $k
MATCH (t:Ticket)-[:CONTAINS_INCIDENT]->(i)
OPTIONAL MATCH (i)-[:MENTIONS]->(a:Artifact) WHERE a.kind <> 'Generic'
RETURN t.id AS ticket_id, i.incident_id AS incident_id, s AS skor,
       i.symptom AS symptom, i.findings AS findings, i.root_cause AS root_cause,
       i.resolution AS resolution, i.outcome AS outcome,
       m.name AS modul, f.name AS feature, kanallar, faaliyetler, ekipler,
       t.created_at AS tarih,
       [x IN collect(DISTINCT a)[0..8] | {ad: x.name, tip: x.kind}] AS artifacts
"""

# Hata kodu/metot adı geçen sorgular için: artifact üzerinden gir, incident'e yürü.
RETRIEVE_ARTIFACT = """
CALL db.index.fulltext.queryNodes('artifact_ft', $query) YIELD node AS a, score
WHERE a.kind <> 'Generic'
WITH a, score LIMIT 100
MATCH (i:Incident)-[:MENTIONS]->(a) WHERE i.has_knowledge
WITH i, max(score) AS score
ORDER BY score DESC LIMIT $k
MATCH (t:Ticket)-[:CONTAINS_INCIDENT]->(i)
OPTIONAL MATCH (i)-[:AFFECTS]->(f:Feature)-[:PART_OF]->(m:Module)
OPTIONAL MATCH (i)-[:MENTIONS]->(x:Artifact) WHERE x.kind <> 'Generic'
RETURN t.id AS ticket_id, i.incident_id AS incident_id, score AS skor,
       i.symptom AS symptom, i.findings AS findings, i.root_cause AS root_cause,
       i.resolution AS resolution, i.outcome AS outcome,
       m.name AS modul, f.name AS feature, t.created_at AS tarih,
       [] AS kanallar, [] AS faaliyetler, [] AS ekipler,
       [y IN collect(DISTINCT x)[0..8] | {ad: y.name, tip: y.kind}] AS artifacts
"""


def lucene(keywords: list[str]) -> str:
    terms = [_LUCENE.sub(r"\\\1", k.strip()) for k in keywords if k and k.strip()]
    return " OR ".join(t for t in terms if t)


VECTOR = """
CALL db.index.vector.queryNodes('incident_vec', $topn, $vec) YIELD node AS i, score
WHERE i.has_knowledge
OPTIONAL MATCH (i)-[:AFFECTS]->(f:Feature)-[:PART_OF]->(m:Module)
OPTIONAL MATCH (i)-[:VIA_CHANNEL]->(ch:Channel)
OPTIONAL MATCH (i)-[:HAS_ACTIVITY]->(ac:Activity)
OPTIONAL MATCH (i)-[:SOURCED_FROM]->(tm:Team)
WITH i, score, m, f,
     collect(DISTINCT ch.name) AS kanallar,
     collect(DISTINCT ac.name) AS faaliyetler,
     collect(DISTINCT tm.name) AS ekipler
WITH i, m, f, kanallar, faaliyetler, ekipler,
     score
     * (CASE WHEN $module   IS NULL OR m.name = $module         THEN 1.0 ELSE $pen_mod END)
     * (CASE WHEN $channel  IS NULL OR $channel  IN kanallar    THEN 1.0 ELSE $pen_ch  END)
     * (CASE WHEN $activity IS NULL OR $activity IN faaliyetler THEN 1.0 ELSE $pen_ac END)
     AS s
ORDER BY s DESC LIMIT $k
MATCH (t:Ticket)-[:CONTAINS_INCIDENT]->(i)
OPTIONAL MATCH (i)-[:MENTIONS]->(a:Artifact) WHERE a.kind <> 'Generic'
RETURN t.id AS ticket_id, i.incident_id AS incident_id, s AS skor,
       i.symptom AS symptom, i.findings AS findings, i.root_cause AS root_cause,
       i.resolution AS resolution, i.outcome AS outcome,
       m.name AS modul, f.name AS feature, kanallar, faaliyetler, ekipler,
       t.created_at AS tarih,
       [x IN collect(DISTINCT a)[0..8] | {ad: x.name, tip: x.kind}] AS artifacts
"""


def rrf(*rankings, k: int = 60, ident=lambda r: (r["ticket_id"], r["incident_id"])) -> list[dict]:
    """Reciprocal Rank Fusion: skor 1/(k+sıra). Farklı ölçekli skorları
    normalize etmeden birleştirir; yalnızca sıralamayı kullanır. ident: satırın
    kimliği (varsayılan incident; API dokümanlarında bölüm id'si)."""
    acc: dict = {}
    for rank_list in rankings:
        for pos, row in enumerate(rank_list, 1):
            key = ident(row)
            if key not in acc:
                acc[key] = dict(row)
                acc[key]["rrf"] = 0.0
            acc[key]["rrf"] += 1.0 / (k + pos)
    return sorted(acc.values(), key=lambda x: -x["rrf"])


# --- API doküman bölümleri (scripts/load_api_docs.py) ---
DOC_K = 2                 # soru başına en fazla bölüm
DOC_MAX_CHARS = 3000      # bölüm başına sentez bağlamına giren metin
DOC_VEC_MIN = 0.79        # yalnız benzerlikle eklenme eşiği (cosine)
DOC_VEC_WINDOW = 0.03     # aday kümesi: en yakın bölüme bu kadar yakın olanlar
API_MODULES = {"REST/SOAP API", "API Erişimi"}

_DOC_FIELDS = ("d.id AS id, d.protocol AS protocol, d.service AS service, d.method AS method, "
               "d.summary AS summary, d.url AS url, d.text AS text")
DOC_FT = f"""
CALL db.index.fulltext.queryNodes('apidoc_ft', $query) YIELD node AS d, score
RETURN {_DOC_FIELDS}, score ORDER BY score DESC LIMIT $k
"""
DOC_VEC = f"""
CALL db.index.vector.queryNodes('apidoc_vec', $k, $vec) YIELD node AS d, score
RETURN {_DOC_FIELDS}, score
"""
DOC_BY_METHOD = f"""
MATCH (d:ApiDoc) WHERE toLower(d.method) IN $names
RETURN {_DOC_FIELDS}, 1.0 AS score
"""


class RetrieverV2:
    def __init__(self) -> None:
        for k in ("NEO4J_V2_URI", "NEO4J_V2_USERNAME", "NEO4J_V2_PASSWORD", "NEO4J_V2_DATABASE"):
            if not os.environ.get(k):
                raise SystemExit(f"Eksik ortam değişkeni: {k}")
        self.driver = GraphDatabase.driver(
            os.environ["NEO4J_V2_URI"],
            auth=(os.environ["NEO4J_V2_USERNAME"], os.environ["NEO4J_V2_PASSWORD"]))
        self.db = os.environ["NEO4J_V2_DATABASE"]
        # Ceza katsayıları: 1.0'a yakın olan eksen zayıf etkiler.
        self.pen = {"pen_mod": 0.70, "pen_ch": 0.80, "pen_ac": 0.85, "boost_fresh": 1.15}
        self._emb_warned = False
        # Aynı soru hem her niyetin vektör aramasında hem doküman aramasında gömülür.
        self._emb_cache: dict = {}
        self._doc_methods: Optional[dict] = None
        self._doc_warned = False

    def close(self) -> None:
        self.driver.close()

    def _embed(self, text: str) -> Optional[list[float]]:
        # Sorgu vektörü graftakilerle aynı model ve boyutta olmalı (OPENAI_EMBED_*).
        # Hata olursa arama yalnızca fulltext'e düşer; ilk hatada uyarı basılır.
        try:
            from . import openai_llm as llm
            if text not in self._emb_cache:
                if len(self._emb_cache) > 256:
                    self._emb_cache.clear()
                self._emb_cache[text] = llm.embed([text])[0][0]
            return self._emb_cache[text]
        except Exception as exc:  # noqa: BLE001
            if not self._emb_warned:
                logging.getLogger(__name__).warning(
                    "sorgu embedding'i üretilemedi, arama yalnızca fulltext: %s", exc)
                self._emb_warned = True
            return None

    def hybrid(self, question: str, keywords: list[str], module: Optional[str] = None,
               channel: Optional[str] = None, activity: Optional[str] = None,
               k: int = 5) -> list[dict]:
        """Fulltext + vektör, RRF ile birleştirilmiş."""
        ft = self.retrieve(keywords, module, channel, activity, k=k * 4, with_artifacts=False)
        vec = self._embed(question)
        if not vec:
            return ft[:k]
        params = {"vec": vec, "topn": k * 8, "module": module, "channel": channel,
                  "activity": activity, "k": k * 4, **self.pen}
        with self.driver.session(database=self.db) as s:
            vr = [dict(r) for r in s.run(VECTOR, parameters=params)]
        return rrf(ft, vr)[:k]

    def _known_methods(self) -> dict:
        """Dokümanlı metot adları: küçük harf -> özgün yazım. Boş sonuç önbelleğe
        alınmaz; dokümanlar sonradan yüklenirse yeniden başlatmadan görünür."""
        if not self._doc_methods:
            with self.driver.session(database=self.db) as s:
                self._doc_methods = {r["m"].lower(): r["m"] for r in s.run(
                    "MATCH (d:ApiDoc) WHERE d.method IS NOT NULL RETURN DISTINCT d.method AS m")}
        return self._doc_methods

    def api_docs(self, question: str, keywords: list[str], modules: list,
                 evidence: list[dict], k: int = DOC_K) -> list[dict]:
        """Soruyla ilgili API doküman bölümleri; gerekmiyorsa boş liste.

        Doküman her soruya eklenmez (maliyet + gürültü). Eklenme sinyalleri:
          metot adı       — soruda dokümanlı, birleşik bir metot adı birebir geçiyor
          API modülü      — router modülü API ile ilgili
          biletteki metot — bulunan biletlerin artifact'lerinde dokümanlı metot var
          benzerlik       — soru ile en yakın bölümün vektör skoru DOC_VEC_MIN'i aşıyor
        Dokümanlar yüklenmemişse ya da sorgu hata verirse akış doküman olmadan sürer.
        """
        try:
            known = self._known_methods()
        except Exception:  # noqa: BLE001
            return []
        if not known:
            return []
        # "Login"/"Logout" gibi tek kelimelik adlar panel girişiyle karışır; birebir
        # eşleşme sinyali yalnızca birleşik adlarda (PostHtml gibi) sayılır.
        compound = {low for low, orig in known.items() if any(c.isupper() for c in orig[1:])}
        named = sorted({w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9_]{3,}", question)} & compound)
        in_evidence = sorted({a["ad"].lower() for r in evidence for a in (r.get("artifacts") or [])
                              if a and a.get("ad")} & compound)
        api_module = any(m in API_MODULES for m in modules if m)
        vec = self._embed(question)
        query = lucene(keywords)
        try:
            # parameters={...}: session.run'ın ilk argümanının adı "query"; Cypher
            # parametresi kwargs ile verilirse çakışıp TypeError fırlatır.
            with self.driver.session(database=self.db) as s:
                def run(cypher: str, **params) -> list[dict]:
                    return [dict(r) for r in s.run(cypher, parameters=params)]
                by_name = run(DOC_BY_METHOD, names=named) if named else []
                by_art = run(DOC_BY_METHOD, names=in_evidence) if in_evidence else []
                ft = run(DOC_FT, query=query, k=10) if query else []
                vr = run(DOC_VEC, vec=vec, k=10) if vec else []
        except Exception as exc:  # noqa: BLE001
            if not self._doc_warned:
                logging.getLogger(__name__).warning("API doküman araması başarısız: %s", exc)
                self._doc_warned = True
            return []
        signals = [name for name, on in (
            ("metot adı", bool(named)), ("API modülü", api_module),
            ("biletteki metot", bool(in_evidence)),
            ("benzerlik", bool(vr) and vr[0]["score"] >= DOC_VEC_MIN)) if on]
        if not signals:
            return []

        # Adaylar: adı birebir geçenler + en yakın vektöre DOC_VEC_WINDOW kadar yakın olanlar.
        # Fulltext ve biletteki metotlar yalnızca sıralamayı etkiler.
        vec_score = {r["id"]: r["score"] for r in vr}
        floor = (vr[0]["score"] if vr else 1.0) - DOC_VEC_WINDOW
        named_ids = {r["id"] for r in by_name}
        ranked = [r for r in rrf(by_name, by_name, vr, vr, ft, by_art, ident=lambda r: r["id"])
                  if r["id"] in named_ids or vec_score.get(r["id"], 0.0) >= floor]
        hint = ("REST" if re.search(r"\brest\b", question, re.I)
                else "SOAP" if re.search(r"\bsoap\b", question, re.I) else None)
        if hint:
            ranked.sort(key=lambda r: r["protocol"] != hint)  # kararlı sıralama: istenen protokol öne
        out, seen = [], set()
        for r in ranked:
            key = (r["method"] or r["id"]).lower()
            if key in seen:
                continue  # aynı metodun REST ve SOAP bölümü iki yeri birden doldurmasın
            seen.add(key)
            text = r["text"] or ""
            if len(text) > DOC_MAX_CHARS:
                text = text[:DOC_MAX_CHARS] + "\n…(kısaltıldı)"
            out.append({"id": r["id"], "protocol": r["protocol"], "service": r["service"],
                        "method": r["method"], "summary": r["summary"], "url": r["url"],
                        "text": text, "reason": ", ".join(signals)})
            if len(out) >= k:
                break
        return out

    def retrieve(self, keywords: list[str], module: Optional[str] = None,
                 channel: Optional[str] = None, activity: Optional[str] = None,
                 k: int = 5, with_artifacts: bool = True) -> list[dict]:
        q = lucene(keywords)
        if not q:
            return []
        params = {"query": q, "module": module, "channel": channel,
                  "activity": activity, "k": k, **self.pen}
        with self.driver.session(database=self.db) as s:
            rows = [dict(r) for r in s.run(RETRIEVE, parameters=params)]
            if with_artifacts and len(rows) < k:
                seen = {(r["ticket_id"], r["incident_id"]) for r in rows}
                for r in s.run(RETRIEVE_ARTIFACT, parameters={'query': q, 'k': k}):
                    d = dict(r)
                    if (d["ticket_id"], d["incident_id"]) not in seen:
                        rows.append(d)
                    if len(rows) >= k:
                        break
        return rows[:k]
