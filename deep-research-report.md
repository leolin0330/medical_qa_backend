# medical_qa_backend 帳密登入與 JWT＋Refresh Token 導入計畫

## Executive summary

我已使用已啟用的 GitHub 連接器掃描 `leolin0330/medical_qa_backend` 的核心檔案（`app.py`、`routers/*.py`、`services/*`、`requirements.txt`、`Dockerfile`、`.env.example`、`models/*`、`utils/*`），並根據目前程式碼現況提出一份「可直接落地」的帳密登入導入方案：支援 `register / login / refresh / me / logout`、Access Token 採 JWT、Refresh Token 採旋轉（rotation）＋重放偵測（reuse detection），並提供 Postgres 資料庫 schema 範例、Alembic migration 提示、FastAPI 與 SQLAlchemy 實作片段、Flutter（mobile/web）安全儲存策略、CI/測試建議，以及可直接套入你 repo 的短 patch（含路徑與 diff）。fileciteturn152file0L1-L1

就現況而言，你 repo 已經有一個最小化的 `/auth/login` 與 `/auth/me`，但仍屬「假資料庫」版本（`fake_user_db`），且 `/auth/me` 目前會因為未匯入 `SECRET_KEY/ALGORITHM` 而在執行時報錯；此外 `utils/security.py` 把 JWT secret 寫死為 `"mysecretkey"`，不適合上線。fileciteturn153file0L1-L1 fileciteturn155file0L1-L1

這份計畫的「最小可用里程碑」是：  
把 `fake_user_db` 換成資料庫表（users、refresh_tokens）、補上 refresh 流程與 token rotation，並把目前會大量消耗資源/費用的端點（例如 `/ask`、`/upload`、`/find_papers`、`/news` 等）掛上 `Depends(get_current_user)`，以符合 entity["organization","OWASP","api security top 10"] API4「Unrestricted Resource Consumption」的防護方向（昂貴操作必須要有身分與配額控管）。citeturn1search6turn1search4 fileciteturn152file0L1-L1 fileciteturn156file0L1-L1 fileciteturn162file0L1-L1 fileciteturn161file0L1-L1

---

## 現況盤點與導入缺口

### 目前 repo 已有的登入雛形

- `routers/auth.py` 已提供：
  - `POST /auth/login`：以 `fake_user_db` 查 user 並驗證密碼，登入成功回傳 JWT。fileciteturn153file0L1-L1
  - `GET /auth/me`：用 Bearer token 解析 JWT 的 `sub`，回傳 username。fileciteturn153file0L1-L1  
  但此處直接引用 `SECRET_KEY`、`ALGORITHM`，檔案內未匯入，會導致 runtime error（你本機剛好一路修到能用，但 repo 版本仍是這樣）。fileciteturn153file0L1-L1

- `models/user.py` 目前不是 DB model，而是 Pydantic schema＋假資料庫：  
  `fake_user_db["admin"]["password"] = hash_password("123456")`。fileciteturn154file0L1-L1

- `utils/security.py` 目前把：
  - `SECRET_KEY = "mysecretkey"` 寫死在程式內  
  - `create_access_token()` 用 `datetime.utcnow()` 建 exp  
  這在 production 不建議（secret 必須由環境變數提供；且 token/時間最好用 UTC aware）。fileciteturn155file0L1-L1

### 你的「AI/昂貴端點」目前在哪裡、為什麼更需要 auth

你現在的「AI 問答核心」在 `services/qna.py`，它會呼叫 OpenAI embeddings + chat completions，並回傳 token usage 與 cost。fileciteturn156file0L1-L1  
而 API 入口主要在 `app.py`：

- `POST /ask` 會呼叫 `qna.answer_question()`（general/doc）並回傳 cost。fileciteturn152file0L1-L1
- `POST /upload` 會解析檔案、切段、embedding、寫入 vector store。fileciteturn152file0L1-L1

此外：
- `POST /find_papers` 會呼叫 Semantic Scholar + `gpt-4` 做翻譯與排名（昂貴）。fileciteturn162file0L1-L1
- `GET /news` 可能對 WHO 抓取並選用 OpenAI 翻譯。fileciteturn161file0L1-L1

這類需要 CPU、記憶體、外部請求、以及「按次計價」的模型呼叫端點，若無 auth/配額，很容易落入 OWASP API4「不受限制的資源消耗」風險（費用暴增/DoS）。citeturn1search6turn1search4

