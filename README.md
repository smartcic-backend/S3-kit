# S3-kit

S3 儲存 Provider，用同一套 API 操作 AWS S3 及相容服務（例如 RustFS、MinIO）。

S3-kit 只使用標準 S3 API，所有後端差異都由設定傳入。更換儲存服務時只需要改設定，不需要改程式碼。

## 目錄

- [安裝](#安裝)
- [快速開始](#快速開始)
- [連線設定](#連線設定)
- [使用方式](#使用方式)
- [錯誤處理](#錯誤處理)
- [S3 的資料夾概念](#s3-的資料夾概念)
- [範例 API](#範例-api)
- [開發與測試](#開發與測試)

## 安裝

需要 Python 3.11 以上，以及這個 repo 的 GitHub 存取權限。

使用 uv：

```bash
uv add "s3-kit @ git+ssh://git@github.com/smartcic-backend/S3-kit.git"
```

使用 pip：

```bash
pip install "s3-kit @ git+ssh://git@github.com/smartcic-backend/S3-kit.git"
```

以上指令會安裝 `main` 分支的最新版本。要固定版本時，在網址最後加上 `@<commit>`，例如 `...S3-kit.git@612aaf5793dd75418b7c81cbb162fe9b2f970f84`。

## 快速開始

先設定環境變數（完整說明見[連線設定](#連線設定)）：

```env
S3_ENDPOINT_URL=http://rustfs:9000
S3_BUCKET=my-bucket
S3_ACCESS_KEY=your-access-key
S3_SECRET_KEY=your-secret-key
S3_FORCE_PATH_STYLE=true
```

接著建立 provider：

```python
from s3_kit import S3Config, S3Provider

provider = S3Provider(S3Config.from_env())
provider.ensure_bucket()

provider.put_object("hello.txt", b"hello", content_type="text/plain")
print(provider.get_object("hello.txt"))
```

一個 provider 只操作設定中的一個 bucket。需要操作多個 bucket 時，請分別建立 provider。

## 連線設定

| 環境變數 | 必填 | 預設值 | 說明 |
|---|---|---|---|
| `S3_BUCKET` | 是 | | bucket 名稱 |
| `S3_ACCESS_KEY` | 是 | | 存取金鑰 |
| `S3_SECRET_KEY` | 是 | | 私密金鑰 |
| `S3_ENDPOINT_URL` | 否 | 空值 | S3 服務位址，空值代表連線到 AWS S3 |
| `S3_REGION` | 否 | `us-east-1` | 區域 |
| `S3_FORCE_PATH_STYLE` | 否 | `false` | 使用 `endpoint/bucket/key` 形式的網址，`1`、`true`、`yes` 代表開啟 |

缺少必填環境變數時，`S3Config.from_env()` 會拋出 `KeyError`。

| 服務 | `S3_ENDPOINT_URL` | `S3_FORCE_PATH_STYLE` |
|---|---|---|
| RustFS、MinIO 等自架服務 | 服務位址，例如 `http://rustfs:9000` | `true` |
| AWS S3 | 不設定 | 不設定 |

也可以不透過環境變數，直接建立設定：

```python
import os

from s3_kit import S3Config, S3Provider

config = S3Config(
    bucket="my-bucket",
    access_key=os.environ["S3_ACCESS_KEY"],
    secret_key=os.environ["S3_SECRET_KEY"],
    endpoint_url="http://rustfs:9000",
    force_path_style=True,
)
provider = S3Provider(config)
```

> 請勿把真實憑證寫在程式碼或提交到 repo。

### 在 Docker 中連線

把服務和 RustFS 放在同一個 Docker 網路，endpoint 使用服務名稱與容器 port，不需要對外開放 RustFS 的 port：

```yaml
services:
  rustfs:
    image: rustfs/rustfs:1.0.4
    environment:
      RUSTFS_ACCESS_KEY: ${S3_ACCESS_KEY}
      RUSTFS_SECRET_KEY: ${S3_SECRET_KEY}
    volumes:
      - rustfs-data:/data

  my-service:
    build: .
    environment:
      S3_ENDPOINT_URL: http://rustfs:9000
      S3_BUCKET: my-bucket
      S3_ACCESS_KEY: ${S3_ACCESS_KEY}
      S3_SECRET_KEY: ${S3_SECRET_KEY}
      S3_FORCE_PATH_STYLE: "true"
    depends_on:
      - rustfs

volumes:
  rustfs-data:
```

`depends_on` 只保證啟動順序，不保證 RustFS 已經可以連線。完整的健康檢查寫法可參考 [examples/docker-compose.yaml](examples/docker-compose.yaml)。

## 使用方式

以下範例都假設已經建立好 `provider`。

### 上傳與下載小檔案

`put_object` 和 `get_object` 會把整個檔案放進記憶體，適合小檔案。上傳到相同的 key 會直接覆蓋舊檔案。

```python
provider.put_object("images/a.png", b"image-bytes", content_type="image/png")

data = provider.get_object("images/a.png")
```

key 就是檔案在 S3 上的完整路徑，資料夾不需要先建立。請把 key 存進你的資料庫，之後下載和刪除都會用到。

### 上傳與下載大檔案

大檔案請使用串流，不會把整個檔案放進記憶體，上傳時也會自動使用分段上傳。

```python
with open("video.mp4", "rb") as f:
    provider.upload_stream("videos/video.mp4", f, content_type="video/mp4")

with open("copy.mp4", "wb") as f:
    for chunk in provider.download_stream("videos/video.mp4"):
        f.write(chunk)
```

`download_stream` 預設每次讀取 8MB，可用 `chunk_size` 調整。也可以直接轉送成 HTTP 回應，以 FastAPI 為例：

```python
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from s3_kit import ObjectNotFoundError

app = FastAPI()


@app.get("/videos/{name}")
def download_video(name: str) -> StreamingResponse:
    try:
        chunks = provider.download_stream(f"videos/{name}")
    except ObjectNotFoundError as error:
        raise HTTPException(status_code=404, detail="檔案不存在") from error
    return StreamingResponse(chunks)
```

### 取得檔案資訊

```python
info = provider.get_info("videos/video.mp4")

print(info.key)           # 完整路徑：videos/video.mp4
print(info.name)          # 檔名：video.mp4
print(info.size)          # 大小，單位為 bytes
print(info.last_modified) # 修改時間，帶時區的 datetime
print(info.content_type)  # Content-Type
```

只想確認檔案是否存在時，可以使用 `exists`：

```python
if provider.exists("videos/video.mp4"):
    print("檔案存在")
```

### 像 ls 一樣瀏覽資料夾

`list_dir` 只列出一層。`folders` 是相對於該資料夾的名稱，`files` 是 `ObjectInfo`，其中 `key` 是完整路徑。

```python
root = provider.list_dir()
print(root.folders)

videos = provider.list_dir("videos")
for file in videos.files:
    print(file.name, file.size, file.last_modified)
```

### 列出所有檔案

`list_objects` 和 `list_keys` 會列出所有層級，超過 1000 個檔案時也會自動處理分頁。兩者都是迭代器，需要串列時請用 `list()` 包起來。

```python
for info in provider.list_objects(prefix="videos/"):
    print(info.key, info.size)

keys = list(provider.list_keys(prefix="videos/"))
```

`list_objects` 和 `list_dir` 回傳的 `content_type` 一定是 `None`，因為 S3 的列表不提供這個欄位。需要時請用 `get_info` 取得。

### 刪除檔案

```python
provider.delete_object("videos/video.mp4")
```

刪除不存在的 key 不會報錯。

### 產生臨時下載連結

```python
url = provider.presigned_get_url("images/a.png", expires_in=600)
```

連結在 `expires_in` 秒後失效，預設為 3600 秒。拿到連結的人不需要憑證就能下載，請小心分享。

> 連結的網址來自 `S3_ENDPOINT_URL`。如果 endpoint 是 `http://rustfs:9000`，只有同一個 Docker 網路內才連得到，瀏覽器無法開啟。要給 Docker 外部使用時，服務必須用外部也連得到的 endpoint。

## 錯誤處理

檔案不存在時，`get_object`、`download_stream` 和 `get_info` 會拋出 `ObjectNotFoundError`。`download_stream` 會在呼叫時立刻拋出，不會等到開始讀取。

```python
from s3_kit import ObjectNotFoundError

try:
    data = provider.get_object("missing.txt")
except ObjectNotFoundError:
    data = None
```

連線失敗、權限不足等其他錯誤不會被包裝，會直接拋出 boto3 的例外（`botocore.exceptions.ClientError`、`botocore.exceptions.BotoCoreError`）。

## S3 的資料夾概念

S3 沒有真正的資料夾。bucket 是一張平面的對照表，`images/2026/b.png` 是一整串 key，資料夾是 `list_dir` 依照 `/` 分隔 key 後推算出來的效果。

因此使用時要注意：

- 資料夾不用先建立，上傳時直接寫在 key 裡即可。
- 資料夾裡的檔案全部刪除後，資料夾就會消失。
- 查詢不存在的路徑不會報錯，只會回傳空結果。
- 只能依 prefix 查詢。需要依上傳者、時間等條件查詢時，請把 key 和相關資訊存進資料庫。

## 範例 API

[examples/api.py](examples/api.py) 示範如何用 S3-kit 提供檔案 API。需要 Docker，在 `examples` 資料夾執行：

```bash
docker compose up --build
```

啟動後打開 <http://localhost:8000/docs> 就能操作。

| 動作 | API | 說明 |
|---|---|---|
| 上傳 | `POST /files` | 用 `file` 欄位上傳，可用 `path` 參數指定資料夾 |
| 瀏覽資料夾 | `GET /ls` | 用 `path` 參數指定資料夾 |
| 列出所有檔案 | `GET /files` | 可用 `prefix` 參數篩選 |
| 下載 | `GET /files/{key}` | |
| 刪除 | `DELETE /files/{key}` | |

這個 API 沒有登入驗證，也會把整個檔案讀進記憶體，只適合本機試用，只綁定 `127.0.0.1`。

### 自行測試

範例的 RustFS 也開放在 `127.0.0.1:19000`，可以用自己的程式直接連線測試：

```env
S3_ENDPOINT_URL=http://127.0.0.1:19000
S3_BUCKET=my-test
S3_ACCESS_KEY=s3kit-local
S3_SECRET_KEY=s3kit-local-secret
S3_FORCE_PATH_STYLE=true
```

這組帳密是範例的本機預設值，只能用於本機測試。請不要使用 `s3-kit-e2e` bucket，e2e 測試會清空它。

在 `examples` 資料夾清除容器和所有上傳過的檔案：

```bash
docker compose down -v
```

## 開發與測試

安裝開發環境：

```bash
uv sync
```

執行單元測試，用 moto 模擬 S3，不需要 Docker：

```bash
uv run pytest tests/unit
```

執行 e2e 測試前，先依照[範例 API](#範例-api)啟動 RustFS。e2e 測試只使用 `s3-kit-e2e` bucket，每個測試前後都會清空它：

```bash
uv run pytest tests/e2e
```
