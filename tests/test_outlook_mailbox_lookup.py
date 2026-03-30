from contextlib import contextmanager
from pathlib import Path
import sys
import types


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


requests_module = types.ModuleType("curl_cffi.requests")
requests_module.Session = type("Session", (), {})
requests_module.Response = type("Response", (), {})
requests_module.RequestsError = type("RequestsError", (Exception,), {})

curl_cffi_module = types.ModuleType("curl_cffi")
curl_cffi_module.requests = requests_module
curl_cffi_module.CurlMime = type("CurlMime", (), {})

sys.modules.setdefault("curl_cffi", curl_cffi_module)
sys.modules.setdefault("curl_cffi.requests", requests_module)

from src.config.constants import EmailServiceType
from src.database.models import Base, EmailService, RegistrationTask
from src.database.session import DatabaseSessionManager
from src.services.outlook.account import OutlookAccount
from src.services.outlook.base import EmailMessage
from src.services.outlook.providers.graph_api import GraphAPIProvider
from src.services.outlook.providers.imap_old import IMAPOldProvider
from src.services.outlook.providers.base import ProviderConfig
from src.services.outlook.service import OutlookService
from src.web.routes import registration as registration_routes


def _build_manager(db_name: str) -> DatabaseSessionManager:
    runtime_dir = Path("tests_runtime")
    runtime_dir.mkdir(exist_ok=True)
    db_path = runtime_dir / db_name
    if db_path.exists():
        db_path.unlink()

    manager = DatabaseSessionManager(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=manager.engine)
    return manager


def _build_get_db(manager: DatabaseSessionManager):
    @contextmanager
    def fake_get_db():
        session = manager.SessionLocal()
        try:
            yield session
        finally:
            session.close()

    return fake_get_db


class _FakeImapConnection:
    def __init__(self):
        self.selected_folder = None

    def select(self, folder, readonly=True):
        self.selected_folder = folder
        return "OK", [b""]

    def search(self, charset, flag):
        if self.selected_folder == "INBOX":
            return "OK", [b""]
        if self.selected_folder == "Junk":
            return "OK", [b"1"]
        return "OK", [b""]

    def fetch(self, msg_id, mode):
        raw = (
            b"From: noreply@openai.com\r\n"
            b"Subject: Your OpenAI verification code\r\n"
            b"Date: Mon, 01 Jan 2024 00:00:00 +0000\r\n"
            b"\r\n"
            b"Your verification code is 123456"
        )
        return "OK", [(b"1", raw)]


class _FakeGraphResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_imap_old_provider_reads_junk_folder_when_inbox_is_empty():
    provider = IMAPOldProvider(
        OutlookAccount(email="tester@example.com", password="secret"),
        ProviderConfig(timeout=5),
    )
    provider._connected = True
    provider._conn = _FakeImapConnection()

    emails = provider.get_recent_emails(count=5, only_unseen=False, folders=["INBOX", "Junk"])

    assert len(emails) == 1
    assert emails[0].folder == "Junk"
    assert "123456" in emails[0].body