---

## 目標架構與設計決策

### JWT 的定位與必要提醒

JWT（JSON Web Token）是把 claims 用緊湊字串表示並可簽章驗證的標準；它**不是加密**，任何人都能 decode payload，所以不要放敏感資料。citeturn0search3turn1search1  
建議只放：`sub`（user_id）、`type`（access）、`exp`、`iat`、`jti` 等最小必要欄位。citeturn0search3turn1search1

### Refresh token rotation 與重放偵測策略

Refresh token rotation 的核心概念是：每次 refresh 都發新 refresh token，舊的立刻失效；如果舊 token 又被拿來用，代表可能被盜用，可視為重放並撤銷整個 session（或整個 grant）。這是 OAuth 安全最佳實務文件明確描述的策略。citeturn4search3turn4search9

### Token 策略比較表

| 策略 | Access Token | Refresh Token | 優點 | 主要風險/代價 | 建議採用情境 |
|---|---|---|---|---|---|
| 純 JWT（無 refresh） | JWT 長效 | 無 | 最簡單 | 長效 JWT 一旦外洩影響大；不好撤銷 | 內部工具、低風險 |
| JWT + refresh（不 rotation） | JWT 短效 | 長效、固定 | 容易實作 | refresh 外洩=長期可續命 | 不建議 |
| JWT + refresh（rotation + reuse detection） | JWT 5–15 分鐘 | 7–30 天；每次 refresh 更新 | 安全性與可用性平衡最好；可偵測重放 | 需要 DB 表與狀態管理 | **本 repo 建議**（AI/醫療類敏感＆昂貴 API）citeturn4search3turn1search4 |

> 存取權限（Authorization）方面，至少要做到「未登入不可呼叫昂貴端點」，因為你目前 `/ask`、`/upload`、`/find_papers` 都會觸發成本與重運算。citeturn1search6turn152file0L1-L1 fileciteturn162file0L1-L1

### Cookie 與跨平台儲存策略

- Mobile（Flutter iOS/Android）：refresh token 建議存 `flutter_secure_storage`（Keychain/Keystore），避免明文落地。
- Web（Flutter Web）：refresh token 建議用 **HttpOnly cookie**（JS 不能讀），降低 XSS 竊取風險；並用 `SameSite` 與 `Secure` 控制跨站送出行為。citeturn3search1turn0search1

若你要讓 web 用 cookie 且跨網域呼叫 API，需要：
- `CORSMiddleware(allow_credentials=True)`  
- 且 `allow_origins` 不能用 `["*"]`（FastAPI 文件明確說明 wildcard 不支援 credentials）。citeturn3search0  
你現在 `app.py` 是 `allow_origins=["*"]`，所以若導入 cookie refresh，必須調整。fileciteturn152file0L1-L1

### Auth flow 圖

```mermaid
sequenceDiagram
  autonumber
  participant C as Client (Flutter)
  participant A as API (FastAPI)
  participant DB as Postgres
  participant AI as OpenAI

  C->>A: POST /auth/register (username,email,password)
  A->>DB: INSERT users(password_hash=bcrypt)
  A-->>C: 201 user

  C->>A: POST /auth/login
  A->>DB: SELECT user by username
  A->>A: verify_password()
  A->>DB: INSERT refresh_tokens(token_hash, expires_at)
  A-->>C: access_token(JWT) + refresh_token(或Set-Cookie)

  C->>A: POST /auth/refresh (cookie/body)
  A->>DB: SELECT refresh_token where not revoked & not expired
  A->>DB: ROTATE: revoke old, insert new
  A-->>C: new access_token + new refresh_token(或Set-Cookie)

  C->>A: POST /ask (Authorization: Bearer access_token)
  A->>A: decode & authz
  A->>AI: embeddings/chat
  A-->>C: answer + usage/cost
```

---

## 資料庫 Schema 與 Alembic 遷移提示

### Postgres schema 範例（概念版）

> 你目前 repo 沒有 DB；本段提供「上線等級」的 users + refresh_tokens 最小集合。

