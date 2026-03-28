"""
账号邮箱服务恢复工具
"""

from typing import Optional, Tuple

from ..config.constants import EmailServiceType
from ..config.settings import get_settings
from ..database.models import Account, EmailService as EmailServiceModel
from ..services import BaseEmailService, EmailServiceFactory


def build_account_email_service_config(
    db,
    service_type: EmailServiceType,
    email: str,
    proxy_url: Optional[str] = None,
) -> Optional[dict]:
    """根据账号信息恢复邮箱服务配置。"""
    if service_type == EmailServiceType.TEMPMAIL:
        settings = get_settings()
        config = {
            "base_url": settings.tempmail_base_url,
            "timeout": settings.tempmail_timeout,
            "max_retries": settings.tempmail_max_retries,
        }
    elif service_type == EmailServiceType.MOE_MAIL:
        domain = email.split("@", 1)[1] if "@" in email else ""
        services = db.query(EmailServiceModel).filter(
            EmailServiceModel.service_type == "moe_mail",
            EmailServiceModel.enabled == True,
        ).order_by(EmailServiceModel.priority.asc()).all()
        svc = None
        for service in services:
            cfg = service.config or {}
            if cfg.get("default_domain") == domain or cfg.get("domain") == domain:
                svc = service
                break
        if not svc and services:
            svc = services[0]
        if not svc:
            return None
        config = svc.config.copy() if svc.config else {}
    else:
        type_map = {
            EmailServiceType.TEMP_MAIL: "temp_mail",
            EmailServiceType.DUCK_MAIL: "duck_mail",
            EmailServiceType.FREEMAIL: "freemail",
            EmailServiceType.IMAP_MAIL: "imap_mail",
            EmailServiceType.OUTLOOK: "outlook",
            EmailServiceType.YYDS_MAIL: "yyds_mail",
        }
        db_type = type_map.get(service_type)
        if not db_type:
            return None

        query = db.query(EmailServiceModel).filter(
            EmailServiceModel.service_type == db_type,
            EmailServiceModel.enabled == True,
        )
        if service_type == EmailServiceType.OUTLOOK:
            services = query.all()
            svc = next((item for item in services if (item.config or {}).get("email") == email), None)
        else:
            svc = query.order_by(EmailServiceModel.priority.asc()).first()

        if not svc:
            return None
        config = svc.config.copy() if svc.config else {}

    if "api_url" in config and "base_url" not in config:
        config["base_url"] = config.pop("api_url")
    if proxy_url and "proxy_url" not in config:
        config["proxy_url"] = proxy_url
    return config


def create_email_service_for_account(
    db,
    account: Account,
    proxy_url: Optional[str] = None,
) -> Tuple[EmailServiceType, BaseEmailService]:
    """为指定账号创建对应的邮箱服务实例。"""
    service_type = EmailServiceType(account.email_service)
    config = build_account_email_service_config(
        db,
        service_type=service_type,
        email=account.email,
        proxy_url=proxy_url,
    )
    if config is None:
        raise ValueError("未找到可用的邮箱服务配置")

    return service_type, EmailServiceFactory.create(service_type, config)
