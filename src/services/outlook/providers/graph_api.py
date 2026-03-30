"""
Graph API 提供者
使用 Microsoft Graph REST API
"""

import json
import logging
from typing import List, Optional
from datetime import datetime

from curl_cffi import requests as _requests

from ..base import ProviderType, EmailMessage
from ..account import OutlookAccount
from ..token_manager import TokenManager
from .base import OutlookProvider, ProviderConfig


logger = logging.getLogger(__name__)


class GraphAPIProvider(OutlookProvider):
    """
    Graph API 提供者
    使用 Microsoft Graph REST API 获取邮件
    需要 graph.microsoft.com/.default scope
    """

    # Graph API 端点
    GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
    DEFAULT_FOLDER_MAP = {
        "INBOX": ("inbox", "INBOX"),
        "JUNK": ("junkemail", "Junk E-mail"),
        "JUNK E-MAIL": ("junkemail", "Junk E-mail"),
        "SPAM": ("junkemail", "Junk E-mail"),
    }

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.GRAPH_API

    def __init__(
        self,
        account: OutlookAccount,
        config: Optional[ProviderConfig] = None,
    ):
        super().__init__(account, config)

        # Token 管理器
        self._token_manager: Optional[TokenManager] = None

        # 注意：Graph API 必须使用 OAuth2
        if not account.has_oauth():
            logger.warning(
                f"[{self.account.email}] Graph API 提供者需要 OAuth2 配置 "
                f"(client_id + refresh_token)"
            )

    def connect(self) -> bool:
        """
        验证连接（获取 Token）

        Returns:
            是否连接成功
        """
        if not self.account.has_oauth():
            error = "Graph API 需要 OAuth2 配置"
            self.record_failure(error)
            logger.error(f"[{self.account.email}] {error}")
            return False

        if not self._token_manager:
            self._token_manager = TokenManager(
                self.account,
                ProviderType.GRAPH_API,
                self.config.proxy_url,
                self.config.timeout,
            )

        # 尝试获取 Token
        token = self._token_manager.get_access_token()
        if token:
            self._connected = True
            self.record_success()
            logger.info(f"[{self.account.email}] Graph API 连接成功")
            return True

        return False

    def disconnect(self):
        """断开连接（清除状态）"""
        self._connected = False

    def get_recent_emails(
        self,
        count: int = 20,
        only_unseen: bool = True,
        folders: Optional[List[str]] = None,
    ) -> List[EmailMessage]:
        """
        获取最近的邮件

        Args:
            count: 获取数量
            only_unseen: 是否只获取未读
            folders: 要查询的文件夹列表

        Returns:
            邮件列表
        """
        if not self._connected:
            if not self.connect():
                return []

        try:
            # 获取 Access Token
            token = self._token_manager.get_access_token()
            if not token:
                self.record_failure("无法获取 Access Token")
                return []

            params = {
                "$top": count,
                "$select": "id,subject,from,toRecipients,receivedDateTime,isRead,hasAttachments,bodyPreview,body",
                "$orderby": "receivedDateTime desc",
            }

            # 只获取未读邮件
            if only_unseen:
                params["$filter"] = "isRead eq false"

            # 构建代理配置
            proxies = None
            if self.config.proxy_url:
                proxies = {"http": self.config.proxy_url, "https": self.config.proxy_url}

            emails = []
            seen_message_ids = set()
            folder_refs = self._normalize_folders(folders)
            had_successful_folder = False
            last_error = ""

            for folder_id, folder_label in folder_refs:
                url = f"{self.GRAPH_API_BASE}/me/mailFolders/{folder_id}/messages"
                resp = _requests.get(
                    url,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Prefer": "outlook.body-content-type='text'",
                    },
                    proxies=proxies,
                    timeout=self.config.timeout,
                    impersonate="chrome110",
                )

                if resp.status_code == 401:
                    if self._token_manager:
                        self._token_manager.clear_cache()
                    self._connected = False
                    logger.warning(f"[{self.account.email}] Graph API 返回 401，client_id 可能无 Graph 权限，跳过")
                    return []

                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    logger.warning(
                        f"[{self.account.email}] Graph API 文件夹请求失败 "
                        f"({folder_label}): HTTP {resp.status_code}"
                    )
                    continue

                had_successful_folder = True
                data = resp.json()
                messages = data.get("value", [])

                for msg in messages:
                    try:
                        email_msg = self._parse_graph_message(msg, folder=folder_label)
                        if not email_msg or email_msg.id in seen_message_ids:
                            continue

                        seen_message_ids.add(email_msg.id)
                        emails.append(email_msg)
                    except Exception as e:
                        logger.warning(f"[{self.account.email}] 解析 Graph API 邮件失败: {e}")

            if had_successful_folder:
                self.record_success()
                return emails

            if last_error:
                self.record_failure(last_error)
                logger.error(f"[{self.account.email}] Graph API 获取邮件失败: {last_error}")
            return []

        except Exception as e:
            self.record_failure(str(e))
            logger.error(f"[{self.account.email}] Graph API 获取邮件失败: {e}")
            return []

    def _parse_graph_message(self, msg: dict, folder: str = "") -> Optional[EmailMessage]:
        """
        解析 Graph API 消息

        Args:
            msg: Graph API 消息对象

        Returns:
            EmailMessage 对象
        """
        # 解析发件人
        from_info = msg.get("from", {})
        sender_info = from_info.get("emailAddress", {})
        sender = sender_info.get("address", "")

        # 解析收件人
        recipients = []
        for recipient in msg.get("toRecipients", []):
            addr_info = recipient.get("emailAddress", {})
            addr = addr_info.get("address", "")
            if addr:
                recipients.append(addr)

        # 解析日期
        received_at = None
        received_timestamp = 0
        try:
            date_str = msg.get("receivedDateTime", "")
            if date_str:
                # ISO 8601 格式
                received_at = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                received_timestamp = int(received_at.timestamp())
        except Exception:
            pass

        # 获取正文
        body_info = msg.get("body", {})
        body = body_info.get("content", "")
        body_preview = msg.get("bodyPreview", "")

        return EmailMessage(
            id=msg.get("id", ""),
            subject=msg.get("subject", ""),
            sender=sender,
            recipients=recipients,
            body=body,
            body_preview=body_preview,
            folder=folder,
            received_at=received_at,
            received_timestamp=received_timestamp,
            is_read=msg.get("isRead", False),
            has_attachments=msg.get("hasAttachments", False),
        )

    def _normalize_folders(self, folders: Optional[List[str]]) -> List[tuple[str, str]]:
        normalized = []
        seen = set()
        for folder in (folders or ["INBOX", "Junk E-mail"]):
            key = str(folder or "").strip().upper()
            if not key:
                continue
            folder_ref = self.DEFAULT_FOLDER_MAP.get(key)
            if not folder_ref or folder_ref[0] in seen:
                continue
            seen.add(folder_ref[0])
            normalized.append(folder_ref)
        return normalized or [("inbox", "INBOX")]

    def test_connection(self) -> bool:
        """
        测试 Graph API 连接

        Returns:
            连接是否正常
        """
        try:
            # 尝试获取一封邮件来测试连接
            emails = self.get_recent_emails(count=1, only_unseen=False)
            return True
        except Exception as e:
            logger.warning(f"[{self.account.email}] Graph API 连接测试失败: {e}")
            return False