```sql
-- users
CREATE TABLE users (
  id            uuid PRIMARY KEY,
  username      text NOT NULL UNIQUE,
  email         text UNIQUE,
  password_hash text NOT NULL,
  is_active     boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  last_login_at timestamptz
);

-- refresh_tokens（rotation + reuse detection）
CREATE TABLE refresh_tokens (
  id                 uuid PRIMARY KEY,
  user_id            uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash         text NOT NULL UNIQUE,
  issued_at          timestamptz NOT NULL DEFAULT now(),
  expires_at         timestamptz NOT NULL,
  revoked_at         timestamptz,
  replaced_by_id     uuid REFERENCES refresh_tokens(id),
  user_agent         text,
  ip                text
);

CREATE INDEX idx_refresh_tokens_user_id ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_expires_at ON refresh_tokens(expires_at);
```

### Alembic autogenerate 的最少步驟

Alembic 支援用 `alembic revision --autogenerate` 根據 ORM metadata 對比資料庫實際狀態來產生 migration，但必須在 `env.py` 暴露 `target_metadata`。citeturn1search3

最低可行流程：

```bash
pip install alembic
alembic init alembic
# 編輯 alembic.ini：sqlalchemy.url = ${DATABASE_URL}
# 編輯 alembic/env.py：import Base.metadata as target_metadata
alembic revision --autogenerate -m "create users and refresh_tokens"
alembic upgrade head
```

> 注意：autogenerate 產出的 migration 需要人工 review（Alembic 文件也強調會產生「候選 migration」）。citeturn1search3

---

## FastAPI 實作規格與可直接套入的短 patch

### 端點規格與 request/response 範例

> 下面是你要求的固定集合：`/register /login /refresh /me /logout`（皆置於 `/auth/*`）。

#### `POST /auth/register`

Request（JSON）：
```json
{
  "username": "timmy",
  "email": "timmy@example.com",
  "password": "StrongPassw0rd!"
}
```

Response（201）：
```json
{
  "id": "d9b6d7f8-....",
  "username": "timmy",
  "email": "timmy@example.com",
  "created_at": "2026-03-13T12:00:00Z"
}
```

#### `POST /auth/login`

Request（JSON）：
```json
{
  "username": "timmy",
  "password": "StrongPassw0rd!",
  "set_cookie": false
}
```

Response（200；mobile 模式）：
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_in": 900,
  "refresh_token": "<opaque-refresh>"
}
```

Response（200；web 模式，`set_cookie=true`）：
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_in": 900
}
```
並在 header `Set-Cookie` 設定 HttpOnly refresh cookie（見後段 cookie 建議）。citeturn3search1turn0search1

#### `POST /auth/refresh`

- Web：從 HttpOnly cookie 讀 refresh token。citeturn3search1  
- Mobile：從 body 帶 refresh token。

Request（JSON，mobile）：
```json
{ "refresh_token": "<opaque-refresh>", "set_cookie": false }
```

Response（200）：
```json
{
  "access_token": "<new-jwt>",
  "token_type": "bearer",
  "expires_in": 900,
  "refresh_token": "<new-opaque-refresh>"
}
```

Rotation/重放偵測行為依 OAuth 安全最佳實務：舊 refresh token 一旦用過就失效；若被再次提交，視為可能被盜用並撤銷。citeturn4search3turn4search9

#### `GET /auth/me`

Request header：
```
Authorization: Bearer <access_token>
```

Response（200）：
```json
{ "id": "...", "username": "timmy", "email": "...", "is_active": true }
```

#### `POST /auth/logout`

- Web：清除 cookie + revoke refresh token  
- Mobile：revoke 指定 refresh token

Response：
```json
{ "ok": true }
```

---

### 你 repo 當前版本的必要修正點（導入前先掃雷）

- `routers/auth.py` 的 `/me` 會用到 `SECRET_KEY/ALGORITHM`，但並未 import，需修正。fileciteturn153file0L1-L1  
- `utils/security.py` 把 `SECRET_KEY="mysecretkey"` 寫死，必須改為環境變數。fileciteturn155file0L1-L1  
- `app.py` 使用 `load_dotenv()`，但 `requirements.txt` 沒列 `python-dotenv`，乾淨環境會裝不起來。fileciteturn152file0L1-L1 fileciteturn164file0L1-L1

---

### 短 patch（含檔案路徑與 diff）

> 以下 patch 以「最小侵入、直接能跑」為原則：先以同步 SQLAlchemy + Postgres driver（psycopg2）完成；後續中期再視流量改 async。

#### Patch：補齊依賴（`requirements.txt`）

