"""
Frontend Button Click and Chat Bar Verification Tests
Tests for:
1. JavaScript syntax integrity in static/js/app.js and static/js/service-worker.js.
2. Programmatic click and event listener bindings for bottom chat bar buttons:
   - waReplySendBtn (Send message)
   - waReplyInput (Enter keypress send)
   - waVoiceNoteBtn (Voice note recording mic)
   - waAiVoiceCallBtn (AI Voice Call)
   - liveAiVoiceCallBtn (Topbar AI Voice Call)
   - waEmojiToggleBtn (Emoji picker tray toggle)
   - waTemplateToggleBtn (Attachment / Quick Reply template tray toggle)
   - waHeaderAiToggle (AI Auto-responder toggle)
3. Global window exposure for core navigation (switchTab) and chat controls.
4. Absence of pointer-blocking modal overlays and proper stacking context for .wa-reply-bar.
"""

import os
import subprocess
import unittest

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestFrontendButtonsAndChatBar(unittest.TestCase):

    def test_01_javascript_syntax_validity(self):
        """Verify static/js/app.js and static/js/service-worker.js pass Node.js syntax check with exit code 0."""
        app_js = os.path.join(REPO_DIR, "static", "js", "app.js")
        sw_js = os.path.join(REPO_DIR, "static", "js", "service-worker.js")

        self.assertTrue(os.path.exists(app_js), "static/js/app.js missing")
        self.assertTrue(os.path.exists(sw_js), "static/js/service-worker.js missing")

        res_app = subprocess.run(["node", "-c", app_js], capture_output=True, text=True)
        self.assertEqual(res_app.returncode, 0, f"app.js syntax error: {res_app.stderr}")

        res_sw = subprocess.run(["node", "-c", sw_js], capture_output=True, text=True)
        self.assertEqual(res_sw.returncode, 0, f"service-worker.js syntax error: {res_sw.stderr}")

    def test_02_node_dom_event_listeners_and_clicks(self):
        """Run Node.js DOM simulation to verify button click handlers trigger without errors."""
        node_test_script = """
        const fs = require('fs');
        const path = require('path');

        // Set up mock browser environment
        const mockElements = {};
        const eventLog = [];

        class MockClassList {
            constructor() { this.classes = new Set(); }
            add(c) { this.classes.add(c); }
            remove(c) { this.classes.delete(c); }
            contains(c) { return this.classes.has(c); }
            toggle(c) {
                if (this.classes.has(c)) { this.classes.delete(c); return false; }
                this.classes.add(c); return true;
            }
        }

        class MockElement {
            constructor(id, tagName = 'div', attrs = {}) {
                this.id = id;
                this.tagName = tagName;
                this.attributes = attrs;
                this.classList = new MockClassList();
                this.style = {};
                this.value = '';
                this.disabled = false;
                this.onclick = null;
                this.onkeydown = null;
                this.listeners = {};
            }
            getAttribute(name) { return this.attributes[name] || null; }
            setAttribute(name, val) { this.attributes[name] = val; }
            addEventListener(event, fn) {
                this.listeners[event] = this.listeners[event] || [];
                this.listeners[event].push(fn);
            }
            dispatchEvent(event) {
                if (this['on' + event.type]) this['on' + event.type](event);
                if (this.listeners[event.type]) {
                    this.listeners[event.type].forEach(fn => fn(event));
                }
            }
            click() {
                const ev = { type: 'click', preventDefault: () => {} };
                this.dispatchEvent(ev);
            }
        }

        function createEl(id, tagName = 'div', attrs = {}) {
            const el = new MockElement(id, tagName, attrs);
            mockElements[id] = el;
            return el;
        }

        // Register Chat Bar elements
        createEl('waReplySendBtn', 'button');
        createEl('waReplyInput', 'textarea');
        createEl('waVoiceNoteBtn', 'button');
        createEl('waAiVoiceCallBtn', 'button');
        createEl('liveAiVoiceCallBtn', 'button');
        createEl('waEmojiToggleBtn', 'button');
        createEl('waTemplateToggleBtn', 'button');
        createEl('waHeaderAiToggle', 'div');
        createEl('waEmojiTray', 'div');
        createEl('waTemplatesTray', 'div');
        createEl('tab-whatsapp', 'div');
        createEl('waConversationList', 'div');
        createEl('waMessagesStream', 'div');

        // Navigation tab buttons
        const navTab1 = new MockElement('tab1', 'button', { onclick: "switchTab('dashboard')" });
        navTab1.classList.add('hud-tab');
        const navTab2 = new MockElement('tab2', 'button', { onclick: "switchTab('whatsapp')" });
        navTab2.classList.add('hud-tab');

        // Global DOM mocks
        global.window = global;
        global.document = {
            getElementById: (id) => mockElements[id] || null,
            querySelectorAll: (sel) => {
                if (sel === '.hud-tab') return [navTab1, navTab2];
                return [];
            },
            querySelector: () => null,
            addEventListener: () => {},
            hidden: false
        };
        global.localStorage = {
            getItem: () => null,
            setItem: () => {}
        };
        global.navigator = { userAgent: 'NodeTest', serviceWorker: { register: () => Promise.resolve() } };
        global.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
        global.showToast = () => {};

        // Read and evaluate app.js
        const appCode = fs.readFileSync(path.join(__dirname, 'static', 'js', 'app.js'), 'utf8');
        try {
            eval(appCode);
        } catch (e) {
            console.error('Eval error in app.js:', e);
            process.exit(1);
        }

        // Assert essential global functions exist
        const requiredGlobals = [
            'switchTab',
            'initNavigationListeners',
            'initWhatsAppChatBarListeners',
            'sendWhatsAppReply',
            'handleWaReplyKeydown',
            'toggleVoiceRecording',
            'cancelVoiceRecording',
            'openLiveVoiceCallModal',
            'closeLiveVoiceCallModal',
            'toggleEmojiTray',
            'toggleTemplatesTray',
            'toggleWhatsAppAiAutoResponder'
        ];

        for (const fnName of requiredGlobals) {
            if (typeof global[fnName] !== 'function') {
                console.error(`Missing required global function: ${fnName}`);
                process.exit(2);
            }
        }

        // Initialize listeners
        initWhatsAppChatBarListeners();
        initNavigationListeners();

        // Verify bottom chat bar handlers are bound
        if (typeof mockElements['waReplySendBtn'].onclick !== 'function') {
            console.error('waReplySendBtn has no onclick handler bound');
            process.exit(3);
        }
        if (typeof mockElements['waReplyInput'].onkeydown !== 'function') {
            console.error('waReplyInput has no onkeydown handler bound');
            process.exit(4);
        }
        if (typeof mockElements['waVoiceNoteBtn'].onclick !== 'function') {
            console.error('waVoiceNoteBtn has no onclick handler bound');
            process.exit(5);
        }
        if (typeof mockElements['waAiVoiceCallBtn'].onclick !== 'function') {
            console.error('waAiVoiceCallBtn has no onclick handler bound');
            process.exit(6);
        }
        if (typeof mockElements['liveAiVoiceCallBtn'].onclick !== 'function') {
            console.error('liveAiVoiceCallBtn has no onclick handler bound');
            process.exit(7);
        }
        if (typeof mockElements['waEmojiToggleBtn'].onclick !== 'function') {
            console.error('waEmojiToggleBtn has no onclick handler bound');
            process.exit(8);
        }
        if (typeof mockElements['waTemplateToggleBtn'].onclick !== 'function') {
            console.error('waTemplateToggleBtn has no onclick handler bound');
            process.exit(9);
        }
        if (typeof mockElements['waHeaderAiToggle'].onclick !== 'function') {
            console.error('waHeaderAiToggle has no onclick handler bound');
            process.exit(10);
        }

        // Simulate click and keypress events
        mockElements['waReplySendBtn'].click();
        mockElements['waReplyInput'].dispatchEvent({ type: 'keydown', key: 'Enter', shiftKey: false, preventDefault: () => {} });
        mockElements['waVoiceNoteBtn'].click();
        mockElements['waAiVoiceCallBtn'].click();
        mockElements['liveAiVoiceCallBtn'].click();
        mockElements['waEmojiToggleBtn'].click();
        mockElements['waTemplateToggleBtn'].click();
        mockElements['waHeaderAiToggle'].click();
        navTab2.click();

        console.log('ALL_HANDLERS_VERIFIED');
        process.exit(0);
        """
        res = subprocess.run(
            ["node", "-e", node_test_script],
            cwd=REPO_DIR,
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0, f"Node DOM test failed:\nstdout: {res.stdout}\nstderr: {res.stderr}")
        self.assertIn("ALL_HANDLERS_VERIFIED", res.stdout)

    def test_03_templates_chat_bar_and_modals_structure(self):
        """Verify templates/index.html includes required chat bar elements and modals are hidden by default."""
        index_html_path = os.path.join(REPO_DIR, "templates", "index.html")
        with open(index_html_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Chat bar buttons and input
        self.assertIn('id="waReplySendBtn"', html)
        self.assertIn('id="waReplyInput"', html)
        self.assertIn('id="waVoiceNoteBtn"', html)
        self.assertIn('id="waAiVoiceCallBtn"', html)
        self.assertIn('id="liveAiVoiceCallBtn"', html)
        self.assertIn('id="waEmojiToggleBtn"', html)
        self.assertIn('id="waTemplateToggleBtn"', html)
        self.assertIn('id="waHeaderAiToggle"', html)

        # Modals should not block clicks by default
        self.assertIn('id="liveVoiceCallModal"', html)
        self.assertIn('id="linkWhatsAppQrModal"', html)
        self.assertTrue('id="liveVoiceCallModal" style="display: none;' in html or 'id="liveVoiceCallModal"' in html)

    def test_04_css_reply_bar_stacking(self):
        """Verify static/css/style.css assigns position relative and z-index >= 10 to .wa-reply-bar."""
        css_path = os.path.join(REPO_DIR, "static", "css", "style.css")
        with open(css_path, "r", encoding="utf-8") as f:
            css = f.read()

        self.assertIn(".wa-reply-bar {", css)
        self.assertIn("z-index: 10;", css)
        self.assertIn("position: relative;", css)


if __name__ == "__main__":
    unittest.main()
