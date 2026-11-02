import base64
import io
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import boto3
import pytest
from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
    ReadTimeoutError,
)
from moto import mock_aws

from s3_kit import (
    AccessDeniedError,
    BucketNotFoundError,
    ObjectInfo,
    ObjectNotFoundError,
    PresignedPost,
    S3Config,
    S3KitError,
    S3Provider,
    StorageConnectionError,
)

BUCKET = "test-bucket"
MB = 1024 * 1024


class NonSeekableStream:
    """只有 read 的串流，模擬無法回頭讀取的來源。"""

    def __init__(self, data: bytes) -> None:
        self._buffer = io.BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)


def make_config(**overrides) -> S3Config:
    values = {"bucket": BUCKET, "access_key": "test", "secret_key": "test"}
    return S3Config(**{**values, **overrides})


def raise_client_error(code: str):
    def raise_error(**_):
        raise ClientError({"Error": {"Code": code}}, "operation")

    return raise_error


@pytest.fixture
def provider():
    with mock_aws():
        provider = S3Provider(make_config())
        provider.ensure_bucket()
        yield provider


def test_ensure_bucket_can_run_twice(provider):
    provider.ensure_bucket()

    provider.put_object("a.txt", b"hello")
    assert provider.exists("a.txt")


def test_ensure_bucket_supports_other_regions():
    with mock_aws():
        provider = S3Provider(make_config(region="ap-northeast-1"))
        provider.ensure_bucket()

        provider.put_object("a.txt", b"hello")
        assert provider.get_object("a.txt") == b"hello"


def test_ensure_bucket_accepts_bucket_created_concurrently(provider, monkeypatch):
    # 模擬檢查時 bucket 還不存在，建立時已被其他程序建立
    monkeypatch.setattr(provider._client, "head_bucket", raise_client_error("404"))
    monkeypatch.setattr(
        provider._client,
        "create_bucket",
        raise_client_error("BucketAlreadyOwnedByYou"),
    )

    provider.ensure_bucket()


def test_ensure_bucket_raises_when_bucket_owned_by_others(provider, monkeypatch):
    monkeypatch.setattr(provider._client, "head_bucket", raise_client_error("404"))
    monkeypatch.setattr(
        provider._client, "create_bucket", raise_client_error("BucketAlreadyExists")
    )

    with pytest.raises(S3KitError) as info:
        provider.ensure_bucket()

    assert isinstance(info.value.__cause__, ClientError)


def test_ensure_bucket_does_not_create_bucket_when_access_denied(provider, monkeypatch):
    def fail_create_bucket(**_):
        pytest.fail("沒有權限時不應嘗試建立 bucket")

    monkeypatch.setattr(provider._client, "head_bucket", raise_client_error("403"))
    monkeypatch.setattr(provider._client, "create_bucket", fail_create_bucket)

    with pytest.raises(AccessDeniedError):
        provider.ensure_bucket()


def test_provider_does_not_use_default_session(monkeypatch):
    monkeypatch.setattr(boto3, "DEFAULT_SESSION", None)

    with mock_aws():
        S3Provider(make_config())

    assert boto3.DEFAULT_SESSION is None


def test_put_and_get_object(provider):
    provider.put_object("a/b.txt", b"hello")

    assert provider.get_object("a/b.txt") == b"hello"


def test_put_object_overwrites_existing_key(provider):
    provider.put_object("a.txt", b"old")
    provider.put_object("a.txt", b"new")

    assert provider.get_object("a.txt") == b"new"


def test_get_object_raises_when_missing(provider):
    with pytest.raises(ObjectNotFoundError, match="missing.txt"):
        provider.get_object("missing.txt")


def test_bucket_missing_raises_bucket_not_found():
    with mock_aws():
        provider = S3Provider(make_config())

        with pytest.raises(BucketNotFoundError, match=BUCKET):
            provider.get_object("a.txt")
        with pytest.raises(BucketNotFoundError):
            provider.download_stream("a.txt")
        with pytest.raises(BucketNotFoundError):
            provider.get_info("a.txt")
        with pytest.raises(BucketNotFoundError):
            provider.exists("a.txt")


def test_exists(provider):
    provider.put_object("a.txt", b"hello")

    assert provider.exists("a.txt") is True
    assert provider.exists("missing.txt") is False