```diff
--- a/requirements.txt
+++ b/requirements.txt
@@
 fastapi
 uvicorn[standard]
+python-dotenv
 python-multipart
 openai
 faiss-cpu
 PyMuPDF
 pdfminer.six
 python-docx
 python-pptx
 moviepy
 pydub
 pillow
 pytesseract
 numpy==1.26.4
 imageio-ffmpeg
 beautifulsoup4
 feedparser
 requests
+
+# auth / db
+python-jose
+passlib[bcrypt]
+# 你在 Windows 實測 passlib + bcrypt 5.x 可能踩雷，建議固定 4.x（中期可再評估）
+bcrypt==4.0.1
+SQLAlchemy>=2.0
+alembic
+psycopg2-binary
```

你 repo 的 `requirements.txt` 目前確實缺 `python-dotenv`、`python-jose`、`passlib`、DB 套件。fileciteturn164file0L1-L1

#### Patch：擴充環境變數樣板（`.env.example`）

```diff
--- a/.env.example
+++ b/.env.example
@@
 OPENAI_API_KEY=YOUR_API_KEY_HERE
 PRICE_WHISPER_PER_MIN=0.006
+
+# Database
+DATABASE_URL=postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/medicalqa
+
+# JWT / Refresh
+JWT_SECRET_KEY=PLEASE_CHANGE_ME_TO_A_LONG_RANDOM_STRING
+JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15
+REFRESH_TOKEN_EXPIRE_DAYS=30
+REFRESH_TOKEN_PEPPER=PLEASE_CHANGE_ME_TOO   # 防 DB 外洩的 second secret
+
+# CORS (comma separated)
+ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:3000
```

你目前 `.env.example` 只有 OpenAI key 與 Whisper 價格。fileciteturn166file0L1-L1

#### Patch：新增 DB 連線（新增檔案 `db.py`）

```diff
--- /dev/null
+++ b/db.py
@@
+import os
+from sqlalchemy import create_engine
+from sqlalchemy.orm import sessionmaker, DeclarativeBase
+
+DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/dev.db")
+
+engine = create_engine(
+    DATABASE_URL,
+    pool_pre_ping=True,
+    future=True,
+)
+
+SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
+
+
+class Base(DeclarativeBase):
+    pass
+
+
+def get_db():
+    db = SessionLocal()
+    try:
+        yield db
+    finally:
+        db.close()
```

#### Patch：新增 SQLAlchemy models（新增檔案 `models/tables.py`）

```diff
--- /dev/null
+++ b/models/tables.py
@@
+from __future__ import annotations
+
+from datetime import datetime, timezone, timedelta
+from uuid import uuid4
+
+from sqlalchemy import (
+    String, Boolean, DateTime, ForeignKey, Text
+)
+from sqlalchemy.orm import Mapped, mapped_column, relationship
+
+from db import Base
+
+
+def utcnow():
+    return datetime.now(timezone.utc)
+
+
+class User(Base):
+    __tablename__ = "users"
+
+    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
+    username: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
+    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
+    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
+    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
+
+    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
+    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
+    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
+
+    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
+
+
+class RefreshToken(Base):
+    __tablename__ = "refresh_tokens"
+
+    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
+    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
+    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
+
+    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
+    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
+    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
+    replaced_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("refresh_tokens.id"))
+
+    user_agent: Mapped[str | None] = mapped_column(String(500))
+    ip: Mapped[str | None] = mapped_column(String(64))
+
+    user = relationship("User", back_populates="refresh_tokens")
```

#### Patch：強化密碼雜湊與 JWT 設定（修改 `utils/security.py`）

bcrypt 的 72 bytes 限制與 work factor 至少 10 的建議，OWASP 在 Password Storage Cheat Sheet 有明確說明。citeturn0search0

