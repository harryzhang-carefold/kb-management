"""Elasticsearch 客户端 — 全文 + 向量混合检索。"""
from typing import Any, Optional
import time

from loguru import logger
from elasticsearch import Elasticsearch

from app.core.config import settings


class ESClient:
    def __init__(self):
        self._es: Optional[Elasticsearch] = None
        self.index = settings.es_index

    @property
    def es(self) -> Elasticsearch:
        if self._es is None:
            auth = None
            if settings.es_username:
                auth = (settings.es_username, settings.es_password or "")
            self._es = Elasticsearch(
                settings.es_host,
                basic_auth=auth,
                request_timeout=30,
            )
        return self._es

    def _existing_dim(self) -> Optional[int]:
        """读取现有索引 embedding 字段的 dims（不存在返回 None）。"""
        try:
            m = self.es.indices.get_mapping(index=self.index)
            props = m.get(self.index, {}).get("mappings", {}).get("properties", {})
            return (props.get("embedding") or {}).get("dims")
        except Exception:
            return None

    def ensure_index(self, embedding_dim: int = 3584):
        """确保索引存在（幂等）。

        维度不一致时（如外部 embedding 端点切换、维度变化）：
        - 索引为空 → 删除后按新维度重建；
        - 索引非空且维度不符 → 抛错，由调用方（启动/任务）降级为告警，不静默丢数据。
        """
        if self.es.indices.exists(index=self.index):
            dim = self._existing_dim()
            if dim != embedding_dim:
                try:
                    cnt = self.es.count(index=self.index).get("count", 0)
                except Exception:
                    cnt = -1
                if cnt == 0:
                    logger.warning(f"ES index {self.index} dim {dim} != {embedding_dim} "
                                   f"but empty → recreating")
                    self.es.indices.delete(index=self.index)
                    # 落到下方重建
                elif cnt > 0:
                    raise RuntimeError(
                        f"ES index {self.index} dim {dim} != requested {embedding_dim} "
                        f"and has {cnt} docs — refuse to recreate")
                else:
                    # cnt<0（count 查询失败）：保守起见不动索引
                    return
                if self.es.indices.exists(index=self.index):
                    return
            else:
                return
        body = {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {
                "properties": {
                    "chunk_id": {"type": "keyword"},
                    "document_id": {"type": "keyword"},
                    "kb_id": {"type": "keyword"},
                    "chunk_index": {"type": "integer"},
                    "content": {"type": "text"},
                    "embedding": {"type": "dense_vector", "dims": embedding_dim,
                                  "index": True, "similarity": "cosine"},
                    "token_count": {"type": "integer"},
                    "metadata": {"type": "object", "enabled": True},
                    "file_name": {"type": "keyword"},
                    "file_type": {"type": "keyword"},
                    "created_at": {"type": "date"},
                }
            },
        }
        self.es.indices.create(index=self.index, body=body)
        logger.info(f"ES index {self.index} created (dim={embedding_dim})")

    def index_chunks(self, kb_id: str, document_id: str, file_name: str, file_type: str,
                     chunks: list[dict]):
        """批量写入分块。chunks: [{chunk_id, chunk_index, content, embedding, token_count, metadata}]"""
        if not chunks:
            return
        actions = []
        for c in chunks:
            actions.append({
                "_op_type": "index",
                "_index": self.index,
                "_id": c["chunk_id"],
                "chunk_id": c["chunk_id"],
                "document_id": document_id,
                "kb_id": kb_id,
                "chunk_index": c["chunk_index"],
                "content": c["content"],
                "embedding": c.get("embedding"),
                "token_count": c.get("token_count", 0),
                "metadata": c.get("metadata", {}),
                "file_name": file_name,
                "file_type": file_type,
                "created_at": c.get("created_at"),
            })
        from elasticsearch.helpers import bulk
        _, errors = bulk(self.es, actions, raise_on_error=False)
        if errors:
            logger.warning(f"ES bulk partial errors: {len(errors)}")

    def delete_document(self, document_id: str):
        self.es.delete_by_query(
            index=self.index,
            body={"query": {"term": {"document_id": document_id}}},
            refresh=True,
        )
        logger.info(f"ES deleted chunks for document {document_id}")

    def delete_kb(self, kb_id: str):
        self.es.delete_by_query(
            index=self.index,
            body={"query": {"term": {"kb_id": kb_id}}},
            refresh=True,
        )
        logger.info(f"ES deleted chunks for kb {kb_id}")

    def hybrid_search(self, kb_id: str, query: str, query_vector: list[float],
                      mode: str = "hybrid", top_k: int = 10,
                      filters: Optional[dict] = None) -> list[dict]:
        """混合检索：向量 kNN + BM25，RRF 融合。"""
        start = time.time()
        base_filter = [{"term": {"kb_id": kb_id}}]
        if filters and filters.get("file_type"):
            base_filter.append({"term": {"file_type": filters["file_type"]}})

        # ---- 向量 kNN 检索 ----
        # BUG-01（P1 跨库泄露）根因：ES 8 对顶层 `query` 与 `knn` 的命中**取并集**。
        # 此前顶层是 {"match_all": {"boost": 0}} —— 没有任何 kb_id 过滤，于是全索引
        # 其它知识库的 chunk（score=0）被并入结果，正好填满 size=top_k
        # （多租户共用一个 kb_chunks 索引，隔离**完全**依赖这份 filter）。
        # 修复：kNN 路径不再声明顶层 query，过滤只由 knn.filter=base_filter 承担。
        vector_hits = []
        if mode in ("hybrid", "vector") and query_vector:
            body = {
                "size": top_k,
                "knn": {
                    "field": "embedding",
                    "query_vector": query_vector,
                    "k": top_k,
                    "num_candidates": top_k * 3,
                    "filter": base_filter,
                },
            }
            resp = self.es.search(index=self.index, body=body)
            for h in resp["hits"]["hits"]:
                # 防御性第二层（多租户隔离红线）：即使将来查询体再度回归，
                # 也不把 kb_id 不匹配的 chunk 交给上层业务。
                if h["_source"].get("kb_id") != kb_id:
                    logger.warning(
                        f"hybrid_search: dropped foreign chunk "
                        f"document_id={h['_source'].get('document_id')} "
                        f"kb_id={h['_source'].get('kb_id')} (query kb_id={kb_id})")
                    continue
                vector_hits.append({
                    "chunk_id": h["_id"],
                    "document_id": h["_source"]["document_id"],
                    "filename": h["_source"]["file_name"],
                    "chunk_index": h["_source"]["chunk_index"],
                    "content": h["_source"]["content"],
                    "metadata": h["_source"].get("metadata", {}),
                    "score": h.get("_score", 0.0),
                    "match_type": "vector",
                })

        # ---- BM25 全文检索 ----
        keyword_hits = []
        if mode in ("hybrid", "keyword"):
            body = {
                "size": top_k,
                "query": {
                    "bool": {
                        "must": [{"match": {"content": query}}],
                        "filter": base_filter,
                    }
                },
                "highlight": {"fields": {"content": {"fragment_size": 200, "number_of_fragments": 1}}},
            }
            resp = self.es.search(index=self.index, body=body)
            for h in resp["hits"]["hits"]:
                # 防御性第二层：同 kNN 分支，kb_id 不匹配的 chunk 一律不下发
                if h["_source"].get("kb_id") != kb_id:
                    logger.warning(
                        f"hybrid_search(keyword): dropped foreign chunk "
                        f"document_id={h['_source'].get('document_id')} "
                        f"kb_id={h['_source'].get('kb_id')} (query kb_id={kb_id})")
                    continue
                keyword_hits.append({
                    "chunk_id": h["_id"],
                    "document_id": h["_source"]["document_id"],
                    "filename": h["_source"]["file_name"],
                    "chunk_index": h["_source"]["chunk_index"],
                    "content": h["_source"]["content"],
                    "metadata": h["_source"].get("metadata", {}),
                    "score": h.get("_score", 0.0),
                    "match_type": "keyword",
                    "highlight": (h.get("highlight", {}).get("content") or [h["_source"]["content"]])[0],
                })

        # ---- RRF 融合 ----
        if mode == "vector":
            results = vector_hits
        elif mode == "keyword":
            results = keyword_hits
        else:
            results = self._rrf_fuse(vector_hits, keyword_hits, k=60)

        for r in results:
            if mode == "hybrid":
                r["match_type"] = "hybrid"
        results = results[:top_k]
        took_ms = int((time.time() - start) * 1000)
        return results, took_ms

    @staticmethod
    def _rrf_fuse(hits_a: list[dict], hits_b: list[dict], k: int = 60) -> list[dict]:
        """Reciprocal Rank Fusion 融合两路结果。"""
        scores: dict[str, float] = {}
        items: dict[str, dict] = {}
        for rank, h in enumerate(hits_a, start=1):
            cid = h["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            items[cid] = h
        for rank, h in enumerate(hits_b, start=1):
            cid = h["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            if cid not in items:
                items[cid] = h
        merged = sorted(items.values(), key=lambda x: scores[x["chunk_id"]], reverse=True)
        for m in merged:
            m["score"] = round(scores[m["chunk_id"]], 6)
        return merged

    def count(self, kb_id: Optional[str] = None) -> int:
        body = {"query": {"match_all": {}}} if not kb_id else {"query": {"term": {"kb_id": kb_id}}}
        resp = self.es.count(index=self.index, body=body)
        return resp.get("count", 0)


es_client = ESClient()
