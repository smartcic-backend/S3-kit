import hashlib
import io
import urllib.request
from datetime import datetime

import pytest

from s3_kit import ObjectNotFoundError

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