```diff
--- a/utils/security.py
+++ b/utils/security.py
@@
-from datetime import datetime, timedelta
-from jose import jwt
-from passlib.context import CryptContext
-
-SECRET_KEY = "mysecretkey"
-ALGORITHM = "HS256"
-ACCESS_TOKEN_EXPIRE_MINUTES = 60
-
-pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
+from __future__ import annotations
+
+import os
+import hashlib
+import secrets
+from datetime import datetime, timedelta, timezone
+from jose import JWTError, jwt
+from passlib.context import CryptContext
+
+JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "DEV-CHANGE-ME")
+ALGORITHM = "HS256"
+ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
+
+REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
+REFRESH_TOKEN_PEPPER = os.getenv("REFRESH_TOKEN_PEPPER", "DEV-PEPPER-CHANGE-ME")
+
+pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
+
+
+def utcnow() -> datetime:
+    return datetime.now(timezone.utc)
@@
 def hash_password(password: str):
     return pwd_context.hash(password)
@@
 def verify_password(plain_password, hashed_password):
     return pwd_context.verify(plain_password, hashed_password)
@@
-def create_access_token(data: dict):
-    to_encode = data.copy()
-
-    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
-    to_encode.update({"exp": expire})
-
-    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
-
-    return encoded_jwt
+def create_access_token(*, subject: str) -> tuple[str, int]:
+    """
+    回傳 (token, expires_in_seconds)
+    JWT 不是加密、是簽章；避免放敏感資料。（FastAPI 文件也提醒 JWT payload 可被讀）citeturn0search3
+    """
+    now = utcnow()
+    exp = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
+    payload = {
+        "sub": subject,
+        "type": "access",
+        "iat": int(now.timestamp()),
+        "exp": int(exp.timestamp()),
+        "jti": secrets.token_hex(16),
+    }
+    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=ALGORITHM)
+    return token, int((exp - now).total_seconds())
+
+
+def decode_access_token(token: str) -> str:
+    payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
+    if payload.get("type") != "access":
+        raise JWTError("not access token")
+    sub = payload.get("sub")
+    if not sub:
+        raise JWTError("missing sub")
+    return str(sub)
+
+
+def new_refresh_token() -> tuple[str, str, datetime]:
+    """
+    產生 refresh token（opaque），並回傳 (raw_token, token_hash, expires_at)
+    """
+    raw = secrets.token_urlsafe(48)
+    token_hash = hash_refresh_token(raw)
+    expires_at = utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
+    return raw, token_hash, expires_at
+
+
+def hash_refresh_token(raw: str) -> str:
+    # pepper + token 做 sha256，避免 DB 外洩直接取得可用 refresh token
+    h = hashlib.sha256()
+    h.update((REFRESH_TOKEN_PEPPER + raw).encode("utf-8"))
+    return h.hexdigest()
```

#### Patch：重寫 auth router（修改 `routers/auth.py`）

> 你目前 router 還在用 `fake_user_db`，而且 `/me` 會引用未 import 的常數。fileciteturn153file0L1-L1  
> 下面 patch 會把它完整升級成 DB 版＋refresh rotation。

