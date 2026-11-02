import hashlib
import io
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import replace
from datetime import datetime

import pytest

from s3_kit import (
    AccessDeniedError,
    BucketNotFoundError,
    ObjectNotFoundError,
    PresignedPost,
    S3Provider,
    StorageConnectionError,
)

MB = 1024 * 1024


class GeneratedStream:
    """邊讀邊產生資料的串流，不需要事先把大檔案放進記憶體。"""

    def __init__(self, size: int) -> None:
        self._remaining = size
        self._counter = 0
        self.digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        size = self._remaining if size < 0 else min(size, self._remaining)
        if size == 0:
            return b""

        block = (self._counter.to_bytes(8, "big") * (size // 8 + 1))[:size]
        self._counter += 1
        self._remaining -= size
        self.digest.update(block)
        return block


def test_ensure_bucket_can_run_twice(provider):
    provider.ensure_bucket()

    provider.put_object("a.txt", b"hello")
    assert provider.exists("a.txt")


def test_object_lifecycle(provider):
    provider.put_object("a/b.txt", b"hello", content_type="text/plain")

    assert provider.exists("a/b.txt") is True
    assert provider.get_object("a/b.txt") == b"hello"

    provider.delete_object("a/b.txt")

    assert provider.exists("a/b.txt") is False


def test_put_object_overwrites_existing_key(provider):
    provider.put_object("a.txt", b"old")
    provider.put_object("a.txt", b"new")

    assert provider.get_object("a.txt") == b"new"


def test_missing_object_raises(provider):
    with pytest.raises(ObjectNotFoundError):
        provider.get_object("missing.txt")
    with pytest.raises(ObjectNotFoundError):
        provider.get_info("missing.txt")
    with pytest.raises(ObjectNotFoundError):
        provider.download_stream("missing.txt")
    assert provider.exists("missing.txt") is False


def test_delete_object_ignores_missing_key(provider):
    provider.delete_object("missing.txt")


def test_get_info(provider):
    provider.put_object("a/b.txt", b"hello", content_type="text/plain")

    info = provider.get_info("a/b.txt")

    assert info.key == "a/b.txt"
    assert info.name == "b.txt"
    assert info.size == 5
    assert info.content_type == "text/plain"
    assert isinstance(info.last_modified, datetime)


def test_stream_round_trip_with_multipart_upload(provider):
    size = 64 * MB
    source = GeneratedStream(size)

    provider.upload_stream("large.bin", source, content_type="application/zip")

    info = provider.get_info("large.bin")
    assert info.size == size
    assert info.content_type == "application/zip"

    digest = hashlib.sha256()
    received = 0
    for chunk in provider.download_stream("large.bin"):
        digest.update(chunk)
        received += len(chunk)

    assert received == size
    assert digest.hexdigest() == source.digest.hexdigest()


def test_upload_stream_small_file(provider):
    provider.upload_stream("a.txt", io.BytesIO(b"hello"))

    assert provider.get_object("a.txt") == b"hello"


def test_list_objects_and_keys(provider):
    provider.put_object("a/b/c.txt", b"hello")
    provider.put_object("a/d.txt", b"")
    provider.put_object("e.txt", b"")

    assert sorted(provider.list_keys()) == ["a/b/c.txt", "a/d.txt", "e.txt"]
    assert sorted(provider.list_keys(prefix="a/")) == ["a/b/c.txt", "a/d.txt"]

    sizes = {info.key: info.size for info in provider.list_objects()}
    assert sizes["a/b/c.txt"] == 5


def test_list_dir(provider):
    provider.put_object("images/a.png", b"hello")
    provider.put_object("images/2026/b.png", b"")
    provider.put_object("root.txt", b"")

    root = provider.list_dir()
    assert root.folders == ["images/"]
    assert [info.key for info in root.files] == ["root.txt"]

    images = provider.list_dir("images")
    assert images.folders == ["2026/"]
    assert [(info.name, info.size) for info in images.files] == [("a.png", 5)]

    missing = provider.list_dir("missing")
    assert missing.folders == []
    assert missing.files == []


def test_presigned_get_url(provider):
    provider.put_object("a.txt", b"hello")

    with urllib.request.urlopen(provider.presigned_get_url("a.txt")) as response:
        assert response.read() == b"hello"


def test_presigned_get_url_uses_public_endpoint(provider, public_endpoint_provider):
    provider.put_object("a.txt", b"hello")

    url = public_endpoint_provider.presigned_get_url("a.txt")

    assert url.startswith("http://localhost:19000/")
    with urllib.request.urlopen(url) as response:
        assert response.read() == b"hello"


def test_presigned_get_url_sets_download_name(provider):
    provider.put_object("a/uuid.txt", b"hello")

    url = provider.presigned_get_url("a/uuid.txt", download_name="報告 1.txt")

    with urllib.request.urlopen(url) as response:
        assert response.read() == b"hello"
        assert (
            response.headers["Content-Disposition"]
            == "attachment; filename*=UTF-8''%E5%A0%B1%E5%91%8A%201.txt"
        )


def post_form(
    post: PresignedPost, data: bytes, overrides: dict[str, str] | None = None
) -> int:
    """用 multipart/form-data 送出預簽 POST 表單，回傳 HTTP 狀態碼。"""
    fields = {**post.fields, **(overrides or {})}
    boundary = uuid.uuid4().hex
    parts = [
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode()
        for name, value in fields.items()
    ]
    # 檔案欄位必須放在最後
    parts.append(
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="upload"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + data
        + f"\r\n--{boundary}--\r\n".encode()
    )
    request = urllib.request.Request(
        post.url,
        data=b"".join(parts),
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def test_presigned_post_uploads_object(provider):
    post = provider.presigned_post(
        "a.txt", content_type="text/plain", max_size=10, min_size=1
    )

    assert post_form(post, b"hello") == 204
    assert provider.get_object("a.txt") == b"hello"
    assert provider.get_info("a.txt").content_type == "text/plain"


@pytest.mark.parametrize("size", [1, 10])
def test_presigned_post_accepts_size_boundaries(provider, size):
    post = provider.presigned_post("a.txt", max_size=10, min_size=1)

    assert post_form(post, b"x" * size) == 204
    assert provider.get_info("a.txt").size == size


def test_presigned_post_uses_public_endpoint(provider, public_endpoint_provider):
    post = public_endpoint_provider.presigned_post("a.txt")

    assert post.url.startswith("http://localhost:19000/")
    assert post_form(post, b"hello") == 204
    assert provider.get_object("a.txt") == b"hello"


# 各後端拒絕時的狀態碼不同（RustFS 違反 policy 回 400，AWS 回 403），只確認被拒絕且沒有存檔
@pytest.mark.parametrize(
    ("data", "overrides"),
    [
        pytest.param(b"x" * 11, {}, id="too-large"),
        pytest.param(b"", {}, id="too-small"),
        pytest.param(b"hello", {"Content-Type": "image/png"}, id="wrong-content-type"),
        pytest.param(b"hello", {"key": "other.txt"}, id="tampered-key"),
        pytest.param(b"hello", {"x-amz-meta-extra": "1"}, id="extra-field"),
        pytest.param(b"hello", {"x-amz-signature": "0" * 64}, id="bad-signature"),
    ],
)
def test_presigned_post_rejects_invalid_upload(provider, data, overrides):
    post = provider.presigned_post(
        "a.txt", content_type="text/plain", max_size=10, min_size=1
    )

    assert post_form(post, data, overrides) in {400, 403}
    assert list(provider.list_keys()) == []


def test_presigned_post_rejects_expired_policy(provider):
    post = provider.presigned_post("a.txt", expires_in=1)
    time.sleep(3)

    assert post_form(post, b"hello") in {400, 403}
    assert list(provider.list_keys()) == []


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda p: p.get_object("a.txt"), id="get_object"),
        pytest.param(lambda p: p.download_stream("a.txt"), id="download_stream"),
        pytest.param(lambda p: p.get_info("a.txt"), id="get_info"),
        pytest.param(lambda p: p.exists("a.txt"), id="exists"),
        pytest.param(lambda p: p.delete_object("a.txt"), id="delete_object"),
        pytest.param(lambda p: list(p.list_keys()), id="list_keys"),
        pytest.param(lambda p: p.list_dir(), id="list_dir"),
        pytest.param(lambda p: p.put_object("a.txt", b"hello"), id="put_object"),
        pytest.param(
            lambda p: p.upload_stream("a.txt", io.BytesIO(b"hello")),
            id="upload_stream",
        ),
    ],
)
def test_missing_bucket_raises_bucket_not_found(missing_bucket_provider, operation):
    with pytest.raises(BucketNotFoundError):
        operation(missing_bucket_provider)


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda p: p.get_object("a.txt"), id="get_object"),
        pytest.param(lambda p: p.get_info("a.txt"), id="get_info"),
        pytest.param(lambda p: p.exists("a.txt"), id="exists"),
        pytest.param(lambda p: p.delete_object("a.txt"), id="delete_object"),
        pytest.param(lambda p: list(p.list_keys()), id="list_keys"),
        pytest.param(lambda p: p.put_object("a.txt", b"hello"), id="put_object"),
        pytest.param(
            lambda p: p.upload_stream("a.txt", io.BytesIO(b"hello")),
            id="upload_stream",
        ),
    ],
)
def test_wrong_secret_key_raises_access_denied(provider, rustfs_config, operation):
    wrong = S3Provider(replace(rustfs_config, secret_key="wrong-secret"))

    with pytest.raises(AccessDeniedError):
        operation(wrong)
    assert list(provider.list_keys()) == []


def test_ensure_bucket_with_wrong_secret_does_not_create_bucket(
    missing_bucket_config,
):
    wrong = S3Provider(replace(missing_bucket_config, secret_key="wrong-secret"))

    with pytest.raises(AccessDeniedError):
        wrong.ensure_bucket()


def test_unreachable_endpoint_raises_connection_error(rustfs_config):
    # port 1 沒有服務，限制逾時與重試次數，確認會在短時間內失敗
    unreachable = S3Provider(
        replace(
            rustfs_config,
            endpoint_url="http://127.0.0.1:1",
            connect_timeout=1,
            max_attempts=1,
        )
    )

    started = time.monotonic()
    with pytest.raises(StorageConnectionError):
        unreachable.exists("a.txt")
    with pytest.raises(StorageConnectionError):
        list(unreachable.list_keys())
    assert time.monotonic() - started < 5