def test_delete_object(provider):
    provider.put_object("a.txt", b"hello")

    provider.delete_object("a.txt")

    assert provider.exists("a.txt") is False


def test_delete_object_ignores_missing_key(provider):
    provider.delete_object("missing.txt")


def test_upload_stream_small_file(provider):
    provider.upload_stream("a.txt", io.BytesIO(b"hello"), content_type="text/plain")

    assert provider.get_object("a.txt") == b"hello"
    assert provider.get_info("a.txt").content_type == "text/plain"


def test_upload_stream_uses_multipart_for_large_file(provider):
    data = b"a" * (9 * MB)

    provider.upload_stream("large.bin", io.BytesIO(data))

    assert provider.get_object("large.bin") == data


def test_upload_stream_accepts_non_seekable_stream(provider):
    data = b"a" * (9 * MB)

    provider.upload_stream("large.bin", NonSeekableStream(data))

    assert provider.get_object("large.bin") == data


def test_download_stream_returns_chunks(provider):
    provider.put_object("a.bin", b"0123456789")

    chunks = list(provider.download_stream("a.bin", chunk_size=4))

    assert chunks == [b"0123", b"4567", b"89"]


def test_download_stream_raises_before_iteration_when_missing(provider):
    with pytest.raises(ObjectNotFoundError, match="missing.bin"):
        provider.download_stream("missing.bin")


def test_get_info(provider):
    provider.put_object("a/b.txt", b"hello", content_type="text/plain")

    info = provider.get_info("a/b.txt")

    assert info.key == "a/b.txt"
    assert info.name == "b.txt"
    assert info.size == 5
    assert info.content_type == "text/plain"
    assert isinstance(info.last_modified, datetime)


def test_get_info_raises_when_missing(provider):
    with pytest.raises(ObjectNotFoundError, match="missing.txt"):
        provider.get_info("missing.txt")


@pytest.mark.parametrize(
    ("key", "name"),
    [("a.txt", "a.txt"), ("a/b.txt", "b.txt"), ("a/b/c.txt", "c.txt")],
)
def test_object_info_name(key, name):
    info = ObjectInfo(key=key, size=0, last_modified=datetime.now(timezone.utc))

    assert info.name == name


def test_list_objects_includes_info(provider):
    provider.put_object("a/b.txt", b"hello", content_type="text/plain")

    [info] = provider.list_objects()

    assert info.key == "a/b.txt"
    assert info.size == 5
    assert isinstance(info.last_modified, datetime)
    assert info.content_type is None


def test_list_keys_is_recursive(provider):
    provider.put_object("a/b/c.txt", b"")
    provider.put_object("a/d.txt", b"")
    provider.put_object("e.txt", b"")

    assert sorted(provider.list_keys()) == ["a/b/c.txt", "a/d.txt", "e.txt"]


def test_list_keys_filters_by_prefix(provider):
    provider.put_object("a/b.txt", b"")
    provider.put_object("c/d.txt", b"")

    assert list(provider.list_keys(prefix="a/")) == ["a/b.txt"]


def test_list_keys_handles_multiple_pages(provider):
    for index in range(1001):
        provider.put_object(f"{index:04}.txt", b"")

    assert len(list(provider.list_keys())) == 1001


def test_list_dir_lists_root(provider):
    provider.put_object("images/a.png", b"")
    provider.put_object("images/2026/b.png", b"")
    provider.put_object("root.txt", b"hello")

    listing = provider.list_dir()

    assert listing.folders == ["images/"]
    assert [info.key for info in listing.files] == ["root.txt"]
    assert listing.files[0].size == 5


@pytest.mark.parametrize("path", ["images", "images/", "/images/"])
def test_list_dir_lists_one_level(provider, path):
    provider.put_object("images/a.png", b"")
    provider.put_object("images/2026/b.png", b"")

    listing = provider.list_dir(path)

    assert listing.folders == ["2026/"]
    assert [info.key for info in listing.files] == ["images/a.png"]
    assert listing.files[0].name == "a.png"


def test_list_dir_does_not_match_similar_prefix(provider):
    provider.put_object("images/a.png", b"")
    provider.put_object("images-old/b.png", b"")

    listing = provider.list_dir("images")

    assert [info.key for info in listing.files] == ["images/a.png"]


def test_list_dir_skips_folder_placeholder(provider):
    provider.put_object("images/", b"")
    provider.put_object("images/a.png", b"")

    listing = provider.list_dir("images")

    assert [info.key for info in listing.files] == ["images/a.png"]