```diff
--- a/routers/auth.py
+++ b/routers/auth.py
@@
-from fastapi import APIRouter, HTTPException, Depends
-from fastapi.security import OAuth2PasswordBearer
-from jose import JWTError, jwt
-
-from models.user import UserLogin, fake_user_db
-from utils.security import verify_password, create_access_token
+from __future__ import annotations
+
+from fastapi import APIRouter, HTTPException, Depends, Response, Request
+from fastapi.security import OAuth2PasswordBearer
+from pydantic import BaseModel, EmailStr, Field
+from sqlalchemy.orm import Session
+from jose import JWTError
+
+from db import get_db
+from models.tables import User, RefreshToken
+from utils.security import (
+    verify_password, hash_password,
+    create_access_token, decode_access_token,
+    new_refresh_token, hash_refresh_token, utcnow
+)
 
 router = APIRouter(prefix="/auth", tags=["auth"])
 
 oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")
+
+
+class RegisterIn(BaseModel):
+    username: str = Field(min_length=3, max_length=32)
+    email: EmailStr | None = None
+    password: str = Field(min_length=10, max_length=72)  # bcrypt 72 bytes 限制（OWASP）citeturn0search0
+
+
+class LoginIn(BaseModel):
+    username: str
+    password: str
+    set_cookie: bool = False
+
+
+class RefreshIn(BaseModel):
+    refresh_token: str | None = None
+    set_cookie: bool = False
+
+
+class TokenOut(BaseModel):
+    access_token: str
+    token_type: str = "bearer"
+    expires_in: int
+    refresh_token: str | None = None
 
 
 @router.post("/login")
-def login(user: UserLogin):
-
-    db_user = fake_user_db.get(user.username)
-
-    if not db_user:
-        raise HTTPException(status_code=400, detail="User not found")
-
-    if not verify_password(user.password, db_user["password"]):
-        raise HTTPException(status_code=400, detail="Incorrect password")
-
-    access_token = create_access_token(
-        data={"sub": user.username}
-    )
-
-    return {
-        "access_token": access_token,
-        "token_type": "bearer"
-    }
+def login(payload: LoginIn, resp: Response, req: Request, db: Session = Depends(get_db)) -> TokenOut:
+    user = db.query(User).filter(User.username == payload.username).one_or_none()
+    if not user or not user.is_active:
+        raise HTTPException(status_code=400, detail="User not found or inactive")
+
+    if not verify_password(payload.password, user.password_hash):
+        raise HTTPException(status_code=400, detail="Incorrect password")
+
+    access_token, expires_in = create_access_token(subject=user.id)
+
+    raw_rt, rt_hash, rt_exp = new_refresh_token()
+    rt = RefreshToken(
+        user_id=user.id,
+        token_hash=rt_hash,
+        expires_at=rt_exp,
+        user_agent=req.headers.get("user-agent"),
+        ip=req.client.host if req.client else None,
+    )
+    user.last_login_at = utcnow()
+    user.updated_at = utcnow()
+    db.add(rt)
+    db.commit()
+
+    out = TokenOut(access_token=access_token, expires_in=expires_in)
+
+    if payload.set_cookie:
+        # Web：用 HttpOnly cookie（MDN 建議 HttpOnly + Secure + SameSite 控制）citeturn3search1turn0search1
+        resp.set_cookie(
+            key="refresh_token",
+            value=raw_rt,
+            httponly=True,
+            secure=False,     # 上線務必 True；本機 http 可先 False（localhost 例外行為見 MDN）citeturn3search1
+            samesite="lax",
+            path="/",
+            max_age=int(60 * 60 * 24 * 30),
+        )
+        out.refresh_token = None
+    else:
+        # Mobile：回傳給前端存 secure storage
+        out.refresh_token = raw_rt
+
+    return out
+
+
+@router.post("/register")
+def register(payload: RegisterIn, db: Session = Depends(get_db)):
+    exists = db.query(User).filter(User.username == payload.username).one_or_none()
+    if exists:
+        raise HTTPException(status_code=400, detail="Username already exists")
+
+    if payload.email:
+        e = db.query(User).filter(User.email == payload.email).one_or_none()
+        if e:
+            raise HTTPException(status_code=400, detail="Email already exists")
+
+    u = User(
+        username=payload.username,
+        email=payload.email,
+        password_hash=hash_password(payload.password),
+    )
+    db.add(u)
+    db.commit()
+    return {"id": u.id, "username": u.username, "email": u.email, "created_at": u.created_at}
 
 
 @router.get("/me")
-def get_current_user(token: str = Depends(oauth2_scheme)):
-
-    try:
-        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
-        username = payload.get("sub")
-
-        if username is None:
-            raise HTTPException(status_code=401, detail="Invalid token")
-
-    except JWTError:
-        raise HTTPException(status_code=401, detail="Invalid token")
-
-    return {
-        "username": username
-    }
+def me(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
+    try:
+        user_id = decode_access_token(token)
+    except JWTError:
+        raise HTTPException(status_code=401, detail="Invalid token")
+    user = db.query(User).filter(User.id == user_id).one_or_none()
+    if not user or not user.is_active:
+        raise HTTPException(status_code=401, detail="Invalid token")
+    return {"id": user.id, "username": user.username, "email": user.email, "is_active": user.is_active}
+
+
+@router.post("/refresh")
+def refresh(payload: RefreshIn, resp: Response, req: Request, db: Session = Depends(get_db)) -> TokenOut:
+    raw = payload.refresh_token or req.cookies.get("refresh_token")
+    if not raw:
+        raise HTTPException(status_code=401, detail="Missing refresh token")
+
+    token_hash = hash_refresh_token(raw)
+    rt = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).one_or_none()
+    if not rt:
+        raise HTTPException(status_code=401, detail="Invalid refresh token")
+
+    # 重放偵測：token 已 revoked 或已被替換 -> 視為 replay，撤銷該 user 的有效 refresh tokens（OAuth BCP 建議）citeturn4search3turn4search9
+    if rt.revoked_at is not None or rt.replaced_by_id is not None:
+        db.query(RefreshToken).filter(
+            RefreshToken.user_id == rt.user_id,
+            RefreshToken.revoked_at.is_(None),
+        ).update({"revoked_at": utcnow()})
+        db.commit()
+        raise HTTPException(status_code=401, detail="Refresh token replay detected; session revoked")
+
+    if rt.expires_at <= utcnow():
+        raise HTTPException(status_code=401, detail="Refresh token expired")
+
+    # rotation：發新 refresh token、舊的 revoke 並連結 replaced_by
+    new_raw, new_hash, new_exp = new_refresh_token()
+    new_rt = RefreshToken(
+        user_id=rt.user_id,
+        token_hash=new_hash,
+        expires_at=new_exp,
+        user_agent=req.headers.get("user-agent"),
+        ip=req.client.host if req.client else None,
+    )
+    db.add(new_rt)
+    db.commit()
+
+    rt.revoked_at = utcnow()
+    rt.replaced_by_id = new_rt.id
+    db.add(rt)
+    db.commit()
+
+    access_token, expires_in = create_access_token(subject=rt.user_id)
+    out = TokenOut(access_token=access_token, expires_in=expires_in)
+
+    if payload.set_cookie:
+        resp.set_cookie(
+            key="refresh_token",
+            value=new_raw,
+            httponly=True,
+            secure=False,   # 上線 True
+            samesite="lax",
+            path="/",
+            max_age=int(60 * 60 * 24 * 30),
+        )
+        out.refresh_token = None
+    else:
+        out.refresh_token = new_raw
+    return out
+
+
+@router.post("/logout")
+def logout(payload: RefreshIn, resp: Response, req: Request, db: Session = Depends(get_db)):
+    raw = payload.refresh_token or req.cookies.get("refresh_token")
+    if raw:
+        token_hash = hash_refresh_token(raw)
+        rt = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).one_or_none()
+        if rt and rt.revoked_at is None:
+            rt.revoked_at = utcnow()
+            db.add(rt)
+            db.commit()
+    # 清 cookie（web）
+    resp.delete_cookie("refresh_token", path="/")
+    return {"ok": True}
```

#### Patch：把昂貴端點掛上登入（`app.py` 範例，最小改動）

你目前 `/ask` 與 `/upload` 會觸發 embedding/chat、檔案解析與向量庫寫入。fileciteturn152file0L1-L1 fileciteturn156file0L1-L1  
建議至少先保護這兩條（符合 OWASP API4 的方向）。citeturn1search6

（示意 diff；實際插入位置請以你 `app.py` 內容為準）

```diff
--- a/app.py
+++ b/app.py
@@
-from fastapi import FastAPI, File, UploadFile, HTTPException, Form
+from fastapi import FastAPI, File, UploadFile, HTTPException, Form, Depends
@@
 from routers import auth
+from utils.security import decode_access_token
+from fastapi.security import OAuth2PasswordBearer
+
+oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")
+
+def require_user_id(token: str = Depends(oauth2_scheme)) -> str:
+    return decode_access_token(token)
@@
 async def upload_pdf(
+    user_id: str = Depends(require_user_id),
     request: Request,
     file: UploadFile = File(...),
@@
 async def ask_question(
+    user_id: str = Depends(require_user_id),
     query: Optional[str] = Form(None),
```

> 後續你可以再把 `/find_papers`、`/news` 也加上同樣的 `Depends`（它們也可能觸發 OpenAI 呼叫）。fileciteturn162file0L1-L1 fileciteturn161file0L1-L1

#### Patch：若要讓 Web 用 HttpOnly cookie refresh，必須調整 CORS（`app.py`）

FastAPI 文件明確說明：wildcard `["*"]` 雖可放寬，但**不支援 cookies/Authorization 等 credentials**；若 `allow_credentials=True`，`allow_origins/allow_methods/allow_headers` 也不能用 `["*"]`。citeturn3search0  
你目前是 `allow_origins=["*"]`。fileciteturn152file0L1-L1

---

## Flutter 儲存與自動 refresh 建議

### Mobile（iOS/Android）

- `access_token`：只放記憶體（App 重啟就用 refresh 換新的）  
- `refresh_token`：用 `flutter_secure_storage` 存  
- API 呼叫：每次加 `Authorization: Bearer <access>`  
- 遇到 401：呼叫 `/auth/refresh`（body 帶 refresh），拿到新 access + 新 refresh（rotation），更新 secure storage，再重送原 request

### Web（Flutter Web）

