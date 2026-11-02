from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO
from urllib.parse import quote

import boto3
from boto3.exceptions import S3UploadFailedError
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    HTTPClientError,
    NoCredentialsError,
)
from botocore.exceptions import (
    ConnectionError as BotoConnectionError,
)
from botocore.response import StreamingBody

from s3_kit.config import S3Config
from s3_kit.exceptions import (
    AccessDeniedError,
    BucketNotFoundError,
    ObjectNotFoundError,
    S3KitError,
    StorageConnectionError,
)

_DEFAULT_REGION = "us-east-1"
_STREAM_CHUNK_SIZE = 8 * 1024 * 1024
# SigV4 預簽連結的有效期限上限為 7 天
_MAX_PRESIGN_EXPIRES_IN = 7 * 24 * 60 * 60
# 預簽 POST 單次上傳的上限為 5 GB
_MAX_POST_SIZE = 5 * 1024 * 1024 * 1024
# 標準 S3 錯誤代碼；HEAD 請求沒有 body，只能拿到 HTTP 狀態碼
_ACCESS_DENIED_CODES = {
    "AccessDenied",
    "InvalidAccessKeyId",
    "SignatureDoesNotMatch",
    # 臨時憑證過期或無效
    "ExpiredToken",
    "InvalidToken",
    # 用戶端時間與服務相差太多，簽名被拒絕
    "RequestTimeTooSkewed",
    "403",
}


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


@dataclass(frozen=True, slots=True)
class PresignedPost:
    """預簽 POST 上傳表單。

    上傳端用 multipart/form-data 對 url 送出 fields 的所有欄位，檔案欄位 file 必須放在最後。
    """

    url: str
    fields: dict[str, str]


def _error_code(error: ClientError) -> str:
    return error.response.get("Error", {}).get("Code", "")


def _to_object_info(item: dict) -> ObjectInfo:
    return ObjectInfo(
        key=item["Key"], size=item["Size"], last_modified=item["LastModified"]
    )


def _translate_error(error: Exception, bucket: str, key: str | None) -> S3KitError:
    # upload_fileobj 會把 ClientError 包成 S3UploadFailedError，原始錯誤在 __context__
    if isinstance(error, S3UploadFailedError) and isinstance(
        error.__context__, (ClientError, BotoCoreError)
    ):
        error = error.__context__
    if isinstance(error, ClientError):
        code = _error_code(error)
        if code == "NoSuchKey" and key is not None:
            return ObjectNotFoundError(key)
        if code == "NoSuchBucket":
            return BucketNotFoundError(bucket)
        if code in _ACCESS_DENIED_CODES:
            return AccessDeniedError(str(error))
    # 省略金鑰且 boto3 預設的憑證來源也找不到憑證
    if isinstance(error, NoCredentialsError):
        return AccessDeniedError(str(error))
    if isinstance(error, (BotoConnectionError, HTTPClientError)):
        return StorageConnectionError(str(error))
    return S3KitError(str(error))