def test_list_dir_returns_empty_for_missing_path(provider):
    listing = provider.list_dir("missing")

    assert listing.folders == []
    assert listing.files == []


def test_presigned_get_url_uses_path_style():
    with mock_aws():
        provider = S3Provider(
            make_config(endpoint_url="http://localhost:9000", force_path_style=True)
        )

        url = provider.presigned_get_url("a/b.txt", expires_in=60)

    assert url.startswith(f"http://localhost:9000/{BUCKET}/a/b.txt?")
    assert "X-Amz-Expires=60" in url
    assert "X-Amz-Signature=" in url


def test_presigned_get_url_uses_public_endpoint():
    with mock_aws():
        provider = S3Provider(
            make_config(
                public_endpoint_url="http://public.example:9000", force_path_style=True
            )
        )
        # 實際請求仍走 endpoint_url（moto 模擬的 AWS），不會連到對外位址
        provider.ensure_bucket()
        provider.put_object("a.txt", b"hello")

        url = provider.presigned_get_url("a/b.txt", expires_in=60)

        assert provider.get_object("a.txt") == b"hello"
    assert url.startswith(f"http://public.example:9000/{BUCKET}/a/b.txt?")
    assert "X-Amz-Signature=" in url


def test_presigned_get_url_accepts_max_expires_in(provider):
    url = provider.presigned_get_url("a.txt", expires_in=7 * 24 * 60 * 60)

    assert "X-Amz-Expires=604800" in url


@pytest.mark.parametrize("expires_in", [0, -1, 7 * 24 * 60 * 60 + 1])
def test_presigned_get_url_rejects_invalid_expires_in(provider, expires_in):
    with pytest.raises(ValueError, match="expires_in"):
        provider.presigned_get_url("a.txt", expires_in=expires_in)


def query_params(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def test_presigned_get_url_sets_download_name(provider):
    url = provider.presigned_get_url("a/uuid.pdf", download_name="報告 1.pdf")

    assert query_params(url)["response-content-disposition"] == [
        "attachment; filename*=UTF-8''%E5%A0%B1%E5%91%8A%201.pdf"
    ]


def test_presigned_get_url_without_download_name(provider):
    url = provider.presigned_get_url("a.txt")

    assert "response-content-disposition" not in query_params(url)


def decode_policy(post: PresignedPost) -> dict:
    return json.loads(base64.b64decode(post.fields["policy"]))


def test_presigned_post(provider):
    post = provider.presigned_post(
        "a/b.txt", expires_in=60, content_type="text/plain", max_size=10, min_size=1
    )
    policy = decode_policy(post)

    assert post.fields["key"] == "a/b.txt"
    assert post.fields["Content-Type"] == "text/plain"
    assert ["content-length-range", 1, 10] in policy["conditions"]
    assert {"Content-Type": "text/plain"} in policy["conditions"]
    assert {"key": "a/b.txt"} in policy["conditions"]
    assert {"bucket": BUCKET} in policy["conditions"]
    expiration = datetime.strptime(policy["expiration"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    assert 0 < (expiration - datetime.now(timezone.utc)).total_seconds() <= 60


def test_presigned_post_defaults(provider):
    post = provider.presigned_post("a.txt")
    policy = decode_policy(post)

    assert "Content-Type" not in post.fields
    assert ["content-length-range", 0, 5 * 1024 * 1024 * 1024] in policy["conditions"]
    assert not any(
        isinstance(condition, dict) and "Content-Type" in condition
        for condition in policy["conditions"]
    )


def test_presigned_post_uses_public_endpoint():
    provider = S3Provider(
        make_config(
            endpoint_url="http://rustfs:9000",
            public_endpoint_url="http://public.example:9000",
            force_path_style=True,
        )
    )

    post = provider.presigned_post("a.txt")

    assert post.url == f"http://public.example:9000/{BUCKET}"


@pytest.mark.parametrize("expires_in", [0, 7 * 24 * 60 * 60 + 1])
def test_presigned_post_rejects_invalid_expires_in(provider, expires_in):
    with pytest.raises(ValueError, match="expires_in"):
        provider.presigned_post("a.txt", expires_in=expires_in)


@pytest.mark.parametrize(
    "sizes",
    [
        {"min_size": -1},
        {"min_size": 11, "max_size": 10},
        {"max_size": -1},
        {"max_size": 5 * 1024 * 1024 * 1024 + 1},
    ],
)
def test_presigned_post_rejects_invalid_sizes(provider, sizes):
    with pytest.raises(ValueError, match="min_size"):
        provider.presigned_post("a.txt", **sizes)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("NoSuchKey", ObjectNotFoundError),
        ("NoSuchBucket", BucketNotFoundError),
        ("AccessDenied", AccessDeniedError),
        ("InvalidAccessKeyId", AccessDeniedError),
        ("SignatureDoesNotMatch", AccessDeniedError),
        ("ExpiredToken", AccessDeniedError),
        ("InvalidToken", AccessDeniedError),
        ("RequestTimeTooSkewed", AccessDeniedError),
        ("403", AccessDeniedError),
        ("InternalError", S3KitError),
    ],
)
def test_client_errors_are_translated(provider, monkeypatch, code, expected):
    monkeypatch.setattr(provider._client, "get_object", raise_client_error(code))

    with pytest.raises(expected) as info:
        provider.get_object("a.txt")

    assert type(info.value) is expected
    assert isinstance(info.value.__cause__, ClientError)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (EndpointConnectionError(endpoint_url="http://s3"), StorageConnectionError),
        (ConnectTimeoutError(endpoint_url="http://s3"), StorageConnectionError),
        (ReadTimeoutError(endpoint_url="http://s3"), StorageConnectionError),
        (NoCredentialsError(), AccessDeniedError),
    ],
)
def test_botocore_errors_are_translated(provider, monkeypatch, error, expected):
    def raise_error(**_):
        raise error

    monkeypatch.setattr(provider._client, "list_objects_v2", raise_error)

    with pytest.raises(expected) as info:
        list(provider.list_keys())

    assert type(info.value) is expected
    assert info.value.__cause__ is error


