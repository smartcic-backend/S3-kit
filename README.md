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

`ensure_bucket()` 會在 bucket 不存在時建立，多個程序同時啟動並呼叫也不會出錯。

一個 provider 只操作設定中的一個 bucket。需要操作多個 bucket 時，請分別建立 provider。

## 連線設定

| 環境變數 | 必填 | 預設值 | 說明 |
|---|---|---|---|
| `S3_BUCKET` | 是 | | bucket 名稱 |
| `S3_ACCESS_KEY` | 否 | 空值 | 存取金鑰，與 `S3_SECRET_KEY` 同時提供或同時省略，見[憑證](#憑證) |
| `S3_SECRET_KEY` | 否 | 空值 | 私密金鑰 |
| `S3_SESSION_TOKEN` | 否 | 空值 | 臨時憑證的 session token，必須搭配金鑰使用 |
| `S3_ENDPOINT_URL` | 否 | 空值 | S3 服務位址，空值代表連線到 AWS S3 |
| `S3_REGION` | 否 | `us-east-1` | 區域 |
| `S3_FORCE_PATH_STYLE` | 否 | `false` | 使用 `endpoint/bucket/key` 形式的網址，`1`、`true`、`yes` 代表開啟 |
| `S3_PUBLIC_ENDPOINT_URL` | 否 | 空值 | 產生預簽連結時使用的位址，空值代表與 `S3_ENDPOINT_URL` 相同，見[產生臨時下載連結](#產生臨時下載連結) |
| `S3_CONNECT_TIMEOUT` | 否 | 空值 | 連線逾時秒數，空值沿用 boto3 預設的 60 秒 |
| `S3_READ_TIMEOUT` | 否 | 空值 | 讀取逾時秒數，空值沿用 boto3 預設的 60 秒 |
| `S3_MAX_ATTEMPTS` | 否 | 空值 | 最多嘗試次數（含第一次），設定時使用 boto3 的 `standard` 重試模式 |
| `S3_VERIFY_SSL` | 否 | `true` | `0`、`false`、`no` 代表不驗證 TLS 憑證 |
| `S3_CA_BUNDLE` | 否 | 空值 | CA bundle 路徑，設定時優先於 `S3_VERIFY_SSL` |

缺少 `S3_BUCKET` 時，`S3Config.from_env()` 會拋出 `KeyError`。只提供一個金鑰、數字格式錯誤或數值超出範圍時，會拋出 `ValueError`。

### 憑證

- 自架服務（RustFS、MinIO 等）請一定要設定 `S3_ACCESS_KEY` 和 `S3_SECRET_KEY`。
- 兩個金鑰都省略時，會改用 boto3 預設的憑證來源，例如 `AWS_ACCESS_KEY_ID` 環境變數、`~/.aws` 設定檔、ECS task role、EKS IRSA、EC2 instance profile。在 AWS 上建議使用這種方式，不需要長期金鑰。
- 本機忘記設定金鑰時，會讀到開發者電腦上的 `~/.aws` 設定，可能意外連到其他帳號。

### 逾時與 TLS

- `S3_READ_TIMEOUT` 是單次 socket 讀取的逾時，不是整個下載的時間上限，串流下載大檔案不會因此中斷。但下載端消費太慢時，仍可能觸發讀取逾時。
- 自架服務使用內部 CA 簽發的憑證時，用 `S3_CA_BUNDLE` 指定 CA bundle。
- `S3_VERIFY_SSL=false` 會關閉憑證驗證，只能用於本機或測試。

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

連結在 `expires_in` 秒後失效，預設為 3600 秒，最長 604800 秒（7 天，SigV4 的上限），超出範圍會拋出 `ValueError`。拿到連結的人不需要憑證就能下載，請小心分享。

指定 `download_name` 時，瀏覽器會用這個檔名下載，而不是在瀏覽器中開啟，支援中文檔名。key 使用 UUID 等不可讀的名稱時很有用：

```python
url = provider.presigned_get_url("files/3f2a9c.pdf", download_name="報告.pdf")
```

連結的網址來自 `S3_PUBLIC_ENDPOINT_URL`，沒設定時使用 `S3_ENDPOINT_URL`。服務透過 Docker 網路連線時，`S3_ENDPOINT_URL` 是 `http://rustfs:9000`，簽出來的連結只有同一個 Docker 網路內才連得到，瀏覽器無法開啟。要把連結交給瀏覽器或外部服務時，把 `S3_PUBLIC_ENDPOINT_URL` 設成外部連得到的位址：

```yaml
services:
  my-service:
    environment:
      S3_ENDPOINT_URL: http://rustfs:9000
      S3_PUBLIC_ENDPOINT_URL: https://s3.example.com
```

- 服務的實際讀寫仍然走 `S3_ENDPOINT_URL`，`S3_PUBLIC_ENDPOINT_URL` 只用來產生連結。產生連結不會發出請求，服務本身不需要連得到對外位址。
- 不能把連結中的網址直接換成對外位址，SigV4 的簽名包含 `Host`，換掉後簽名會失效。
- 對外位址前面若有反向代理，代理必須原樣轉送 `Host` 與路徑，否則簽名驗證會失敗。開啟 `S3_FORCE_PATH_STYLE` 時，連結是 `endpoint/bucket/key` 形式，代理也要轉送 bucket 路徑。
- 服務自己要讀取檔案時，請直接使用 `get_object` 或 `download_stream`，不要產生預簽連結再下載，否則設定了對外位址後，流量會繞到外部。

### 產生臨時上傳表單

讓瀏覽器或其他服務直接上傳到 S3，檔案不需要經過你的服務。S3-kit 使用預簽 POST，可以在簽名中限制檔案大小與類型：

```python
post = provider.presigned_post(
    "images/a.png",
    expires_in=600,
    content_type="image/png",
    max_size=10 * 1024 * 1024,
)
# post.url：上傳網址
# post.fields：上傳時必須原樣送出的表單欄位
```

上傳端用 `multipart/form-data` 對 `post.url` 送出 `post.fields` 的所有欄位，檔案欄位 `file` 必須放在最後。成功時回應 `204`。以瀏覽器為例：

```javascript
const form = new FormData();
for (const [name, value] of Object.entries(post.fields)) {
  form.append(name, value);
}
form.append("file", file);
await fetch(post.url, { method: "POST", body: form });
```

用 `curl` 時，每個欄位都要用 `-F` 帶上：

```bash
curl -F "key=images/a.png" -F "Content-Type=image/png" -F "policy=..." -F "x-amz-signature=..." ... -F "file=@a.png" "<post.url>"
```

簽名的 policy 會限制：

- **key**：只能上傳到指定的 key，改掉 `key` 欄位會被拒絕。
- **檔案大小**：`min_size` 到 `max_size` bytes，預設為 0 到 5 GB（單次 POST 的上限）。
- **Content-Type**：指定 `content_type` 時，上傳的 `Content-Type` 欄位必須相同。
- **有效期限**：`expires_in` 的規則與下載連結相同。
- **欄位**：不能多送 policy 沒列出的欄位。

違反限制時，服務會拒絕上傳並且不存檔。各服務回傳的狀態碼不同（例如 RustFS 回 `400`，AWS 回 `403`），上傳端請以「不是 2xx」判斷失敗。

注意事項：

- key 請由你的服務決定（例如 UUID），不要讓上傳端自己指定，否則可能覆蓋其他檔案。有效期限內同一份表單可以重複上傳，後面的會覆蓋前面的。
- 表單網址同樣來自 `S3_PUBLIC_ENDPOINT_URL`。
- 瀏覽器直接上傳時，S3 服務需要設定 CORS。設定方式依服務而異，請參考各服務的文件。
- 預簽 POST 需要服務支援 POST Object。AWS S3、MinIO 支援，RustFS 1.0.4 已由 e2e 測試確認。更換服務前請先確認，部分 S3 相容服務不支援。

## 錯誤處理

S3-kit 會把 boto3 的例外轉成自己的例外，使用方不需要 import boto3 或解析錯誤代碼。所有例外都繼承 `S3KitError`，原始的 boto3 例外保留在 `__cause__`，方便除錯。

| 例外 | 發生情況 |
|---|---|
| `ObjectNotFoundError` | 指定的物件不存在 |
| `BucketNotFoundError` | 設定的 bucket 不存在 |
| `AccessDeniedError` | 憑證無效或沒有權限 |
| `StorageConnectionError` | 無法連線到 S3 服務、連線逾時，或下載到一半斷線 |
| `S3KitError` | 其他無法歸類的錯誤 |

```python
from s3_kit import ObjectNotFoundError, S3KitError

try:
    data = provider.get_object("missing.txt")
except ObjectNotFoundError:
    data = None
except S3KitError:
    logger.exception("讀取檔案失敗")
    raise
```

- 檔案不存在時，`get_object`、`download_stream` 和 `get_info` 會拋出 `ObjectNotFoundError`，`exists` 會回傳 `False`。`download_stream` 會在呼叫時立刻拋出，不會等到開始讀取。
- bucket 不存在時，會連線到 S3 的操作都會拋出 `BucketNotFoundError`，包括 `exists` 和 `delete_object`，不會被誤當成「檔案不存在」。產生預簽連結不會連線，因此不會檢查 bucket。
- 刪除不存在的 key 不會報錯。
- 參數錯誤（例如 `expires_in` 超出範圍、設定不完整）會拋出 `ValueError`，不屬於 `S3KitError`。

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
| 取得上傳表單 | `POST /presign/upload` | 用 `key` 參數指定路徑，可用 `content_type` 限制檔案類型、`max_size` 限制大小（預設 10 MB），表單 10 分鐘內有效 |
| 取得下載連結 | `GET /presign/download/{key}` | 連結 10 分鐘內有效，下載時使用原本的檔名 |

範例把 `S3_PUBLIC_ENDPOINT_URL` 設成 `http://127.0.0.1:19000`，預簽連結可以直接在本機的瀏覽器或 `curl` 使用。

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

這組帳密是範例的本機預設值，只能用於本機測試。請不要使用 `s3-kit-e2e` bucket，e2e 測試會清空它；也不要建立 `s3-kit-e2e-missing` bucket，e2e 測試需要它不存在。

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

執行 e2e 測試前，先依照[範例 API](#範例-api)啟動 RustFS。e2e 測試只寫入 `s3-kit-e2e` bucket，每個測試前後都會清空它；另外會用不存在的 `s3-kit-e2e-missing` bucket 測試 bucket 不存在的情況，測試前後都會確認它沒有被建立：

```bash
uv run pytest tests/e2e
```
