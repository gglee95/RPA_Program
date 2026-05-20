from __future__ import annotations

import hashlib
import os
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, RowMapping
from sqlalchemy.exc import IntegrityError


BASE_DIR = Path(__file__).resolve().parent
SECRETS_PATH = BASE_DIR / "secrets.toml"
DASHBOARD_URL = "https://lookerstudio.google.com/embed/reporting/83973585-1aab-4d35-91a6-256780f5835c/page/p_gdb4s295yd"
DEFAULT_SCALE = 95
DASHBOARD_HEIGHT = 1260
DB_SCHEMA = "mangoperf"

app = FastAPI(
    title="Looker Dashboard API",
    description="FastAPI dashboard with Looker Studio and user CRUD",
    version="1.0.0",
)


class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=30)
    email: str = Field(..., min_length=5, max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    full_name: str = Field(..., min_length=1, max_length=60)


class UserCreate(UserBase):
    password: str = Field(..., min_length=4, max_length=100)


class UserUpdate(BaseModel):
    username: str | None = Field(None, min_length=3, max_length=30)
    email: str | None = Field(None, min_length=5, max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    full_name: str | None = Field(None, min_length=1, max_length=60)
    password: str | None = Field(None, min_length=4, max_length=100)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=30)
    password: str = Field(..., min_length=1, max_length=100)


class UserOut(UserBase):
    id: int
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def load_postgres_config() -> dict[str, Any]:
    env_config = {
        "db_host": os.getenv("POSTGRES_DB_HOST"),
        "db_port": os.getenv("POSTGRES_DB_PORT"),
        "db_name": os.getenv("POSTGRES_DB_NAME"),
        "db_username": os.getenv("POSTGRES_DB_USERNAME"),
        "db_password": os.getenv("POSTGRES_DB_PASSWORD"),
    }
    if all(env_config.values()):
        return env_config

    if not SECRETS_PATH.exists():
        raise RuntimeError(f"Secrets file not found: {SECRETS_PATH}")

    with SECRETS_PATH.open("rb") as file:
        secrets = tomllib.load(file)

    config = secrets.get("postgresql_database")
    if not config:
        raise RuntimeError("postgresql_database config not found in secrets.toml")

    return config


def build_database_url() -> str:
    config = load_postgres_config()
    return (
        f"postgresql+psycopg2://{quote_plus(str(config['db_username']))}:"
        f"{quote_plus(str(config['db_password']))}"
        f"@{config['db_host']}:{config['db_port']}/{config['db_name']}"
    )


def get_engine() -> Engine:
    if not hasattr(get_engine, "_engine"):
        get_engine._engine = create_engine(build_database_url(), pool_size=20, max_overflow=0)  # type: ignore[attr-defined]
    return get_engine._engine  # type: ignore[attr-defined]


def init_db() -> None:
    engine = get_engine()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS mangoperf.users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(30) NOT NULL UNIQUE,
                    email VARCHAR(120) NOT NULL UNIQUE,
                    full_name VARCHAR(60) NOT NULL,
                    password_hash VARCHAR(64) NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
                """
            )
        )


def row_to_user(row: RowMapping) -> UserOut:
    return UserOut(
        id=row["id"],
        username=row["username"],
        email=row["email"],
        full_name=row["full_name"],
        created_at=row["created_at"].isoformat(timespec="seconds"),
        updated_at=row["updated_at"].isoformat(timespec="seconds"),
    )


def fetch_user(user_id: int) -> UserOut:
    engine = get_engine()
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT id, username, email, full_name, created_at, updated_at
                FROM mangoperf.users
                WHERE id = :user_id
                """
            ),
            {"user_id": user_id},
        ).mappings().fetchone()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return row_to_user(row)


def ensure_unique_error(exc: IntegrityError) -> None:
    message = str(exc).lower()
    if "username" in message:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    if "email" in message:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unable to save user")


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(build_dashboard_html())


@app.get("/api/users", response_model=list[UserOut])
async def list_users() -> list[UserOut]:
    engine = get_engine()
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT id, username, email, full_name, created_at, updated_at
                FROM mangoperf.users
                ORDER BY id DESC
                """
            )
        ).mappings().fetchall()

    return [row_to_user(row) for row in rows]


@app.get("/api/users/{user_id}", response_model=UserOut)
async def get_user(user_id: int) -> UserOut:
    return fetch_user(user_id)


@app.post("/api/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate) -> UserOut:
    timestamp = datetime.now()
    engine = get_engine()

    try:
        with engine.begin() as connection:
            created_id = int(
                connection.execute(
                    text(
                        """
                        INSERT INTO mangoperf.users (username, email, full_name, password_hash, created_at, updated_at)
                        VALUES (:username, :email, :full_name, :password_hash, :created_at, :updated_at)
                        RETURNING id
                        """
                    ),
                    {
                        "username": payload.username,
                        "email": payload.email,
                        "full_name": payload.full_name,
                        "password_hash": hash_password(payload.password),
                        "created_at": timestamp,
                        "updated_at": timestamp,
                    },
                ).scalar_one()
            )
    except IntegrityError as exc:
        ensure_unique_error(exc)
        raise

    return fetch_user(created_id)


@app.put("/api/users/{user_id}", response_model=UserOut)
async def update_user(user_id: int, payload: UserUpdate) -> UserOut:
    engine = get_engine()
    with engine.begin() as connection:
        current_row = connection.execute(
            text("SELECT * FROM mangoperf.users WHERE id = :user_id"),
            {"user_id": user_id},
        ).mappings().fetchone()

        if current_row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        current: dict[str, Any] = dict(current_row)
        updates = payload.model_dump(exclude_unset=True)
        current["username"] = updates.get("username", current["username"])
        current["email"] = updates.get("email", current["email"])
        current["full_name"] = updates.get("full_name", current["full_name"])
        current["password_hash"] = (
            hash_password(updates["password"]) if "password" in updates else current["password_hash"]
        )
        current["updated_at"] = datetime.now()

        try:
            connection.execute(
                text(
                    """
                    UPDATE mangoperf.users
                    SET username = :username, email = :email, full_name = :full_name,
                        password_hash = :password_hash, updated_at = :updated_at
                    WHERE id = :user_id
                    """
                ),
                {
                    "username": current["username"],
                    "email": current["email"],
                    "full_name": current["full_name"],
                    "password_hash": current["password_hash"],
                    "updated_at": current["updated_at"],
                    "user_id": user_id,
                },
            )
        except IntegrityError as exc:
            ensure_unique_error(exc)
            raise

    return fetch_user(user_id)


@app.delete("/api/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int) -> None:
    fetch_user(user_id)

    engine = get_engine()
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM mangoperf.users WHERE id = :user_id"), {"user_id": user_id})


@app.post("/api/login")
async def login(payload: LoginRequest) -> dict[str, Any]:
    engine = get_engine()
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT id, username, email, full_name, password_hash, created_at, updated_at
                FROM mangoperf.users
                WHERE username = :username
                """
            ),
            {"username": payload.username},
        ).mappings().fetchone()

    if row is None or row["password_hash"] != hash_password(payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    return {
        "message": "Login successful",
        "user": row_to_user(row).model_dump(),
    }


def build_dashboard_html() -> str:
    return f"""
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Looker Dashboard</title>
  <style>
    :root {{
      --bg: #f4efe6;
      --panel: rgba(255, 252, 246, 0.96);
      --border: #d6c3a7;
      --ink: #1f2933;
      --muted: #5c6b73;
      --accent: #b3541e;
      --accent-dark: #7c2d12;
      --success: #20603d;
      --shadow: 0 20px 45px rgba(80, 55, 20, 0.12);
    }}

    * {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      font-family: "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(224, 163, 85, 0.28), transparent 24%),
        radial-gradient(circle at bottom right, rgba(148, 82, 42, 0.2), transparent 28%),
        linear-gradient(135deg, #f7f2e9 0%, #efe2cf 100%);
      min-height: 100vh;
    }}

    .wrap {{
      max-width: 1760px;
      margin: 0 auto;
      padding: 16px 18px 30px;
    }}

    .topbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }}

    .title-block h1 {{
      margin: 0;
      font-size: 2rem;
    }}

    .title-block p {{
      margin: 6px 0 0;
      color: var(--muted);
    }}

    .header-actions {{
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }}

    .scale-box {{
      display: flex;
      gap: 10px;
      align-items: center;
      padding: 10px 14px;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 999px;
      box-shadow: var(--shadow);
    }}

    .card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 14px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }}

    .auth-state {{
      color: var(--success);
      font-weight: 700;
      min-height: 22px;
      margin: 0 0 10px;
    }}

    .meta {{
      color: var(--muted);
      font-size: 0.92rem;
    }}

    form {{
      display: grid;
      gap: 12px;
    }}

    label {{
      font-size: 0.92rem;
      font-weight: 600;
    }}

    input {{
      width: 100%;
      margin-top: 6px;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px 14px;
      font: inherit;
      background: #fffdfa;
      color: var(--ink);
    }}

    button {{
      border: 0;
      border-radius: 999px;
      padding: 11px 18px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}

    .primary {{ background: var(--accent); color: white; }}
    .secondary {{ background: #ead9c3; color: var(--ink); }}

    .notice {{
      min-height: 22px;
      font-size: 0.92rem;
      color: var(--accent-dark);
    }}

    .viewer-card {{
      position: relative;
    }}

    .frame-wrap {{
      width: 100%;
      overflow-x: auto;
      overflow-y: hidden;
      border-radius: 18px;
      position: relative;
    }}

    .frame-stage {{
      display: flex;
      justify-content: center;
      align-items: flex-start;
      width: 100%;
      height: {DASHBOARD_HEIGHT}px;
      overflow: hidden;
      padding: 0 12px;
    }}

    iframe {{
      border: none;
      background: white;
      transform-origin: top left;
      transition: filter 0.25s ease;
    }}

    .viewer-card.is-locked iframe {{
      filter: blur(6px) saturate(0.82) brightness(0.82);
    }}

    .dashboard-lock {{
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
      z-index: 2;
      background:
        linear-gradient(135deg, rgba(28, 34, 40, 0.64), rgba(61, 35, 14, 0.56)),
        radial-gradient(circle at top right, rgba(233, 170, 94, 0.38), transparent 30%);
      backdrop-filter: blur(10px);
    }}

    .dashboard-lock.hidden {{
      display: none;
    }}

    .lock-card {{
      width: min(520px, 100%);
      padding: 32px 28px;
      border-radius: 28px;
      background: rgba(255, 250, 243, 0.92);
      border: 1px solid rgba(214, 195, 167, 0.9);
      box-shadow: 0 28px 50px rgba(27, 20, 10, 0.18);
      text-align: center;
    }}

    .lock-badge {{
      display: inline-flex;
      padding: 8px 14px;
      border-radius: 999px;
      background: #f1e2cd;
      color: #8b4b1f;
      font-size: 0.82rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      margin-bottom: 14px;
    }}

    .lock-card h2 {{
      margin: 0 0 10px;
      font-size: clamp(1.8rem, 3vw, 2.5rem);
      line-height: 1.05;
    }}

    .lock-card p {{
      margin: 0 0 20px;
      color: var(--muted);
      font-size: 1rem;
      line-height: 1.6;
    }}

    .lock-actions {{
      display: flex;
      gap: 10px;
      justify-content: center;
      flex-wrap: wrap;
    }}

    dialog {{
      width: min(440px, calc(100vw - 24px));
      border: none;
      border-radius: 22px;
      padding: 0;
      background: transparent;
    }}

    dialog::backdrop {{
      background: rgba(31, 41, 51, 0.42);
    }}

    .modal-card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 20px;
      box-shadow: var(--shadow);
    }}

    .modal-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 12px;
    }}

    .modal-head h3 {{
      margin: 0;
    }}

    .link-button {{
      padding: 0;
      background: transparent;
      color: var(--muted);
    }}

    .toast {{
      position: fixed;
      right: 24px;
      top: 24px;
      z-index: 30;
      min-width: 280px;
      max-width: 420px;
      padding: 16px 18px;
      border-radius: 18px;
      background: rgba(32, 96, 61, 0.96);
      color: #f4fff7;
      box-shadow: 0 18px 40px rgba(22, 51, 34, 0.24);
      transform: translateY(-12px);
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.25s ease, transform 0.25s ease;
    }}

    .toast.show {{
      opacity: 1;
      transform: translateY(0);
    }}

    .toast strong {{
      display: block;
      margin-bottom: 4px;
      font-size: 0.98rem;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <header class="topbar">
      <div class="title-block">
        <h1>Data Dashboard</h1>
        <p>루커 스튜디오는 로그인 후에만 열립니다.</p>
      </div>

      <div class="header-actions">
        <div class="scale-box">
          <label for="scaleRange">Dashboard Scale</label>
          <input id="scaleRange" type="range" min="60" max="100" step="5" value="{DEFAULT_SCALE}" />
          <span id="scaleLabel">{DEFAULT_SCALE}%</span>
        </div>
        <button class="secondary" type="button" id="reload-frame">Reset Filters</button>
        <button class="secondary" type="button" id="open-signup">회원가입</button>
        <button class="primary" type="button" id="open-login">로그인</button>
      </div>
    </header>

    <main class="card viewer-card is-locked" id="viewer-card">
      <p class="auth-state" id="auth-state"></p>
      <div class="frame-wrap">
        <div class="dashboard-lock" id="dashboard-lock">
          <div class="lock-card">
            <span class="lock-badge">Private Dashboard</span>
            <h2>로그인이 필요합니다</h2>
            <p>대시보드 데이터는 인증된 사용자에게만 공개됩니다. 먼저 로그인한 뒤 루커 스튜디오 화면을 확인해 주세요.</p>
            <div class="lock-actions">
              <button class="primary" type="button" id="overlay-login">로그인하기</button>
              <button class="secondary" type="button" id="overlay-signup">회원가입</button>
            </div>
          </div>
        </div>
        <div class="frame-stage">
          <iframe id="dashboard-frame" src="{DASHBOARD_URL}" allowfullscreen></iframe>
        </div>
      </div>
    </main>
  </div>

  <dialog id="signup-dialog">
    <div class="modal-card">
      <div class="modal-head">
        <h3>회원가입</h3>
        <button class="link-button" type="button" data-close="signup-dialog">닫기</button>
      </div>
      <form id="user-form">
        <label>
          Username
          <input id="username" maxlength="30" required />
        </label>
        <label>
          Full Name
          <input id="full-name" maxlength="60" required />
        </label>
        <label>
          Email
          <input id="email" type="email" maxlength="120" required />
        </label>
        <label>
          Password
          <input id="password" type="password" maxlength="100" required />
        </label>
        <div class="header-actions">
          <button class="primary" type="submit" id="save-user">회원가입</button>
        </div>
      </form>
      <p class="notice" id="user-notice"></p>
    </div>
  </dialog>

  <dialog id="login-dialog">
    <div class="modal-card">
      <div class="modal-head">
        <h3>로그인</h3>
        <button class="link-button" type="button" data-close="login-dialog">닫기</button>
      </div>
      <form id="login-form">
        <label>
          Username
          <input id="login-username" maxlength="30" required />
        </label>
        <label>
          Password
          <input id="login-password" type="password" maxlength="100" required />
        </label>
        <div class="header-actions">
          <button class="primary" type="submit">로그인</button>
        </div>
      </form>
      <p class="notice" id="login-notice"></p>
    </div>
  </dialog>

  <div class="toast" id="success-toast">
    <strong>로그인 성공</strong>
    <span id="success-toast-text">대시보드 접근이 열렸습니다.</span>
  </div>

  <script>
    const userForm = document.getElementById("user-form");
    const usernameInput = document.getElementById("username");
    const fullNameInput = document.getElementById("full-name");
    const emailInput = document.getElementById("email");
    const passwordInput = document.getElementById("password");
    const userNotice = document.getElementById("user-notice");
    const saveUser = document.getElementById("save-user");

    const scaleRange = document.getElementById("scaleRange");
    const scaleLabel = document.getElementById("scaleLabel");
    const dashboardFrame = document.getElementById("dashboard-frame");
    const reloadFrameButton = document.getElementById("reload-frame");
    const viewerCard = document.getElementById("viewer-card");
    const dashboardLock = document.getElementById("dashboard-lock");
    const authState = document.getElementById("auth-state");

    const signupDialog = document.getElementById("signup-dialog");
    const loginDialog = document.getElementById("login-dialog");
    const openSignupButton = document.getElementById("open-signup");
    const openLoginButton = document.getElementById("open-login");
    const overlayLoginButton = document.getElementById("overlay-login");
    const overlaySignupButton = document.getElementById("overlay-signup");
    const loginForm = document.getElementById("login-form");
    const loginUsernameInput = document.getElementById("login-username");
    const loginPasswordInput = document.getElementById("login-password");
    const loginNotice = document.getElementById("login-notice");

    const successToast = document.getElementById("success-toast");
    const successToastText = document.getElementById("success-toast-text");

    let isLoggedIn = false;
    let toastTimer = null;

    function setUserNotice(message) {{
      userNotice.textContent = message;
    }}

    function setLoginNotice(message) {{
      loginNotice.textContent = message;
    }}

    function extractErrorMessage(error, fallbackMessage) {{
      if (!error || !error.detail) {{
        return fallbackMessage;
      }}

      if (typeof error.detail === "string") {{
        return error.detail;
      }}

      if (Array.isArray(error.detail)) {{
        return error.detail
          .map((item) => {{
            const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : "field";
            return `${{field}}: ${{item.msg}}`;
          }})
          .join(" | ");
      }}

      return fallbackMessage;
    }}

    function applyScale() {{
      const scale = Number(scaleRange.value);
      const scaleRatio = scale / 100;
      const innerWidth = Math.round(100 / scaleRatio);
      const innerHeight = Math.round({DASHBOARD_HEIGHT} / scaleRatio);

      scaleLabel.textContent = `${{scale}}%`;
      dashboardFrame.style.width = `${{innerWidth}}%`;
      dashboardFrame.style.height = `${{innerHeight}}px`;
      dashboardFrame.style.transform = `scale(${{scaleRatio}})`;
    }}

    function setDashboardAccess(loggedIn) {{
      isLoggedIn = loggedIn;
      viewerCard.classList.toggle("is-locked", !loggedIn);
      dashboardLock.classList.toggle("hidden", loggedIn);
    }}

    function showSuccessToast(message) {{
      successToastText.textContent = message;
      successToast.classList.add("show");

      if (toastTimer) {{
        window.clearTimeout(toastTimer);
      }}

      toastTimer = window.setTimeout(() => {{
        successToast.classList.remove("show");
      }}, 2600);
    }}

    function reloadFrame() {{
      if (!isLoggedIn) {{
        return;
      }}
      dashboardFrame.src = dashboardFrame.src;
    }}

    function resetUserForm() {{
      userForm.reset();
      passwordInput.required = true;
      saveUser.textContent = "회원가입";
      setUserNotice("");
    }}

    async function submitUserForm(event) {{
      event.preventDefault();

      const payload = {{
        username: usernameInput.value.trim(),
        full_name: fullNameInput.value.trim(),
        email: emailInput.value.trim(),
        password: passwordInput.value.trim()
      }};

      const response = await fetch("/api/users", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify(payload)
      }});

      if (!response.ok) {{
        const error = await response.json().catch(() => ({{ detail: "회원 저장 실패" }}));
        setUserNotice(extractErrorMessage(error, "회원 저장 실패"));
        return;
      }}

      resetUserForm();
      setUserNotice("회원가입이 완료되었습니다.");
      signupDialog.close();
    }}

    async function submitLogin(event) {{
      event.preventDefault();

      const response = await fetch("/api/login", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{
          username: loginUsernameInput.value.trim(),
          password: loginPasswordInput.value
        }})
      }});

      if (!response.ok) {{
        const error = await response.json().catch(() => ({{ detail: "로그인 실패" }}));
        setLoginNotice(extractErrorMessage(error, "로그인 실패"));
        return;
      }}

      const result = await response.json();
      authState.textContent = `로그인 완료: ${{result.user.full_name}} (@${{result.user.username}})`;
      setLoginNotice("");
      setDashboardAccess(true);
      showSuccessToast(`${{result.user.full_name}}님, 대시보드 접근이 열렸습니다.`);
      loginForm.reset();
      loginDialog.close();
    }}

    function openSignup() {{
      resetUserForm();
      signupDialog.showModal();
    }}

    function openLogin() {{
      setLoginNotice("");
      loginDialog.showModal();
    }}

    userForm.addEventListener("submit", submitUserForm);
    scaleRange.addEventListener("input", applyScale);
    reloadFrameButton.addEventListener("click", reloadFrame);
    openSignupButton.addEventListener("click", openSignup);
    openLoginButton.addEventListener("click", openLogin);
    overlayLoginButton.addEventListener("click", openLogin);
    overlaySignupButton.addEventListener("click", openSignup);
    loginForm.addEventListener("submit", submitLogin);

    document.querySelectorAll("[data-close]").forEach((button) => {{
      button.addEventListener("click", () => {{
        document.getElementById(button.dataset.close).close();
      }});
    }});

    applyScale();
    setDashboardAccess(false);
    resetUserForm();
  </script>
</body>
</html>
    """


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("dashboard:app", host="0.0.0.0", port=8000, reload=False)