def test_download_stream_translates_errors_during_iteration(provider, monkeypatch):
    class BrokenBody:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def iter_chunks(self, _chunk_size):
            yield b"first"
            raise ReadTimeoutError(endpoint_url="http://s3")

    monkeypatch.setattr(provider, "_open_object", lambda _key: BrokenBody())
    chunks = provider.download_stream("a.txt")

    assert next(chunks) == b"first"
    with pytest.raises(StorageConnectionError):
        next(chunks)


def test_upload_stream_translates_wrapped_client_error(provider, monkeypatch):
    # upload_fileobj 會把 ClientError 包成 S3UploadFailedError
    def raise_upload_failed(*_, **__):
        try:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "PutObject")
        except ClientError:
            raise S3UploadFailedError("Failed to upload")

    monkeypatch.setattr(provider._client, "upload_fileobj", raise_upload_failed)

    with pytest.raises(AccessDeniedError):
        provider.upload_stream("a.txt", io.BytesIO(b"hello"))


def test_client_uses_connection_settings():
    provider = S3Provider(
        make_config(connect_timeout=2, read_timeout=5, max_attempts=3, verify=False)
    )

    config = provider._client.meta.config
    assert config.connect_timeout == 2
    assert config.read_timeout == 5
    # max_attempts 含第一次請求，對應 botocore 的 total_max_attempts
    assert config.retries == {"total_max_attempts": 3, "mode": "standard"}
    assert provider._client._endpoint.http_session._verify is False


def test_client_keeps_botocore_defaults():
    provider = S3Provider(make_config())

    config = provider._client.meta.config
    assert config.connect_timeout == 60
    assert config.read_timeout == 60
    assert provider._client._endpoint.http_session._verify is True


def test_client_uses_ca_bundle():
    provider = S3Provider(make_config(verify="/etc/ssl/internal-ca.pem"))

    assert provider._client._endpoint.http_session._verify == "/etc/ssl/internal-ca.pem"


def test_provider_uses_default_credentials_when_keys_omitted(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "env-access")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "env-secret")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)

    provider = S3Provider(S3Config(bucket=BUCKET))

    url = provider.presigned_get_url("a.txt")
    assert query_params(url)["X-Amz-Credential"][0].startswith("env-access/")


def test_provider_uses_session_token():
    provider = S3Provider(make_config(session_token="my-token"))

    url = provider.presigned_get_url("a.txt")
    assert query_params(url)["X-Amz-Security-Token"] == ["my-token"]