def test_graph_provider_reads_junk_folder_when_requested(monkeypatch):
    provider = GraphAPIProvider(
        OutlookAccount(
            email="tester@example.com",
            client_id="client-id",
            refresh_token="refresh-token",
        ),
        ProviderConfig(timeout=5),
    )
    provider._connected = True
    provider._token_manager = type(
        "FakeTokenManager",
        (),
        {
            "get_access_token": lambda self: "token",
            "clear_cache": lambda self: None,
        },
    )()

    requested_urls = []

    def fake_get(url, **kwargs):
        requested_urls.append(url)
        if url.endswith("/mailFolders/inbox/messages"):
            return _FakeGraphResponse(200, {"value": []})
        if url.endswith("/mailFolders/junkemail/messages"):
            return _FakeGraphResponse(
                200,
                {
                    "value": [
                        {
                            "id": "msg-1",
                            "subject": "Your OpenAI verification code",
                            "from": {"emailAddress": {"address": "noreply@openai.com"}},
                            "toRecipients": [{"emailAddress": {"address": "tester@example.com"}}],
                            "receivedDateTime": "2024-01-01T00:00:00Z",
                            "isRead": False,
                            "hasAttachments": False,
                            "bodyPreview": "Your verification code is 123456",
                            "body": {"content": "Your verification code is 123456"},
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("src.services.outlook.providers.graph_api._requests.get", fake_get)

    emails = provider.get_recent_emails(count=5, only_unseen=False, folders=["INBOX", "Junk E-mail"])

    assert len(emails) == 1
    assert emails[0].folder == "Junk E-mail"
    assert requested_urls == [
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages",
        "https://graph.microsoft.com/v1.0/me/mailFolders/junkemail/messages",
    ]


def test_outlook_service_checks_junk_folders_for_verification_code(monkeypatch):
    service = OutlookService({"email": "tester@example.com", "password": "secret"})
    captured = {}

    def fake_try(account, count=20, only_unseen=True, folders=None):
        captured["folders"] = list(folders or [])
        return [
            EmailMessage(
                id="msg-1",
                subject="Your OpenAI verification code",
                sender="noreply@openai.com",
                body="Your verification code is 123456",
                folder="Junk E-mail",
                received_timestamp=1_700_000_000,
            )
        ]

    monkeypatch.setattr(service, "_try_providers_for_emails", fake_try)

    code = service.get_verification_code(
        "tester@example.com",
        timeout=1,
        otp_sent_at=1_700_000_000,
    )

    assert code == "123456"
    assert "Junk" in captured["folders"]
    assert "Junk E-mail" in captured["folders"]


def test_sync_registration_task_uses_bound_email_service_id(monkeypatch):
    manager = _build_manager("outlook_batch_binding.db")
    fake_get_db = _build_get_db(manager)

    with manager.session_scope() as session:
        selected_service = EmailService(
            service_type="outlook",
            name="selected@example.com",
            config={"email": "selected@example.com", "password": "secret"},
            enabled=True,
        )
        session.add(selected_service)
        session.flush()

        task = RegistrationTask(
            task_uuid="task-bound-service",
            status="pending",
            email_service_id=selected_service.id,
        )
        session.add(task)

    captured = {}

    class _FakeEngine:
        def __init__(self, email_service, proxy_url=None, callback_logger=None, task_uuid=None):
            captured["task_uuid"] = task_uuid

        def run(self):
            return registration_routes.RegistrationResult(
                success=False,
                error_message="expected test failure",
            )

    def fake_create(service_type, config, name=None):
        captured["service_type"] = service_type
        captured["config"] = dict(config)
        return object()

    monkeypatch.setattr(registration_routes, "get_db", fake_get_db)
    monkeypatch.setattr(registration_routes.EmailServiceFactory, "create", fake_create)
    monkeypatch.setattr(registration_routes, "RegistrationEngine", _FakeEngine)

    registration_routes._run_sync_registration_task(
        task_uuid="task-bound-service",
        email_service_type="outlook",
        proxy=None,
        email_service_config=None,
        email_service_id=None,
    )

    assert captured["task_uuid"] == "task-bound-service"
    assert captured["service_type"] == EmailServiceType.OUTLOOK
    assert captured["config"]["email"] == "selected@example.com"


def test_outlook_register_job_persists_created_account_as_email_service(monkeypatch):
    manager = _build_manager("outlook_register_job.db")
    fake_get_db = _build_get_db(manager)

    with manager.session_scope() as session:
        session.add(
            RegistrationTask(
                task_uuid="task-outlook-create",
                status="pending",
                task_type="outlook_register",
            )
        )

    class _FakeResult:
        def __init__(self):
            self.success = True
            self.email = "created@example.com"
            self.password = "Secret123!"
            self.refresh_token = "refresh-token"
            self.access_token = "access-token"
            self.expires_at = None
            self.error_message = ""
            self.metadata = {}

        def to_dict(self):
            return {
                "success": True,
                "email": self.email,
                "password": self.password,
                "refresh_token": "refresh-token...",
                "access_token": "access-token...",
                "expires_at": None,
                "error_message": "",
                "metadata": {},
            }

    class _FakeRunner:
        def __init__(self, config=None, proxy_url=None, callback_logger=None):
            self.config = config or {}

        def run(self):
            return _FakeResult()

    monkeypatch.setattr(registration_routes, "get_db", fake_get_db)
    monkeypatch.setattr(registration_routes, "OutlookBrowserRegistrationRunner", _FakeRunner)
    monkeypatch.setattr(registration_routes, "get_proxy_for_registration", lambda db: (None, None))

    result = registration_routes._run_sync_job_task(
        task_uuid="task-outlook-create",
        task_type="outlook_register",
        proxy=None,
        job_config={
            "persist_as_email_service": True,
            "client_id": "client-id",
            "redirect_url": "http://localhost:8000",
            "scopes": ["offline_access"],
        },
    )

    assert result.success is True

    with manager.session_scope() as session:
        task = session.query(RegistrationTask).filter_by(task_uuid="task-outlook-create").first()
        service = session.query(EmailService).filter_by(name="created@example.com", service_type="outlook").first()

        assert task is not None
        assert task.status == "completed"
        assert service is not None
        assert service.config["email"] == "created@example.com"
        assert service.config["password"] == "Secret123!"