class S3Provider:
    """用標準 S3 API 操作單一 bucket，不包含任何後端專屬邏輯。"""

    def __init__(self, config: S3Config) -> None:
        self._bucket = config.bucket
        self._region = config.region

        config_options: dict = {
            "signature_version": "s3v4",
            "s3": {"addressing_style": "path" if config.force_path_style else "auto"},
            # boto3 預設的額外 checksum 不是所有 S3 相容服務都支援
            "request_checksum_calculation": "when_required",
            "response_checksum_validation": "when_required",
        }
        if config.connect_timeout is not None:
            config_options["connect_timeout"] = config.connect_timeout
        if config.read_timeout is not None:
            config_options["read_timeout"] = config.read_timeout
        if config.max_attempts is not None:
            # botocore 的 max_attempts 不含第一次請求，total_max_attempts 才是總嘗試次數
            config_options["retries"] = {
                "total_max_attempts": config.max_attempts,
                "mode": "standard",
            }

        client_options: dict = {
            "region_name": config.region,
            "config": Config(**config_options),
        }
        # 省略金鑰時交給 boto3 預設的憑證來源（環境變數、設定檔、IAM role 等）
        if config.access_key is not None:
            client_options["aws_access_key_id"] = config.access_key
            client_options["aws_secret_access_key"] = config.secret_key
            client_options["aws_session_token"] = config.session_token
        # verify 為 True 時不傳入，保留 boto3 讀取 AWS_CA_BUNDLE 等設定的預設行為
        if config.verify is not True:
            client_options["verify"] = config.verify

        # 每個 provider 使用自己的 session，boto3 的預設 session 不適合多執行緒共用
        session = boto3.session.Session()
        self._client = session.client(
            "s3", endpoint_url=config.endpoint_url, **client_options
        )
        # SigV4 簽名包含 Host，對外連結必須用對外位址簽名，不能事後替換網址。
        # 產生預簽連結不會發出請求，服務本身不需要連得到對外位址。
        self._presign_client = (
            session.client(
                "s3", endpoint_url=config.public_endpoint_url, **client_options
            )
            if config.public_endpoint_url
            else self._client
        )

    @contextmanager
    def _translate_errors(self, key: str | None = None) -> Iterator[None]:
        """把 boto3 的例外轉成 S3-kit 的例外，原始例外保留在 __cause__。"""
        try:
            yield
        except (ClientError, BotoCoreError, S3UploadFailedError) as error:
            raise _translate_error(error, self._bucket, key) from error

    def _raise_if_bucket_missing(self) -> None:
        """HEAD 物件回傳 404 時，bucket 不存在和物件不存在無法區分，需要再確認 bucket。"""
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as error:
            if _error_code(error) in {"404", "NoSuchBucket"}:
                raise BucketNotFoundError(self._bucket) from error
            raise

    def ensure_bucket(self) -> None:
        """bucket 不存在時建立。多個程序同時呼叫也不會出錯。"""
        with self._translate_errors():
            try:
                self._client.head_bucket(Bucket=self._bucket)
                return
            except ClientError as error:
                if _error_code(error) not in {"404", "NoSuchBucket"}:
                    raise

            params: dict = {"Bucket": self._bucket}
            if self._region != _DEFAULT_REGION:
                params["CreateBucketConfiguration"] = {
                    "LocationConstraint": self._region
                }
            try:
                self._client.create_bucket(**params)
            except ClientError as error:
                # 檢查之後到建立之前，bucket 可能已被其他程序建立
                if _error_code(error) != "BucketAlreadyOwnedByYou":
                    raise

    def put_object(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        with self._translate_errors(key):
            self._client.put_object(Bucket=self._bucket, Key=key, Body=data, **extra)

    def upload_stream(
        self,
        key: str,
        stream: BinaryIO,
        content_type: str | None = None,
    ) -> None:
        """分塊上傳檔案物件，大檔案會自動使用分段上傳。"""
        extra = {"ContentType": content_type} if content_type else {}
        with self._translate_errors(key):
            self._client.upload_fileobj(stream, self._bucket, key, ExtraArgs=extra)

    def get_object(self, key: str) -> bytes:
        body = self._open_object(key)
        with body, self._translate_errors(key):
            return body.read()

    def download_stream(
        self,
        key: str,
        chunk_size: int = _STREAM_CHUNK_SIZE,
    ) -> Iterator[bytes]:
        """分塊下載大檔案。物件不存在時會立即拋出例外，不會等到開始讀取。"""
        return self._iter_chunks(self._open_object(key), key, chunk_size)

    def _open_object(self, key: str) -> StreamingBody:
        with self._translate_errors(key):
            return self._client.get_object(Bucket=self._bucket, Key=key)["Body"]

    def _iter_chunks(
        self, body: StreamingBody, key: str, chunk_size: int
    ) -> Iterator[bytes]:
        # 讀取中途斷線也要轉成 S3-kit 的例外
        with body, self._translate_errors(key):
            yield from body.iter_chunks(chunk_size)

    def get_info(self, key: str) -> ObjectInfo:
        with self._translate_errors(key):
            try:
                response = self._client.head_object(Bucket=self._bucket, Key=key)
            except ClientError as error:
                if _error_code(error) != "404":
                    raise
                self._raise_if_bucket_missing()
                raise ObjectNotFoundError(key) from error
        return ObjectInfo(
            key=key,
            size=response["ContentLength"],
            last_modified=response["LastModified"],
            content_type=response.get("ContentType"),
        )

    def delete_object(self, key: str) -> None:
        """刪除不存在的 key 不會報錯，bucket 不存在時拋出 BucketNotFoundError。"""
        with self._translate_errors(key):
            self._client.delete_object(Bucket=self._bucket, Key=key)

    def exists(self, key: str) -> bool:
        """bucket 不存在時拋出 BucketNotFoundError，不會回傳 False。"""
        with self._translate_errors(key):
            try:
                self._client.head_object(Bucket=self._bucket, Key=key)
            except ClientError as error:
                if _error_code(error) != "404":
                    raise
                self._raise_if_bucket_missing()
                return False
        return True

    def list_objects(self, prefix: str = "") -> Iterator[ObjectInfo]:
        paginator = self._client.get_paginator("list_objects_v2")
        with self._translate_errors():
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
        with self._translate_errors():
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

    def presigned_get_url(
        self,
        key: str,
        expires_in: int = 3600,
        download_name: str | None = None,
    ) -> str:
        """產生下載連結。expires_in 必須在 1 秒到 7 天之間。

        指定 download_name 時，瀏覽器會以該檔名下載，而不是在瀏覽器中開啟。
        """
        params = {"Bucket": self._bucket, "Key": key}
        if download_name is not None:
            params["ResponseContentDisposition"] = (
                f"attachment; filename*=UTF-8''{quote(download_name, safe='')}"
            )
        return self._presigned_url("get_object", params, expires_in)

    def presigned_post(
        self,
        key: str,
        expires_in: int = 3600,
        content_type: str | None = None,
        max_size: int | None = None,
        min_size: int = 0,
    ) -> PresignedPost:
        """產生上傳表單。expires_in 必須在 1 秒到 7 天之間。

        key、content_type 與檔案大小範圍（bytes）都會寫進簽名的 policy，上傳內容不符合時服務會拒絕。
        max_size 未指定時，上限為單次 POST 的 5 GB。
        """
        _check_expires_in(expires_in)
        upper = _MAX_POST_SIZE if max_size is None else max_size
        if not 0 <= min_size <= upper <= _MAX_POST_SIZE:
            raise ValueError(
                f"檔案大小必須符合 0 <= min_size <= max_size <= {_MAX_POST_SIZE}："
                f"min_size={min_size}, max_size={max_size}"
            )

        fields: dict[str, str] = {}
        conditions: list = [["content-length-range", min_size, upper]]
        if content_type is not None:
            fields["Content-Type"] = content_type
            conditions.append({"Content-Type": content_type})

        # boto3 會自動把 bucket 與 key 加進 policy
        with self._translate_errors(key):
            response = self._presign_client.generate_presigned_post(
                self._bucket,
                key,
                Fields=fields,
                Conditions=conditions,
                ExpiresIn=expires_in,
            )
        return PresignedPost(url=response["url"], fields=response["fields"])

    def _presigned_url(self, operation: str, params: dict, expires_in: int) -> str:
        _check_expires_in(expires_in)
        with self._translate_errors(params["Key"]):
            return self._presign_client.generate_presigned_url(
                operation, Params=params, ExpiresIn=expires_in
            )


def _check_expires_in(expires_in: int) -> None:
    # 超出 SigV4 上限的連結會被服務拒絕，提早拋出錯誤
    if not 1 <= expires_in <= _MAX_PRESIGN_EXPIRES_IN:
        raise ValueError(
            f"expires_in 必須在 1 到 {_MAX_PRESIGN_EXPIRES_IN} 秒之間：{expires_in}"
        )
