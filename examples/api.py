"""用 RustFS 實例提供檔案上傳、下載、刪除的 API。

啟動方式：
    docker compose up --build

啟動後打開 http://localhost:8000/docs 操作 API。

結束後清除容器與資料：
    docker compose down -v
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Response, UploadFile

from s3_kit import DirectoryListing, ObjectNotFoundError, S3Config, S3Provider

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
