import io
from datetime import datetime, timezone

import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from s3_kit import ObjectInfo, ObjectNotFoundError, S3Config, S3Provider

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


def test_get_object_keeps_other_errors():
    with mock_aws():
        provider = S3Provider(make_config())

        with pytest.raises(ClientError):
            provider.get_object("a.txt")


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
