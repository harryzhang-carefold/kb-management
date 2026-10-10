"""MinIO 对象存储客户端（S3 兼容）。bucket 自动创建。"""
import io
from typing import Optional

from loguru import logger
from minio import Minio
from minio.error import S3Error

from app.core.config import settings


class MinioClient:
    def __init__(self):
        self._client: Optional[Minio] = None
        self.bucket = "kb-docs"

    @property
    def client(self) -> Minio:
        if self._client is None:
            self._client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=False,
            )
            self._ensure_bucket()
        return self._client

    def _ensure_bucket(self):
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info(f"MinIO bucket '{self.bucket}' created")
        except S3Error as e:
            logger.error(f"MinIO bucket ensure failed: {e}")

    def put_object(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self.client.put_object(
            self.bucket, key, io.BytesIO(data), length=len(data),
            content_type=content_type,
        )
        logger.info(f"MinIO put {key} ({len(data)} bytes)")
        return key

    def get_object(self, key: str) -> bytes:
        resp = self.client.get_object(self.bucket, key)
        data = resp.read()
        resp.close()
        resp.release_conn()
        return data

    def get_presigned_url(self, key: str, expires_hours: int = 1) -> str:
        from datetime import timedelta
        url = self.client.presigned_get_object(self.bucket, key, expires=timedelta(hours=expires_hours))
        return url

    def remove_object(self, key: str):
        try:
            self.client.remove_object(self.bucket, key)
            logger.info(f"MinIO removed {key}")
        except S3Error as e:
            logger.warning(f"MinIO remove {key} failed: {e}")

    def remove_prefix(self, prefix: str):
        """删除某前缀下所有对象（删除知识库/文档时清理）。"""
        objs = list(self.client.list_objects(self.bucket, prefix=prefix, recursive=True))
        for o in objs:
            self.client.remove_object(self.bucket, o.object_name)
        if objs:
            logger.info(f"MinIO removed {len(objs)} objects under prefix {prefix}")

    def count_objects(self, prefix: str = "") -> int:
        return len(list(self.client.list_objects(self.bucket, prefix=prefix, recursive=True)))

    def bucket_size(self) -> int:
        total = 0
        for o in self.client.list_objects(self.bucket, recursive=True):
            total += o.size or 0
        return total


minio_client = MinioClient()
