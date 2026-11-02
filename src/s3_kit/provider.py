from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from botocore.response import StreamingBody

from s3_kit.config import S3Config
from s3_kit.exceptions import ObjectNotFoundError

_DEFAULT_REGION = "us-east-1"
_STREAM_CHUNK_SIZE = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ObjectInfo:
    """物件資訊。key 為完整路徑，S3 列表不提供 content_type，因此列表結果為 None。"""

    key: str
    size: int
    last_modified: datetime
    content_type: str | None = None

    @property
    def name(self) -> str:
        return self.key.rsplit("/", 1)[-1]


@dataclass(frozen=True, slots=True)
class DirectoryListing:
    """單一層目錄的內容。folders 為相對於該目錄的名稱。"""

    folders: list[str]
    files: list[ObjectInfo]


def _error_code(error: ClientError) -> str:
    return error.response.get("Error", {}).get("Code", "")


def _to_object_info(item: dict) -> ObjectInfo:
    return ObjectInfo(
        key=item["Key"], size=item["Size"], last_modified=item["LastModified"]
    )


def _iter_chunks(body: StreamingBody, chunk_size: int) -> Iterator[bytes]:
    with body:
        yield from body.iter_chunks(chunk_size)


class S3Provider:
    """用標準 S3 API 操作單一 bucket，不包含任何後端專屬邏輯。"""

    def __init__(self, config: S3Config) -> None:
        self._bucket = config.bucket
        self._region = config.region
        self._client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            region_name=config.region,
            aws_access_key_id=config.access_key,
            aws_secret_access_key=config.secret_key,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path" if config.force_path_style else "auto"},
                # boto3 預設的額外 checksum 不是所有 S3 相容服務都支援
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def ensure_bucket(self) -> None:
        """bucket 不存在時建立。"""
        try:
            self._client.head_bucket(Bucket=self._bucket)
            return
        except ClientError as error:
            if _error_code(error) not in {"404", "NoSuchBucket"}:
                raise

        if self._region == _DEFAULT_REGION:
            self._client.create_bucket(Bucket=self._bucket)
        else:
            self._client.create_bucket(
                Bucket=self._bucket,
                CreateBucketConfiguration={"LocationConstraint": self._region},
            )

    def put_object(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, **extra)

    def upload_stream(
        self,
        key: str,
        stream: BinaryIO,
        content_type: str | None = None,
    ) -> None:
        """分塊上傳檔案物件，大檔案會自動使用分段上傳。"""
        extra = {"ContentType": content_type} if content_type else {}
        self._client.upload_fileobj(stream, self._bucket, key, ExtraArgs=extra)

    def get_object(self, key: str) -> bytes:
        return self._open_object(key).read()

    def download_stream(
        self,
        key: str,
        chunk_size: int = _STREAM_CHUNK_SIZE,
    ) -> Iterator[bytes]:
        """分塊下載大檔案。物件不存在時會立即拋出例外，不會等到開始讀取。"""
        return _iter_chunks(self._open_object(key), chunk_size)

    def _open_object(self, key: str) -> StreamingBody:
        try:
            return self._client.get_object(Bucket=self._bucket, Key=key)["Body"]
        except ClientError as error:
            if _error_code(error) == "NoSuchKey":
                raise ObjectNotFoundError(key) from error
            raise

    def get_info(self, key: str) -> ObjectInfo:
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            if _error_code(error) == "404":
                raise ObjectNotFoundError(key) from error
            raise
        return ObjectInfo(
            key=key,
            size=response["ContentLength"],
            last_modified=response["LastModified"],
            content_type=response.get("ContentType"),
        )

    def delete_object(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            if _error_code(error) == "404":
                return False
            raise
        return True

    def list_objects(self, prefix: str = "") -> Iterator[ObjectInfo]:
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                yield _to_object_info(item)

    def list_keys(self, prefix: str = "") -> Iterator[str]:
        for info in self.list_objects(prefix):
            yield info.key

    def list_dir(self, path: str = "") -> DirectoryListing:
        """像 ls 一樣只列出一層。S3 沒有真正的目錄，這裡以 / 分隔 key 來模擬。"""
        path = path.strip("/")
        prefix = f"{path}/" if path else ""
        folders: list[str] = []
        files: list[ObjectInfo] = []

        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=self._bucket, Prefix=prefix, Delimiter="/"
        ):
            for item in page.get("CommonPrefixes", []):
                folders.append(item["Prefix"].removeprefix(prefix))
            for item in page.get("Contents", []):
                # 略過代表目錄本身的佔位物件
                if item["Key"] != prefix:
                    files.append(_to_object_info(item))

        return DirectoryListing(folders=folders, files=files)

    def presigned_get_url(self, key: str, expires_in: int = 3600) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )
