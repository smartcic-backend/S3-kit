"""用 RustFS 實例提供檔案上傳、下載、刪除的 API。

啟動方式（在 examples 資料夾執行）：
    docker compose up --build

啟動後打開 http://localhost:8000/docs 操作 API。

結束後清除容器與資料：
    docker compose down -v
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Response, UploadFile

from s3_kit import (
    DirectoryListing,
    ObjectNotFoundError,
    PresignedPost,
    S3Config,
    S3Provider,
)

storage = S3Provider(S3Config.from_env())


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    storage.ensure_bucket()
    yield


app = FastAPI(title="S3-kit RustFS 範例", lifespan=lifespan)


@app.get("/files")
def list_files(prefix: str = "") -> list[str]:
    return list(storage.list_keys(prefix=prefix))


@app.get("/ls")
def list_directory(path: str = "") -> DirectoryListing:
    return storage.list_dir(path)


@app.post("/files", status_code=201)
def upload_file(file: UploadFile, path: str = "") -> dict[str, str]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少檔名")
    key = "/".join(part for part in (path.strip("/"), file.filename) if part)
    storage.put_object(key, file.file.read(), content_type=file.content_type)
    return {"key": key}


@app.get("/files/{key:path}")
def download_file(key: str) -> Response:
    try:
        data = storage.get_object(key)
    except ObjectNotFoundError as error:
        raise HTTPException(status_code=404, detail="檔案不存在") from error

    filename = quote(key.rsplit("/", 1)[-1])
    return Response(
        data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@app.delete("/files/{key:path}", status_code=204)
def delete_file(key: str) -> None:
    if not storage.exists(key):
        raise HTTPException(status_code=404, detail="檔案不存在")
    storage.delete_object(key)


@app.post("/presign/upload")
def presign_upload(
    key: str, content_type: str | None = None, max_size: int = 10 * 1024 * 1024
) -> PresignedPost:
    try:
        return storage.presigned_post(
            key, expires_in=600, content_type=content_type, max_size=max_size
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/presign/download/{key:path}")
def presign_download(key: str) -> dict[str, str]:
    if not storage.exists(key):
        raise HTTPException(status_code=404, detail="檔案不存在")
    url = storage.presigned_get_url(
        key, expires_in=600, download_name=key.rsplit("/", 1)[-1]
    )
    return {"url": url}
