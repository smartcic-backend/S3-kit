# 預簽連結的對外 endpoint

## 問題

`presigned_get_url` 使用 `S3_ENDPOINT_URL` 產生連結。依照專案的連線方式，服務透過 Docker 網路連線，endpoint 是 `http://rustfs:9000`，因此產生的連結只有同一個 Docker 網路內才連得到，瀏覽器無法開啟。

README 目前只把這點寫成限制，沒有提供解法。

## 影響

- 預簽連結的主要用途就是交給瀏覽器或外部服務下載，現在在預設部署方式下無法使用。
- 使用方若為了讓連結可用而把 `S3_ENDPOINT_URL` 改成對外位址，服務本身的流量就會繞到外部，違反「不依賴對外開放的 port」的連線方式。
- 之後的預簽上傳連結（見 [02-presigned-upload.md](02-presigned-upload.md)）會遇到相同問題。

## 提案

在 `S3Config` 新增選填欄位 `public_endpoint_url`：

```python
@dataclass(frozen=True, slots=True)
class S3Config:
    ...
    public_endpoint_url: str | None = None
```

| 環境變數 | 必填 | 預設值 | 說明 |
|---|---|---|---|
| `S3_PUBLIC_ENDPOINT_URL` | 否 | 空值 | 產生預簽連結時使用的位址，空值代表與 `S3_ENDPOINT_URL` 相同 |

`S3Provider` 內部建立兩個 client：

- `_client`：使用 `endpoint_url`，負責所有實際請求。
- `_presign_client`：使用 `public_endpoint_url`，只用來產生預簽連結。未設定時直接使用 `_client`。

兩個 client 共用同一份 botocore `Config`（path-style、checksum 設定等）。

產生預簽連結是本機運算，不會發出網路請求，所以服務本身連不到 `public_endpoint_url` 也沒關係。

## 為什麼不用字串替換網址

直接把連結中的 `http://rustfs:9000` 換成對外位址行不通。SigV4 簽名包含 `Host`，換掉 host 後簽名會失效，所以必須用對外位址重新簽名。

## 設計原則檢查

- 只使用標準 S3 的預簽機制。
- 差異完全由設定處理，沒有任何後端判斷。

## 注意事項

- 對外位址前面若有反向代理，代理必須原樣轉送 `Host` 與路徑，否則簽名驗證會失敗。這點要寫進 README。
- 開啟 `force_path_style` 時，對外連結也會是 `endpoint/bucket/key` 形式，代理需要轉送 bucket 路徑。

## 測試

- 單元測試：設定 `public_endpoint_url` 後，連結以對外位址開頭；未設定時維持使用 `endpoint_url`。
- 單元測試：`from_env` 讀取 `S3_PUBLIC_ENDPOINT_URL`，空值視為未設定。
- e2e：`endpoint_url` 與 `public_endpoint_url` 設成兩個都能連到 RustFS 的位址（例如 `127.0.0.1:19000` 與 `localhost:19000`），確認用對外位址產生的連結可以下載。

## 待確認事項

- 欄位名稱用 `public_endpoint_url` 還是 `presign_endpoint_url`。
- 範例的 `docker-compose.yaml` 是否要設定 `S3_PUBLIC_ENDPOINT_URL=http://127.0.0.1:19000`，讓範例 API 也能示範預簽連結。
