import json
from pathlib import Path
import subprocess
import textwrap


def run_app_js_scenario(scenario_js: str) -> None:
    app_js_path = Path("static/js/app.js").resolve()
    scenario_wrapper = json.dumps(f"(async () => {{\n{scenario_js}\n}})()")

    node_script = textwrap.dedent(
        f"""
        (async () => {{
        const fs = require('fs');
        const vm = require('vm');

        class FakeElement {{
          constructor(id) {{
            this.id = id;
            this.value = '';
            this.checked = false;
            this.disabled = false;
            this.innerHTML = '';
            this.textContent = '';
            this.className = '';
            this.dataset = {{}};
            this.style = {{}};
            this.children = [];
            this.listeners = {{}};
            this.scrollTop = 0;
            this.scrollHeight = 0;
          }}

          addEventListener(type, callback) {{
            this.listeners[type] = callback;
          }}

          appendChild(child) {{
            this.children.push(child);
            this.scrollHeight = this.children.length;
            return child;
          }}

          querySelectorAll() {{
            return [];
          }}

          querySelector() {{
            return null;
          }}

          closest() {{
            return null;
          }}

          contains() {{
            return false;
          }}

          remove() {{
            return null;
          }}
        }}

        const ids = [
          'registration-form', 'email-service', 'reg-mode', 'reg-mode-group',
          'batch-count-group', 'batch-count', 'batch-options', 'interval-min',
          'interval-max', 'start-btn', 'cancel-btn', 'task-status-row',
          'batch-progress-section', 'console-log', 'clear-log-btn', 'task-id',
          'task-email', 'task-status', 'task-service', 'task-status-badge',
          'batch-progress-text', 'batch-progress-percent', 'progress-bar',
          'batch-success', 'batch-failed', 'batch-remaining',
          'recent-accounts-table', 'refresh-accounts-btn',
          'outlook-batch-section', 'outlook-accounts-container',
          'outlook-select-all-btn', 'outlook-select-unregistered-btn',
          'outlook-deselect-all-btn', 'outlook-interval-min',
          'outlook-interval-max', 'outlook-skip-registered',
          'outlook-concurrency-mode', 'outlook-concurrency-count',
          'outlook-concurrency-hint', 'outlook-interval-group',
          'outlook-register-section', 'outlook-register-count',
          'outlook-register-backend', 'outlook-register-browser-path',
          'outlook-register-bot-wait', 'outlook-register-captcha-retries',
          'outlook-register-concurrency-mode', 'outlook-register-concurrency-count',
          'outlook-register-concurrency-hint', 'outlook-register-interval-group',
          'outlook-register-interval-min', 'outlook-register-interval-max',
          'outlook-register-persist-service', 'outlook-register-enable-oauth2',
          'outlook-register-oauth-group', 'outlook-register-client-id',
          'outlook-register-redirect-url', 'outlook-register-scopes',
          'concurrency-mode', 'concurrency-count', 'concurrency-hint',
          'interval-group', 'auto-upload-cpa', 'cpa-service-select-group',
          'cpa-service-select', 'auto-upload-sub2api',
          'sub2api-service-select-group', 'sub2api-service-select',
          'auto-upload-tm', 'tm-service-select-group', 'tm-service-select'
        ];

        const elements = Object.fromEntries(ids.map((id) => [id, new FakeElement(id)]));
        elements['email-service'].value = 'tempmail:default';
        elements['reg-mode'].value = 'single';
        elements['batch-count'].value = '7';
        elements['interval-min'].value = '5';
        elements['interval-max'].value = '30';
        elements['concurrency-mode'].value = 'pipeline';
        elements['concurrency-count'].value = '3';
        elements['outlook-skip-registered'].checked = true;
        elements['outlook-interval-min'].value = '5';
        elements['outlook-interval-max'].value = '30';
        elements['outlook-concurrency-mode'].value = 'pipeline';
        elements['outlook-concurrency-count'].value = '3';
        elements['outlook-register-count'].value = '3';
        elements['outlook-register-backend'].value = 'auto';
        elements['outlook-register-bot-wait'].value = '12';
        elements['outlook-register-captcha-retries'].value = '2';
        elements['outlook-register-concurrency-mode'].value = 'pipeline';
        elements['outlook-register-concurrency-count'].value = '2';
        elements['outlook-register-interval-min'].value = '5';
        elements['outlook-register-interval-max'].value = '30';
        elements['outlook-register-persist-service'].checked = true;

        const documentListeners = {{}};
        const testState = {{
          postedPaths: [],
          getResponses: {{}},
          postResponses: {{}},
          querySelectorAllMap: {{}},
          websocketReadyState: null
        }};

        const document = {{
          getElementById(id) {{
            return elements[id] || new FakeElement(id);
          }},
          addEventListener(type, callback) {{
            if (!documentListeners[type]) {{
              documentListeners[type] = [];
            }}
            documentListeners[type].push(callback);
          }},
          createElement(tag) {{
            return new FakeElement(tag);
          }},
          querySelectorAll(selector) {{
            return testState.querySelectorAllMap[selector] || [];
          }},
          body: new FakeElement('body')
        }};

        const sessionStorage = {{
          _store: {{}},
          getItem(key) {{
            return Object.prototype.hasOwnProperty.call(this._store, key) ? this._store[key] : null;
          }},
          setItem(key, value) {{
            this._store[key] = String(value);
          }},
          removeItem(key) {{
            delete this._store[key];
          }}
        }};

        const api = {{
          async get(path) {{
            if (Object.prototype.hasOwnProperty.call(testState.getResponses, path)) {{
              const response = testState.getResponses[path];
              return typeof response === 'function' ? await response(path) : response;
            }}
            if (path === '/registration/available-services') {{
              return {{
                tempmail: {{ available: true, count: 1, services: [{{ id: 'default', name: 'Tempmail.lol' }}] }},
                yyds_mail: {{ available: false, count: 0, services: [] }},
                outlook: {{ available: false, count: 0, services: [] }},
                moe_mail: {{ available: false, count: 0, services: [] }},
                temp_mail: {{ available: false, count: 0, services: [] }},
                duck_mail: {{ available: false, count: 0, services: [] }},
                freemail: {{ available: false, count: 0, services: [] }}
              }};
            }}
            if (path === '/accounts?page=1&page_size=10') {{
              return {{ accounts: [] }};
            }}
            if (path === '/registration/batch/batch-1') {{
              return {{ total: 7, completed: 0, success: 0, failed: 0, cancelled: false, finished: false }};
            }}
            if (path === '/registration/jobs/batch/job-batch-1') {{
              return {{ job_type: 'outlook_register', total: 3, completed: 0, success: 0, failed: 0, cancelled: false, finished: false, logs: [] }};
            }}
            return [];
          }},
          async post(path) {{
            testState.postedPaths.push(path);
            if (Object.prototype.hasOwnProperty.call(testState.postResponses, path)) {{
              const response = testState.postResponses[path];
              return typeof response === 'function' ? await response(path) : response;
            }}
            if (path === '/registration/batch') {{
              return {{ batch_id: 'batch-1', count: 7, tasks: [] }};
            }}
            if (path === '/registration/start') {{
              return {{ task_uuid: 'task-1' }};
            }}
            if (path === '/registration/outlook-batch') {{
              return {{ batch_id: 'outlook-batch-1', total: 2, skipped: 0, to_register: 2, service_ids: [1, 2] }};
            }}
            if (path === '/registration/jobs/batch') {{
              return {{ batch_id: 'job-batch-1', job_type: 'outlook_register', count: 3, tasks: [] }};
            }}
            return {{}};
          }}
        }};

        class FakeWebSocket {{
          constructor(url) {{
            this.url = url;
            this.readyState = testState.websocketReadyState ?? FakeWebSocket.OPEN;
          }}

          close() {{
            this.readyState = FakeWebSocket.CLOSED;
          }}

          send() {{
            return null;
          }}
        }}

        FakeWebSocket.CONNECTING = 0;
        FakeWebSocket.OPEN = 1;
        FakeWebSocket.CLOSED = 3;

        const context = {{
          console,
          document,
          documentListeners,
          elements,
          testState,
          window: {{
            location: {{
              protocol: 'http:',
              host: '127.0.0.1:8000'
            }}
          }},
          sessionStorage,
          api,
          toast: {{
            error() {{}},
            info() {{}},
            success() {{}},
            warning() {{}}
          }},
          WebSocket: FakeWebSocket,
          theme: {{ toggle() {{}} }},
          copyToClipboard() {{}},
          setInterval() {{ return 1; }},
          clearInterval() {{}},
          setTimeout,
          clearTimeout,
          Promise,
          Date,
          Math,
          JSON,
          Array,
          Object,
          String,
          parseInt,
        }};

        vm.createContext(context);
        const code = fs.readFileSync({str(app_js_path)!r}, 'utf8');
        vm.runInContext(code, context);
        vm.runInContext(
          `
          globalThis.__test_state = globalThis.testState;
          globalThis.__elements = globalThis.elements;
          globalThis.__run_dom_content_loaded = async function () {{
            for (const callback of globalThis.documentListeners['DOMContentLoaded'] || []) {{
              callback();
            }}
            await Promise.resolve();
            await Promise.resolve();
          }};
          globalThis.__test_exports = {{
            handleStartRegistration,
            handleCancelTask,
            handleModeChange,
            resetButtons,
            restoreActiveTask
          }};
          `,
          context
        );

        await vm.runInContext({scenario_wrapper}, context);
        }})().catch((error) => {{
          console.error(error);
          process.exit(1);
        }});
        """
    )

    result = subprocess.run(
        ["node", "-e", node_script],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_registration_page_initial_batch_mode_submits_batch_request():
    run_app_js_scenario(
        """
        await globalThis.__run_dom_content_loaded();
        __elements['reg-mode'].value = 'batch';
        __test_exports.handleModeChange({ target: __elements['reg-mode'] });

        await __test_exports.handleStartRegistration({
          preventDefault() {}
        });

        if (__test_state.postedPaths[0] !== '/registration/batch') {
          throw new Error(`expected first request to /registration/batch, got ${__test_state.postedPaths[0]}`);
        }
        """
    )


def test_registration_page_batch_reset_keeps_batch_mode_and_unlocks_controls():
    run_app_js_scenario(
        """
        await globalThis.__run_dom_content_loaded();
        __elements['reg-mode'].value = 'batch';
        __test_exports.handleModeChange({ target: __elements['reg-mode'] });

        await __test_exports.handleStartRegistration({
          preventDefault() {}
        });

        if (!__elements['email-service'].disabled || !__elements['batch-count'].disabled || !__elements['concurrency-count'].disabled) {
          throw new Error('expected batch controls to be locked while task is running');
        }

        __test_exports.resetButtons();

        if (__elements['email-service'].disabled || __elements['batch-count'].disabled || __elements['concurrency-count'].disabled) {
          throw new Error('expected batch controls to be unlocked after reset');
        }

        await __test_exports.handleStartRegistration({
          preventDefault() {}
        });

        if (__test_state.postedPaths[1] !== '/registration/batch') {
          throw new Error(`expected second request to /registration/batch, got ${__test_state.postedPaths[1]}`);
        }
        """
    )


def test_registration_page_restore_running_batch_locks_controls():
    run_app_js_scenario(
        """
        sessionStorage.setItem('activeTask', JSON.stringify({
          batch_id: 'batch-restore',
          mode: 'batch',
          total: 10
        }));
        __test_state.getResponses['/registration/batch/batch-restore'] = {
          total: 10,
          completed: 3,
          success: 2,
          failed: 1,
          cancelled: false,
          finished: false
        };

        await globalThis.__run_dom_content_loaded();

        if (__elements['reg-mode'].value !== 'batch') {
          throw new Error(`expected reg-mode to stay on batch, got ${__elements['reg-mode'].value}`);
        }
        if (!__elements['email-service'].disabled || !__elements['reg-mode'].disabled || !__elements['batch-count'].disabled) {
          throw new Error('expected restored batch task to lock core registration controls');
        }
        """
    )


def test_registration_page_batch_cancel_rest_keeps_controls_locked_until_terminal_status():
    run_app_js_scenario(
        """
        __test_state.websocketReadyState = WebSocket.CLOSED;

        await globalThis.__run_dom_content_loaded();
        __elements['reg-mode'].value = 'batch';
        __test_exports.handleModeChange({ target: __elements['reg-mode'] });

        await __test_exports.handleStartRegistration({
          preventDefault() {}
        });
        await __test_exports.handleCancelTask();

        if (__test_state.postedPaths[0] !== '/registration/batch') {
          throw new Error(`expected first request to /registration/batch, got ${__test_state.postedPaths[0]}`);
        }
        if (__test_state.postedPaths[1] !== '/registration/batch/batch-1/cancel') {
          throw new Error(`expected cancel request to /registration/batch/batch-1/cancel, got ${__test_state.postedPaths[1]}`);
        }
        if (!__elements['start-btn'].disabled || !__elements['cancel-btn'].disabled || !__elements['email-service'].disabled) {
          throw new Error('expected controls to remain locked while cancellation is still pending');
        }
        """
    )


def test_registration_page_outlook_register_submits_generic_job_batch_request():
    run_app_js_scenario(
        """
        await globalThis.__run_dom_content_loaded();
        __elements['email-service'].value = 'outlook_register:job';

        await __test_exports.handleStartRegistration({
          preventDefault() {}
        });

        if (__test_state.postedPaths[0] !== '/registration/jobs/batch') {
          throw new Error(`expected first request to /registration/jobs/batch, got ${__test_state.postedPaths[0]}`);
        }
        """
    )
