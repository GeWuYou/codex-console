"""Outlook 浏览器注册作业。"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import secrets
import string
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional
from urllib.parse import parse_qs, quote, urlencode
from urllib.request import ProxyHandler, Request, build_opener

from ...config.constants import OUTLOOK_REGISTER_DEFAULTS, generate_random_user_info


logger = logging.getLogger(__name__)

MS_AUTHORIZE_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MS_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"


def _generate_strong_password(length: int = 16) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%^&*"

    while True:
        password = "".join(secrets.choice(chars) for _ in range(length))
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
            and any(c in "!@#$%^&*" for c in password)
        ):
            return password


def _random_email_local_part(length: int) -> str:
    first_char = random.choice(string.ascii_lowercase)
    other_chars = []
    for _ in range(length - 1):
        if random.random() < 0.07:
            other_chars.append(random.choice(string.digits))
        else:
            other_chars.append(random.choice(string.ascii_lowercase))
    return first_char + "".join(other_chars)


def _generate_code_verifier(length: int = 128) -> str:
    alphabet = string.ascii_letters + string.digits + "-._~"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _generate_code_challenge(code_verifier: str) -> str:
    sha256_hash = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(sha256_hash).decode("ascii").rstrip("=")


def _exchange_oauth_token(token_data: Dict[str, str], proxy_url: Optional[str], timeout: int = 30) -> Dict[str, object]:
    payload = urlencode(token_data).encode("utf-8")
    request = Request(
        MS_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    opener = build_opener(ProxyHandler({"http": proxy_url, "https": proxy_url}) if proxy_url else ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


@dataclass
class OutlookRegistrationResult:
    """Outlook 注册结果。"""

    success: bool
    email: str = ""
    password: str = ""
    refresh_token: str = ""
    access_token: str = ""
    expires_at: Optional[datetime] = None
    error_message: str = ""
    metadata: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "success": self.success,
            "email": self.email,
            "password": self.password,
            "refresh_token": self.refresh_token[:20] + "..." if self.refresh_token else "",
            "access_token": self.access_token[:20] + "..." if self.access_token else "",
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }


class OutlookBrowserRegistrationRunner:
    """执行单个 Outlook 账号注册任务。"""

    def __init__(
        self,
        config: Optional[Dict[str, object]] = None,
        proxy_url: Optional[str] = None,
        callback_logger: Optional[Callable[[str], None]] = None,
    ):
        merged_config = dict(OUTLOOK_REGISTER_DEFAULTS)
        if config:
            merged_config.update(config)

        self.config = merged_config
        self.proxy_url = proxy_url
        self.callback_logger = callback_logger or (lambda message: logger.info(message))

    def _log(self, message: str) -> None:
        self.callback_logger(message)
        logger.info(message)

    def _wait(self, page, seconds: float) -> None:
        if seconds <= 0:
            return
        page.wait_for_timeout(int(seconds * 1000))

    def _sleep_scaled(self, page, scale: float) -> None:
        base_seconds = float(self.config.get("bot_protection_wait_seconds", 12) or 0)
        self._wait(page, max(0, base_seconds * scale))

    def _start_playwright(self):
        requested_backend = str(self.config.get("browser_backend", "auto") or "auto").lower()
        candidates = [requested_backend]
        if requested_backend == "auto":
            candidates = ["patchright", "playwright"]

        browser_path = self.config.get("browser_path") or None
        last_error = None

        for backend in candidates:
            try:
                if backend == "patchright":
                    from patchright.sync_api import sync_playwright  # type: ignore
                else:
                    from playwright.sync_api import sync_playwright  # type: ignore

                playwright = sync_playwright().start()
                launch_kwargs = {
                    "headless": False,
                    "args": ["--lang=zh-CN"],
                }
                if self.proxy_url:
                    launch_kwargs["proxy"] = {"server": self.proxy_url, "bypass": "localhost"}
                if browser_path and backend == "playwright":
                    launch_kwargs["executable_path"] = browser_path

                browser = playwright.chromium.launch(**launch_kwargs)
                self._log(f"[系统] 浏览器后端已启用: {backend}")
                return backend, playwright, browser
            except Exception as exc:  # pragma: no cover - 依赖环境差异大
                last_error = exc
                logger.warning("启动 %s 失败: %s", backend, exc)

        raise RuntimeError(f"启动浏览器失败: {last_error}")

    def _handle_optional_oauth_form(self, page, email: str) -> None:
        try:
            login_locator = page.locator('[name="loginfmt"]')
            if login_locator.count() > 0:
                login_locator.fill(email, timeout=10_000)
                page.locator("#idSIButton9").click(timeout=7_000)
        except Exception:
            pass

        for selector in [
            '[data-testid="appConsentPrimaryButton"]',
            '#acceptButton',
            'button:has-text("接受")',
            'button:has-text("Accept")',
        ]:
            try:
                locator = page.locator(selector)
                if locator.count() > 0:
                    locator.first.click(timeout=10_000)
                    break
            except Exception:
                continue

    def _collect_oauth_tokens(self, page, email: str) -> OutlookRegistrationResult:
        client_id = str(self.config.get("client_id") or "").strip()
        redirect_url = str(self.config.get("redirect_url") or "").strip()
        scopes = self.config.get("scopes") or []

        if not client_id or not redirect_url or not scopes:
            return OutlookRegistrationResult(
                success=False,
                email=email,
                error_message="启用 OAuth2 时必须填写 client_id、redirect_url 和 scopes",
            )

        code_verifier = _generate_code_verifier()
        code_challenge = _generate_code_challenge(code_verifier)
        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_url,
            "scope": " ".join(scopes),
            "response_mode": "query",
            "prompt": "select_account",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        callback_url = None
        authorize_url = f"{MS_AUTHORIZE_URL}?{'&'.join(f'{k}={quote(str(v))}' for k, v in params.items())}"

        with page.expect_response(lambda response: redirect_url in response.url, timeout=50_000) as response_info:
            page.goto(authorize_url, wait_until="domcontentloaded")
            self._handle_optional_oauth_form(page, email)
            callback_url = response_info.value.url

        if not callback_url or "code=" not in callback_url:
            return OutlookRegistrationResult(
                success=False,
                email=email,
                error_message="OAuth2 回调中未获取到授权码",
            )

        auth_code = parse_qs(callback_url.split("?", 1)[1]).get("code", [""])[0]
        token_payload = {
            "client_id": client_id,
            "code": auth_code,
            "redirect_uri": redirect_url,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
            "scope": " ".join(scopes),
        }

        try:
            token_response = _exchange_oauth_token(token_payload, self.proxy_url)
        except Exception as exc:
            return OutlookRegistrationResult(
                success=False,
                email=email,
                error_message=f"OAuth2 token 交换失败: {exc}",
            )

        refresh_token = str(token_response.get("refresh_token") or "")
        access_token = str(token_response.get("access_token") or "")
        expires_in = int(token_response.get("expires_in") or 0)

        if not refresh_token:
            return OutlookRegistrationResult(
                success=False,
                email=email,
                error_message=f"OAuth2 token 响应缺少 refresh_token: {token_response}",
            )

        return OutlookRegistrationResult(
            success=True,
            email=email,
            refresh_token=refresh_token,
            access_token=access_token,
            expires_at=datetime.utcnow() + timedelta(seconds=expires_in) if expires_in else None,
            metadata={
                "client_id": client_id,
                "redirect_url": redirect_url,
                "scopes": scopes,
            },
        )

    def _complete_post_registration(self, page, email: str) -> Optional[str]:
        try:
            page.get_by_text("取消").click(timeout=20_000)
        except Exception as exc:
            return f"注册成功，但无法跳过后续引导: {exc}"

        try:
            try:
                page.get_by_text("无法创建通行密钥").wait_for(timeout=25_000)
                page.get_by_text("取消").click(timeout=7_000)
            except Exception:
                pass

            page.locator('[aria-label="新邮件"]').wait_for(timeout=26_000)
            self._log(f"[成功] Outlook 账号已完成初始化: {email}")
            return None
        except Exception as exc:
            return f"邮箱初始化未完成: {exc}"

    def _register_account(self, page, email_local_part: str, password: str) -> OutlookRegistrationResult:
        full_email = f"{email_local_part}@outlook.com"
        user_info = generate_random_user_info()
        first_name = str(user_info["name"])[:12]
        last_name = secrets.choice(["Smith", "Johnson", "Taylor", "Brown", "Lee"])
        birth_year, birth_month, birth_day = user_info["birthdate"].split("-")

        try:
            page.goto(
                "https://outlook.live.com/mail/0/?prompt=create_account",
                timeout=20_000,
                wait_until="domcontentloaded",
            )
            page.get_by_text("同意并继续").wait_for(timeout=30_000)
            start_time = time.time()
            self._sleep_scaled(page, 0.05)
            page.get_by_text("同意并继续").click(timeout=30_000)
        except Exception as exc:
            return OutlookRegistrationResult(success=False, error_message=f"无法进入 Outlook 注册页: {exc}")

        try:
            page.locator('[aria-label="新建电子邮件"]').type(
                email_local_part,
                delay=max(20, int(float(self.config.get("bot_protection_wait_seconds", 12)) * 4)),
                timeout=10_000,
            )
            page.locator('[data-testid="primaryButton"]').click(timeout=5_000)
            self._sleep_scaled(page, 0.03)
            page.locator('[type="password"]').type(
                password,
                delay=max(15, int(float(self.config.get("bot_protection_wait_seconds", 12)) * 3)),
                timeout=10_000,
            )
            self._sleep_scaled(page, 0.02)
            page.locator('[data-testid="primaryButton"]').click(timeout=5_000)

            self._sleep_scaled(page, 0.02)
            page.locator('[name="BirthYear"]').fill(birth_year, timeout=10_000)

            try:
                page.locator('[name="BirthMonth"]').select_option(value=str(int(birth_month)), timeout=1_500)
                page.locator('[name="BirthDay"]').select_option(value=str(int(birth_day)), timeout=1_500)
            except Exception:
                page.locator('[name="BirthMonth"]').click()
                page.locator(f'[role="option"]:text-is("{int(birth_month)}月")').click()
                page.locator('[name="BirthDay"]').click()
                page.locator(f'[role="option"]:text-is("{int(birth_day)}日")').click()

            page.locator('[data-testid="primaryButton"]').click(timeout=5_000)
            page.locator("#lastNameInput").type(last_name, timeout=10_000)
            self._sleep_scaled(page, 0.02)
            page.locator("#firstNameInput").fill(first_name, timeout=10_000)

            elapsed = time.time() - start_time
            minimum_wait = float(self.config.get("bot_protection_wait_seconds", 12))
            if elapsed < minimum_wait:
                self._wait(page, minimum_wait - elapsed)

            page.locator('[data-testid="primaryButton"]').click(timeout=5_000)
            page.locator('span > [href="https://go.microsoft.com/fwlink/?LinkID=521839"]').wait_for(
                state="detached",
                timeout=22_000,
            )
            page.wait_for_timeout(500)
        except Exception as exc:
            return OutlookRegistrationResult(success=False, error_message=f"表单提交失败: {exc}")

        if (
            page.get_by_text("一些异常活动").count()
            or page.get_by_text("此站点正在维护，暂时无法使用，请稍后重试。").count() > 0
        ):
            return OutlookRegistrationResult(success=False, error_message="当前 IP 或浏览器环境触发了限流/风控")

        if page.locator("iframe#enforcementFrame").count() > 0:
            return OutlookRegistrationResult(success=False, error_message="检测到 FunCaptcha，当前流程仅兼容按压验证码")

        max_captcha_retries = int(self.config.get("max_captcha_retries", 2) or 0)
        solved = False

        if page.locator('iframe[title="验证质询"]').count() > 0:
            try:
                frame1 = page.frame_locator('iframe[title="验证质询"]')
                frame2 = frame1.frame_locator('iframe[style*="display: block"]')
                for _ in range(max_captcha_retries + 1):
                    frame2.locator('[aria-label="可访问性挑战"]').click(timeout=15_000)
                    frame2.locator('[aria-label="再次按下"]').click(timeout=30_000)
                    try:
                        page.locator(".draw").wait_for(state="detached", timeout=15_000)
                        page.wait_for_timeout(8_000)
                        if frame2.locator('[aria-label="可访问性挑战"]').count() > 0:
                            continue
                        solved = True
                        break
                    except Exception:
                        continue
            except Exception:
                solved = False
        else:
            try:
                page.wait_for_event(
                    "request",
                    lambda req: req.url.startswith("blob:https://iframe.hsprotect.net/"),
                    timeout=22_000,
                )
                page.wait_for_timeout(800)
                for _ in range(max_captcha_retries + 1):
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(11_500)
                    page.keyboard.press("Enter")
                    try:
                        page.wait_for_event(
                            "request",
                            lambda req: req.url.startswith("https://browser.events.data.microsoft.com"),
                            timeout=10_000,
                        )
                        try:
                            page.wait_for_event(
                                "request",
                                lambda req: req.url.startswith("https://collector-pxzc5j78di.hsprotect.net/assets/js/bundle"),
                                timeout=4_000,
                            )
                            page.wait_for_timeout(1_500)
                            continue
                        except Exception:
                            solved = True
                            break
                    except Exception:
                        continue
            except Exception:
                solved = False

        if not solved:
            return OutlookRegistrationResult(
                success=False,
                error_message="验证码未通过或重试次数已用尽",
            )

        post_init_error = self._complete_post_registration(page, full_email)
        base_result = OutlookRegistrationResult(
            success=post_init_error is None or not bool(self.config.get("enable_oauth2")),
            email=full_email,
            password=password,
            error_message=post_init_error or "",
            metadata={"provider": "outlook.live.com"},
        )

        if not bool(self.config.get("enable_oauth2")):
            if post_init_error:
                base_result.success = False
                base_result.metadata["account_created"] = True
            return base_result

        oauth_result = self._collect_oauth_tokens(page, full_email)
        oauth_result.email = full_email
        oauth_result.password = password
        oauth_result.metadata = {
            **base_result.metadata,
            **oauth_result.metadata,
            "account_created": True,
        }
        return oauth_result

    def run(self) -> OutlookRegistrationResult:
        backend = None
        playwright = None
        browser = None
        context = None

        try:
            backend, playwright, browser = self._start_playwright()
            context = browser.new_context()
            page = context.new_page()

            email_local_part = _random_email_local_part(random.randint(12, 14))
            password = _generate_strong_password(random.randint(11, 15))
            result = self._register_account(page, email_local_part, password)
            result.metadata.setdefault("browser_backend", backend)
            return result
        except Exception as exc:  # pragma: no cover - 浏览器环境相关
            logger.exception("Outlook 注册任务异常")
            return OutlookRegistrationResult(success=False, error_message=str(exc))
        finally:
            try:
                if context:
                    context.close()
            except Exception:
                pass
            try:
                if browser:
                    browser.close()
            except Exception:
                pass
            try:
                if playwright:
                    playwright.stop()
            except Exception:
                pass
