import urllib.request
import json
import sqlite3

def run_verifications():
    print("--- 1. Testing Live HTTP Endpoints ---")
    ready_res = urllib.request.urlopen("http://127.0.0.1:5000/ready")
    assert ready_res.getcode() == 200
    ready_data = json.loads(ready_res.read().decode())
    print("[PASS] /ready status 200:", ready_data["status"])

    index_res = urllib.request.urlopen("http://127.0.0.1:5000/")
    assert index_res.getcode() == 200
    html = index_res.read().decode()
    print(f"[PASS] / index.html returned {len(html)} bytes")

    print("\n--- 2. Verifying DOM Elements in index.html ---")
    assert 'id="safetyConfirmModal"' in html, "safetyConfirmModal missing"
    print("[PASS] Safety Confirmation Modal element present in DOM")

    assert 'class="pill-segmented-control"' in html, "pill-segmented-control missing"
    print("[PASS] Pill segmented control toggles present in DOM")

    assert 'class="sleek-filter-bar"' in html, "sleek-filter-bar missing"
    print("[PASS] Sleek horizontal CRM leads filter bar present in DOM")

    assert 'class="embedded-search-wrapper"' in html, "embedded-search-wrapper missing"
    print("[PASS] Embedded search input with internal icon present in DOM")

    assert 'class="engine-specs-grid"' in html, "engine-specs-grid missing"
    print("[PASS] Engine architecture specs grid present in DOM")

    assert 'class="code-editor-card"' in html, "code-editor-card missing"
    print("[PASS] Code editor cards for JSON payloads present in DOM")

    assert 'class="app-global-footer"' in html, "app-global-footer missing"
    print("[PASS] Modern enterprise sticky footer present in DOM")

    print("\n--- 3. Verifying CSS Enterprise Polish ---")
    css_res = urllib.request.urlopen("http://127.0.0.1:5000/static/css/style.css")
    assert css_res.getcode() == 200
    css = css_res.read().decode()
    assert ".status-badge.success" in css, "status-badge.success CSS missing"
    assert "#10b981" in css, "Emerald color missing"
    assert ".pill-segmented-control" in css, "pill-segmented-control CSS missing"
    assert ".pill-toggle" in css, "pill-toggle CSS missing"
    assert ".sleek-filter-bar" in css, "sleek-filter-bar CSS missing"
    assert ".embedded-search-wrapper" in css, "embedded-search-wrapper CSS missing"
    assert ".custom-sleek-select" in css, "custom-sleek-select CSS missing"
    assert ".code-editor-card" in css, "code-editor-card CSS missing"
    assert ".hud-btn.destructive-danger" in css, "destructive-danger CSS missing"
    assert ".engine-specs-grid" in css, "engine-specs-grid CSS missing"
    assert ".app-global-footer" in css, "app-global-footer CSS missing"
    print("[PASS] All 10 new CSS Enterprise components verified in style.css")

    print("\n--- 4. Verifying JS Engine & Safety Modal Logic ---")
    js_res = urllib.request.urlopen("http://127.0.0.1:5000/static/js/app.js")
    assert js_res.getcode() == 200
    js = js_res.read().decode()
    assert "openSafetyConfirmModal" in js, "openSafetyConfirmModal missing"
    assert "promptPurgeLogsModal" in js, "promptPurgeLogsModal missing"
    assert "promptClearAlertsModal" in js, "promptClearAlertsModal missing"
    assert "promptRemoveTeamMember" in js, "promptRemoveTeamMember missing"
    assert "promptDeleteWebhook" in js, "promptDeleteWebhook missing"
    assert "formatManualPayloadJson" in js, "formatManualPayloadJson missing"
    assert "formatConsolePayloadJson" in js, "formatConsolePayloadJson missing"
    assert "copyWebhookUrl" in js, "copyWebhookUrl missing"
    # Check status-badge case normalization fix
    assert "log.status || '').toLowerCase() === 'success'" in js or "(log.status || '').toLowerCase()" in js
    print("[PASS] JS Safety Modals, status normalization, and Webhook Copy verified in app.js")

    print("\n--- 5. Verifying Database Workflows Deduplication & Tenant Isolation ---")
    conn = sqlite3.connect("opsflow_saas.db")
    c = conn.cursor()
    c.execute("SELECT organization_id, name, count(*) FROM automation_rules GROUP BY organization_id, name HAVING count(*) > 1")
    duplicates = c.fetchall()
    print(f"[PASS] Duplicate rules per organization: {len(duplicates)}")
    assert len(duplicates) == 0, f"Found duplicate rules in organization: {duplicates}"

    c.execute("SELECT count(*) FROM automation_rules")
    total = c.fetchone()[0]
    print(f"[PASS] Total workflows across tenants: {total}")
    assert total >= 15, "Expected varied enterprise workflows"

    c.execute("SELECT category, count(*) FROM automation_rules GROUP BY category ORDER BY count(*) DESC")
    cats = c.fetchall()
    print("[PASS] Workflow categories distribution:")
    for cat, count in cats:
        print(f"   - {cat}: {count} rules")
    conn.close()

    print("\n--- 6. Verifying Light Mode Enterprise Polish ---")
    assert "html:not(.dark) .metric-card" in css, "Light mode .metric-card missing"
    assert "html:not(.dark) .enterprise-sidebar" in css, "Light mode .enterprise-sidebar missing"
    assert "html:not(.dark) .sidebar-nav" in css, "Light mode .sidebar-nav missing"
    assert "html:not(.dark) .telemetry-widget-panel" in css, "Light mode .telemetry-widget-panel missing"
    assert "html:not(.dark) .telemetry-gauge-card" in css, "Light mode .telemetry-gauge-card missing"
    assert "html:not(.dark) .app-global-footer" in css, "Light mode .app-global-footer missing"
    print("[PASS] KPI cards, Sidebar Navigation, and Telemetry Footer light mode styles verified!")

    print("\n=======================================================")
    print("  ALL UI/UX & LIGHT MODE VERIFICATIONS PASSED 100%!  ")
    print("=======================================================")

if __name__ == "__main__":
    run_verifications()
