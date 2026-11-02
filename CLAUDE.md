# S3-kit

## 專案目的

S3-kit 是一個 S3 儲存 Provider，用同一套 API 操作 AWS S3 及相容服務（例如 MinIO、RustFS）。

使用方只需要安裝這個套件並提供連線設定，不需要知道背後實際使用哪一種 S3 服務。更換儲存服務時，應該只需要改設定，不需要改程式碼，讓專案的儲存方案保持彈性。

## 設計原則

- **不綁定特定後端**：程式碼只依賴標準 S3 API，不針對任何一種 S3 服務撰寫專屬邏輯。
- **只使用通用套件**：透過通用的 S3 client 套件連線，不引入特定服務的專屬 SDK（例如 MinIO SDK）。
- **不使用專屬功能**：不使用只有特定服務才支援的 API 或管理介面。
- **差異由設定處理**：後端之間的差異（endpoint、region、憑證、path-style 等）一律透過設定傳入，不寫死在程式碼中，也不用服務名稱做條件判斷。
- **憑證不進版控**：存取金鑰等機敏資訊不得寫死在程式碼或提交到 repo。唯一的例外是 `examples/docker-compose.yaml` 和 `tests/e2e/conftest.py` 的本機預設值，它們只用於本機範例與 e2e 測試的 RustFS，不得用於其他環境。

新增功能時，先確認它屬於標準 S3 API。如果某個功能只有部分後端支援，要先討論再實作。

新的後端不需要新增子類別或專屬模組，只要提供一組對應的 `S3Config`。

## 技術選擇

- 語言：Python 3.11 以上
- S3 client：boto3
- 套件管理：uv
- 目前使用的 S3 服務：RustFS

## 專案結構

- `src/s3_kit/config.py`：連線設定 `S3Config`
- `src/s3_kit/provider.py`：通用實作 `S3Provider`
- `src/s3_kit/exceptions.py`：對外例外，避免使用方依賴 boto3 的例外型別
- `examples/api.py`：用設定建立 RustFS 實例，並提供檔案上傳、下載、刪除的範例 API
- `examples/docker-compose.yaml`、`examples/Dockerfile`：用 Docker 啟動 RustFS 與範例 API
- `.env.example`：環境變數範本，實際的 `.env` 不進版控
- `tests/unit/`：單元測試，用 moto 模擬 S3，不需要 Docker
- `tests/e2e/`：端對端測試，連線到範例的 RustFS，只寫入 `s3-kit-e2e` bucket；另外使用不存在的 `s3-kit-e2e-missing` bucket 測試 bucket 不存在的情況，測試不得建立它；測試不負責啟動或關閉容器

## 測試

執行單元測試：

```bash
uv run pytest tests/unit
```

e2e 測試的目的是盡可能找出問題，除了正常流程，也要涵蓋錯誤情況（物件或 bucket 不存在、權限錯誤、連線失敗、違反預簽條件等），並驗證錯誤沒有留下副作用（例如被拒絕的上傳沒有存檔）。

執行 e2e 測試前，先啟動範例的 RustFS（見「連線方式」）。e2e 測試會在每個測試前後清空 `s3-kit-e2e` bucket，並確認 `s3-kit-e2e-missing` bucket 不存在：

```bash
uv run pytest tests/e2e
```

## 連線方式

S3 服務以 Docker 容器運行，使用 S3-kit 的服務透過 Docker 網路連線，endpoint 使用服務名稱與容器 port（例如 `http://rustfs:9000`），不依賴對外開放的 port。

範例的 RustFS 另外開放在 `127.0.0.1:19000`，只供 e2e 測試與本機自行測試使用。

在 `examples` 資料夾啟動 RustFS 與範例 API，啟動後打開 `http://localhost:8000/docs` 操作：

```bash
docker compose up --build
```

範例 API 沒有登入驗證，只綁定 `127.0.0.1`，FastAPI 等範例依賴放在 `example` extra，不得加入核心依賴。

在 `examples` 資料夾清除範例的容器與資料：

```bash
docker compose down -v
```

## 開發順序

1. 先完成通用的 `S3Provider`。
2. 再用設定建立 RustFS 實例，確認實際可用。

## 待決定事項

以下項目尚未決定，請先與維護者確認，不要自行假設：

- 套件發佈方式
- CI

## 文件語言

專案文件使用繁體中文。