Web 建議：
- refresh token 用 HttpOnly cookie（JS 不可讀），降低 XSS 竊取；MDN 明確說明 `HttpOnly` 能避免 `Document.cookie` 被 JS 讀到。citeturn3search1turn0search6  
- `SameSite=None` 時必須搭配 `Secure`，否則 cookie 會被瀏覽器拒絕（MDN）。citeturn0search1turn3search1  
- 若用 cookie，就要處理 CORS credentials（見上節 FastAPI CORS 限制）。citeturn3search0

> 實務上「Web 用 cookie，Mobile 用 secure storage」是最常見的折衷；兩者可以共用同一組 `/auth/login /auth/refresh`，靠 `set_cookie` 參數決定回傳方式。

---

## 測試、CI、上線檢核與時程

### 測試建議（pytest）

最少要有這幾類 case（因為 refresh rotation 很容易寫錯）：

- register：username/email unique
- login：密碼錯誤、is_active=false
- refresh：
  - 正常 rotation：舊 refresh 用一次後失效、新 refresh 可用
  - reuse detection：用舊 token 再 refresh → 觸發撤銷（OAuth BCP 的重點之一）citeturn4search3turn4search9
- me：access token type/exp 驗證（JWT claim 是標準的一部分）citeturn1search1turn0search3

### CI 建議（GitHub Actions 概念）

- `pip install -r requirements.txt`
- `pytest`
- `alembic upgrade head`（用 ephemeral Postgres service container）
- 安全掃描（中期）：依你之前需求可加 `pip-audit` 或 Dependabot（此處先不展開）

### 密碼與 Token policy 建議（安全基線）

- bcrypt：
  - work factor 至少 10（OWASP）citeturn0search0  
  - 最大長度 72 bytes（OWASP）citeturn0search0  
- access token：
  - 5–15 分鐘（AI/醫療敏感＆昂貴 API 建議偏短；也符合 FastAPI 對 JWT 用途與 exp 概念的敘述）citeturn0search3turn1search4  
- refresh token：
  - 7–30 天；並做 rotation（OAuth BCP）citeturn4search3turn4search9  

### 導入時程（短/中/長）

```mermaid
timeline
  title Auth 導入里程碑
  section 短期
    DB models + Alembic 初始化 : users + refresh_tokens
    完整 /auth/register|login|refresh|me|logout : rotation + reuse detection
    保護 /ask /upload : Depends(require_user)
  section 中期
    Web cookie refresh + CORS allowlist : allow_credentials + SameSite/Secure
    Rate limit / login 防爆破 : IP + username 節流
    usage 記錄 : user_id + cost_usd + endpoint
  section 長期
    Email 驗證 / MFA（選配） : 高風險帳號保護
    RBAC / 多租戶 : 企業化權限
```

### Production readiness checklist（Auth + AI API）

- [ ] `JWT_SECRET_KEY`、`REFRESH_TOKEN_PEPPER` 不可寫死在 repo，必須由環境變數提供（你目前 `mysecretkey` 需移除）fileciteturn155file0L1-L1  
- [ ] 所有昂貴端點（至少 `/ask`、`/upload`、`/find_papers`、`/news`）都有 auth +（中期）rate limit，避免 OWASP API4 風險citeturn1search6turn1search4  
- [ ] refresh token rotation + reuse detection 有測試覆蓋（參照 OAuth BCP 對 rotation 的描述）citeturn4search3turn4search9  
- [ ] bcrypt policy：最少長度、最大 72 bytes、work factor（OWASP）citeturn0search0  
- [ ] Web 若使用 cookie refresh：`HttpOnly + Secure + SameSite` 設定正確（MDN），且 CORS 不使用 wildcard 並允許 credentials（FastAPI）citeturn3search1turn0search1turn3search0  
- [ ] `requirements.txt` 能在乾淨環境安裝並啟動（你目前缺 `python-dotenv` 會直接壞）fileciteturn152file0L1-L1 fileciteturn164file0L1-L1  
- [ ] Alembic migration 可重現（autogenerate 需人工 review，Alembic 文件亦提醒）citeturn1search3  

---

如果你要我「把上述 patches 拆成更小的 PR 順序」（例如 PR1 只修 requirements + env、PR2 加 DB+models、PR3 換 auth router、PR4 保護 /ask /upload、PR5 web cookie/CORS），我也可以直接用你現在 repo 的檔名與路徑幫你排出最安全的合併順序。