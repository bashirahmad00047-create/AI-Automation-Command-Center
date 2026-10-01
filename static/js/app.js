/**
 * OpsFlow Cloud Enterprise Frontend Application Controller
 * Handles Multi-Tenancy, RBAC Persona switching, Visual Workflow Studio,
 * Inbound Webhooks, NLP Incident Triage, Execution Forensics,
 * Incident Management, Scoped API Keys, and Team Directory.
 */

// Application State
const state = {
    currentTab: 'dashboard',
    rules: [],
    logs: [],
    blueprints: [],
    notifications: [],
    incidents: [],
    webhooks: [],
    apiKeys: [],
    teamMembers: [],
    auditLogs: [],
    organizations: [],
    currentOrg: null,
    currentUser: null,
    userRole: 'admin',
    selectedCategory: 'All',
    selectedLogStatus: 'all',
    selectedIncidentStatus: 'all',
    engineRunning: true
};

// ==========================================
// INITIALIZATION & REAL-TIME EVENT LOOPS
// ==========================================

document.addEventListener('DOMContentLoaded', () => {
    initClock();
    initAuthAndTenancy();
    refreshAllData();

    // Telemetry and status poll (every 2.5 seconds)
    setInterval(pollTelemetry, 2500);

    // Event stream & notifications poll (every 5 seconds)
    setInterval(pollNotifications, 5000);
});

function initClock() {
    function updateClock() {
        const now = new Date();
        const clockEl = document.getElementById('hudClock');
        if (clockEl) {
            clockEl.textContent = now.toTimeString().split(' ')[0];
        }
    }
    updateClock();
    setInterval(updateClock, 1000);
}

async function initAuthAndTenancy() {
    try {
        let res = await fetch('/api/v1/auth/me');
        if (!res.ok) {
            // Auto-authenticate as primary demo admin persona for seamless experience
            const loginRes = await fetch('/api/v1/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: 'admin@opsflow.io', password: 'AdminSecure2026!' })
            });
            if (loginRes.ok) {
                res = await fetch('/api/v1/auth/me');
            }
        }
        if (res.ok) {
            const data = await res.json();
            state.currentUser = data.user;
            state.currentOrg = data.current_organization || data.organization;
            state.userRole = data.role || 'admin';
            updateUserBadgeUI();
        }
        loadOrganizationsList();
    } catch (e) {
        console.error('Failed to load user/org state:', e);
    }
}

async function loadOrganizationsList() {
    try {
        const res = await fetch('/api/v1/organizations');
        if (!res.ok) return;
        const data = await res.json();
        state.organizations = data.organizations || [];

        const select = document.getElementById('workspaceSelect');
        if (select && state.organizations.length > 0) {
            select.innerHTML = '';
            state.organizations.forEach(org => {
                const opt = document.createElement('option');
                opt.value = org.id;
                opt.textContent = `${org.name} (${org.plan_tier.toUpperCase()})`;
                if (state.currentOrg && org.id === state.currentOrg.id) {
                    opt.selected = true;
                }
                select.appendChild(opt);
            });
        }
    } catch (e) {
        console.error('Failed to load orgs list:', e);
    }
}

function updateUserBadgeUI() {
    const nameEl = document.getElementById('currentUserName');
    const badgeEl = document.getElementById('currentUserRoleBadge');

    if (state.currentUser && nameEl) {
        nameEl.textContent = state.currentUser.full_name;
    }
    if (badgeEl) {
        badgeEl.textContent = state.userRole.toUpperCase();
        badgeEl.className = `role-badge ${state.userRole.toLowerCase()}`;
    }
}

async function handleWorkspaceChange(orgId) {
    try {
        const res = await fetch('/api/v1/organizations/switch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ organization_id: orgId })
        });
        const data = await res.json();
        if (res.ok) {
            state.currentOrg = data.organization;
            state.userRole = data.role || 'admin';
            updateUserBadgeUI();
            showToast(`Switched workspace to ${data.organization.name}`, 'success');
            refreshAllData();
        } else {
            showToast(data.error || 'Failed to switch workspace', 'error');
        }
    } catch (e) {
        showToast(`Workspace switch error: ${e.message}`, 'error');
    }
}

function refreshAllData() {
    pollTelemetry();
    loadRules();
    loadBlueprints();
    loadExecutionLogs();
    loadIncidents();
    loadWebhooks();
    loadApiKeys();
    loadTeamAndAudits();
    pollNotifications();
}

// ==========================================
// NAVIGATION & TABS
// ==========================================

function switchTab(tabId) {
    state.currentTab = tabId;

    document.querySelectorAll('.hud-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));

    const tabButtons = document.querySelectorAll('.hud-tab');
    tabButtons.forEach(btn => {
        if (btn.getAttribute('onclick') && btn.getAttribute('onclick').includes(tabId)) {
            btn.classList.add('active');
        }
    });

    const activePanel = document.getElementById(`tab-${tabId}`);
    if (activePanel) {
        activePanel.classList.add('active');
    }

    if (tabId === 'rules') loadRules();
    if (tabId === 'leads') loadLeads();
    if (tabId === 'webhooks') loadWebhooks();
    if (tabId === 'logs') loadExecutionLogs();
    if (tabId === 'incidents') loadIncidents();
    if (tabId === 'apikeys') loadApiKeys();
    if (tabId === 'team') loadTeamAndAudits();
}

// ==========================================
// TELEMETRY & SYSTEM HEALTH
// ==========================================

async function pollTelemetry() {
    try {
        const res = await fetch('/api/v1/system/telemetry');
        if (!res.ok) return;
        const data = await res.json();

        state.engineRunning = data.engine_online;
        const badge = document.getElementById('engineStatusBadge');
        const toggleBtnLabel = document.getElementById('toggleEngineLabel');

        if (state.engineRunning) {
            badge.innerHTML = '<span class="status-dot green pulse"></span><span class="status-text">ENGINE ONLINE</span>';
            if (toggleBtnLabel) toggleBtnLabel.textContent = 'Pause Engine';
        } else {
            badge.innerHTML = '<span class="status-dot red"></span><span class="status-text">ENGINE PAUSED</span>';
            if (toggleBtnLabel) toggleBtnLabel.textContent = 'Resume Engine';
        }

        const stats = data.stats || {};
        document.getElementById('statActiveRules').textContent = `${stats.active_rules || 0} / ${stats.total_rules || 0}`;
        document.getElementById('statTotalRules').textContent = `${stats.total_rules || 0} Total Configured`;
        document.getElementById('statTotalExecutions').textContent = stats.total_executions || 0;
        document.getElementById('statSuccessExecutions').textContent = `${stats.successful_executions || 0} Successful Dispatches`;
        document.getElementById('statSuccessRate').textContent = `${stats.success_rate || 100}%`;
        document.getElementById('statOpenIncidents').textContent = stats.open_alerts || 0;
        document.getElementById('statAckIncidents').textContent = `${stats.acknowledged_alerts || 0} Acknowledged`;
        document.getElementById('statActiveWebhooks').textContent = stats.active_webhooks || 0;

        const highLeadsEl = document.getElementById('statHighPriorityLeads');
        if (highLeadsEl) highLeadsEl.textContent = stats.high_priority_leads || 0;
        const totalLeadsEl = document.getElementById('statTotalLeads');
        if (totalLeadsEl) totalLeadsEl.textContent = `${stats.total_leads || 0} Total Inquiries`;
        const tabLeadEl = document.getElementById('tabLeadCount');
        if (tabLeadEl) tabLeadEl.textContent = stats.total_leads || 0;

        const telem = data.telemetry || {};
        document.getElementById('statUptime').textContent = telem.uptime_formatted || '0s';

        const cpu = Math.round(telem.cpu_percent || 0);
        const ram = Math.round(telem.memory_percent || 0);
        const disk = Math.round(telem.disk_percent || 0);

        document.getElementById('telemCpuVal').textContent = `${cpu}%`;
        document.getElementById('telemCpuBar').style.width = `${Math.min(100, cpu)}%`;

        document.getElementById('telemRamVal').textContent = `${ram}%`;
        document.getElementById('telemRamBar').style.width = `${Math.min(100, ram)}%`;
        document.getElementById('telemRamGb').textContent = `${telem.memory_used_gb || 0} / ${telem.memory_total_gb || 0} GB`;

        document.getElementById('telemDiskVal').textContent = `${disk}%`;
        document.getElementById('telemDiskBar').style.width = `${Math.min(100, disk)}%`;
        document.getElementById('telemDiskGb').textContent = `${telem.disk_used_gb || 0} / ${telem.disk_total_gb || 0} GB`;
    } catch (e) {
        console.error('Failed to poll telemetry:', e);
    }
}

async function toggleEngineState() {
    try {
        const res = await fetch('/api/v1/system/engine/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ online: !state.engineRunning })
        });
        const data = await res.json();
        if (res.ok) {
            state.engineRunning = data.engine_running;
            showToast(`Automation Engine is now ${state.engineRunning ? 'ONLINE' : 'PAUSED'}`, 'info');
            pollTelemetry();
        } else {
            showToast(data.error || 'Failed to toggle engine', 'error');
        }
    } catch (e) {
        showToast(`Engine toggle error: ${e.message}`, 'error');
    }
}

// ==========================================
// WORKFLOW RULES STUDIO (CRUD)
// ==========================================

async function loadRules() {
    try {
        let url = '/api/v1/rules';
        if (state.selectedCategory !== 'All') {
            url += `?category=${encodeURIComponent(state.selectedCategory)}`;
        }
        const res = await fetch(url);
        if (!res.ok) return;
        const data = await res.json();
        state.rules = data.rules || [];
        renderRulesTable();
    } catch (e) {
        console.error('Failed to load rules:', e);
    }
}

function filterRulesCategory(category, btn) {
    state.selectedCategory = category;
    document.querySelectorAll('.filter-group .filter-chip').forEach(c => c.classList.remove('active'));
    if (btn) btn.classList.add('active');
    loadRules();
}

function renderRulesTable() {
    const tbody = document.getElementById('rulesTableBody');
    if (!tbody) return;

    if (state.rules.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="empty-cell">No automation rules configured in this workspace.</td></tr>';
        return;
    }

    tbody.innerHTML = state.rules.map(rule => {
        const isEnabled = rule.enabled === 1 || rule.enabled === true;
        const trigger = rule.trigger || {};
        const triggerDesc = trigger.event_name ? `${trigger.type || 'event'}:${trigger.event_name}` : (trigger.type || 'event');
        const isViewer = state.userRole === 'viewer';

        return `
            <tr>
                <td>
                    <button class="toggle-switch ${isEnabled ? 'on' : 'off'}" 
                            onclick="toggleRuleEnabled('${rule.id}')"
                            title="Toggle Rule State" ${isViewer ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : ''}>
                        <span class="toggle-slider"></span>
                    </button>
                </td>
                <td>
                    <div style="font-weight: 600; color: var(--text-primary);">${escapeHtml(rule.name)}</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted);">${escapeHtml(rule.description || '')}</div>
                </td>
                <td><span class="category-chip ${rule.category ? rule.category.toLowerCase() : 'system'}">${rule.category || 'System'}</span></td>
                <td><code style="font-size: 0.75rem; color: var(--cyan-glow);">${escapeHtml(triggerDesc)}</code></td>
                <td><span style="font-family: var(--font-mono); font-size: 0.8rem;">${rule.priority || 10}</span></td>
                <td><span style="font-family: var(--font-mono); font-size: 0.8rem;">${rule.cooldown_seconds || 0}s</span></td>
                <td><span style="font-family: var(--font-mono); font-size: 0.85rem; font-weight:700;">${rule.execution_count || 0}</span></td>
                <td style="font-size: 0.75rem; color: var(--text-muted);">${rule.last_triggered || 'Never'}</td>
                <td>
                    <div class="action-btn-row">
                        <button class="action-btn cyan-btn" onclick="runRuleTest('${rule.id}')" title="Live Execute">▶</button>
                        <button class="action-btn purple-btn" onclick="runDryRunTest('${rule.id}')" title="Dry Run / Simulation (Zero Side Effects)">🧪</button>
                        <button class="action-btn" style="background:rgba(255,255,255,0.08); color:#e2e8f0;" onclick="duplicateRule('${rule.id}')" title="Duplicate Workflow" ${isViewer ? 'disabled style="opacity:0.5;"' : ''}>📋</button>
                        <button class="action-btn amber-btn" onclick="editRule('${rule.id}')" title="Edit Rule" ${isViewer ? 'disabled style="opacity:0.5;"' : ''}>✏️</button>
                        <button class="action-btn red-btn" onclick="deleteRule('${rule.id}')" title="Delete Rule" ${isViewer ? 'disabled style="opacity:0.5;"' : ''}>🗑️</button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

async function toggleRuleEnabled(ruleId) {
    try {
        const res = await fetch(`/api/v1/rules/${ruleId}/toggle`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const data = await res.json();
        if (res.ok) {
            showToast(`Rule is now ${data.enabled ? 'Enabled' : 'Disabled'}`, 'info');
            loadRules();
            pollTelemetry();
        } else {
            showToast(data.error || 'Failed to toggle rule', 'error');
        }
    } catch (e) {
        showToast(`Toggle error: ${e.message}`, 'error');
    }
}

async function runRuleTest(ruleId) {
    try {
        const res = await fetch(`/api/v1/rules/${ruleId}/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ payload: { test_source: "studio_manual_trigger", timestamp: new Date().toISOString() } })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(`Rule executed: ${data.status.toUpperCase()}`, 'success');
            loadExecutionLogs();
            loadRules();
        } else {
            showToast(data.error || 'Execution failed', 'error');
        }
    } catch (e) {
        showToast(`Execution error: ${e.message}`, 'error');
    }
}

async function deleteRule(ruleId) {
    if (!confirm(`Are you sure you want to delete workflow rule '${ruleId}'?`)) return;
    try {
        const res = await fetch(`/api/v1/rules/${ruleId}`, { method: 'DELETE' });
        const data = await res.json();
        if (res.ok) {
            showToast('Workflow rule deleted.', 'info');
            loadRules();
            pollTelemetry();
        } else {
            showToast(data.error || 'Failed to delete rule', 'error');
        }
    } catch (e) {
        showToast(`Delete error: ${e.message}`, 'error');
    }
}

async function duplicateRule(ruleId) {
    try {
        const res = await fetch(`/api/v1/workflows/${ruleId}/duplicate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await res.json();
        if (res.ok) {
            showToast(`Workflow duplicated: '${data.workflow.name}'`, 'success');
            loadRules();
            pollTelemetry();
        } else {
            showToast(data.error || 'Failed to duplicate workflow', 'error');
        }
    } catch (e) {
        showToast(`Duplicate error: ${e.message}`, 'error');
    }
}

async function runDryRunTest(ruleId) {
    try {
        const res = await fetch(`/api/v1/workflows/${ruleId}/execute`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dry_run: true, payload: { simulation_test: true, timestamp: new Date().toISOString() } })
        });
        const data = await res.json();
        if (res.ok) {
            showToast('Dry Run simulated with ZERO side effects!', 'success');
            alert(
                `🧪 DRY RUN SIMULATION TRACE (ZERO SIDE EFFECTS)\n` +
                `--------------------------------------------------\n` +
                `Workflow: ${data.workflow_name || data.rule_name || ruleId}\n` +
                `Status: ${data.status.toUpperCase()}\n` +
                `Condition Matched: ${data.matched ? 'YES' : 'NO'}\n` +
                `Execution Duration: ${data.duration_ms || 0}ms\n` +
                `Notice: DRY RUN / ZERO SIDE EFFECTS\n\n` +
                `Action Results (Simulated): \n` +
                JSON.stringify(data.action_results || data.steps_trace || [], null, 2)
            );
        } else {
            showToast(data.error || 'Dry run simulation failed', 'error');
        }
    } catch (e) {
        showToast(`Simulation error: ${e.message}`, 'error');
    }
}

// Visual Rule Builder Modal
function openNewRuleModal() {
    if (state.userRole === 'viewer') {
        showToast('Viewer role cannot create workflows. Switch to Operator or Admin persona.', 'warning');
        return;
    }
    document.getElementById('modalTitle').textContent = 'Create New Automation Workflow';
    document.getElementById('formRuleId').value = '';
    document.getElementById('formRuleName').value = '';
    document.getElementById('formRuleDescription').value = '';
    document.getElementById('formRuleCategory').value = 'System';
    document.getElementById('formRulePriority').value = '10';
    document.getElementById('formRuleCooldown').value = '0';
    document.getElementById('formRuleEnabled').value = '1';
    document.getElementById('formTriggerType').value = 'event';
    document.getElementById('formTriggerEvent').value = 'system.metrics';

    document.getElementById('conditionsList').innerHTML = '';
    addConditionRow('payload.cpu_percent', '>', '85');

    document.getElementById('actionsList').innerHTML = '';
    addActionRow('notification');

    document.getElementById('ruleModal').style.display = 'flex';
}

function editRule(ruleId) {
    const rule = state.rules.find(r => r.id === ruleId);
    if (!rule) return;

    document.getElementById('modalTitle').textContent = `Edit Workflow: ${rule.name}`;
    document.getElementById('formRuleId').value = rule.id;
    document.getElementById('formRuleName').value = rule.name;
    document.getElementById('formRuleDescription').value = rule.description || '';
    document.getElementById('formRuleCategory').value = rule.category || 'System';
    document.getElementById('formRulePriority').value = rule.priority || 10;
    document.getElementById('formRuleCooldown').value = rule.cooldown_seconds || 0;
    document.getElementById('formRuleEnabled').value = (rule.enabled === 1 || rule.enabled === true) ? '1' : '0';

    const trigger = rule.trigger || {};
    document.getElementById('formTriggerType').value = trigger.type || 'event';
    document.getElementById('formTriggerEvent').value = trigger.event_name || 'system.metrics';

    // Populate conditions
    const condList = document.getElementById('conditionsList');
    condList.innerHTML = '';
    const condGroup = rule.condition || {};
    document.getElementById('formConditionLogic').value = condGroup.logic || 'AND';
    const conditions = condGroup.conditions || [];
    if (conditions.length > 0) {
        conditions.forEach(c => addConditionRow(c.field, c.operator, c.value));
    } else {
        addConditionRow();
    }

    // Populate actions
    const actList = document.getElementById('actionsList');
    actList.innerHTML = '';
    const actions = rule.actions || [];
    if (actions.length > 0) {
        actions.forEach(a => addActionRow(a.type, a.params));
    } else {
        addActionRow('notification');
    }

    document.getElementById('ruleModal').style.display = 'flex';
}

function closeRuleModal() {
    document.getElementById('ruleModal').style.display = 'none';
}

function addConditionRow(field = '', operator = '==', val = '') {
    const list = document.getElementById('conditionsList');
    const row = document.createElement('div');
    row.className = 'condition-row';
    row.innerHTML = `
        <input type="text" class="hud-input flex-2 cond-field" placeholder="payload.field or nlp.urgency" value="${escapeHtml(String(field))}" required>
        <select class="hud-input flex-1 cond-op">
            <option value="==" ${operator === '==' ? 'selected' : ''}>== (Equals)</option>
            <option value="!=" ${operator === '!=' ? 'selected' : ''}>!= (Not Equals)</option>
            <option value=">" ${operator === '>' ? 'selected' : ''}>&gt; (Greater than)</option>
            <option value=">=" ${operator === '>=' ? 'selected' : ''}>&gt;= (Greater or Equal)</option>
            <option value="<" ${operator === '<' ? 'selected' : ''}>&lt; (Less than)</option>
            <option value="<=" ${operator === '<=' ? 'selected' : ''}>&lt;= (Less or Equal)</option>
            <option value="contains" ${operator === 'contains' ? 'selected' : ''}>contains</option>
            <option value="in_list" ${operator === 'in_list' ? 'selected' : ''}>in list (CSV)</option>
        </select>
        <input type="text" class="hud-input flex-2 cond-val" placeholder="Comparison Target Value" value="${escapeHtml(String(val))}" required>
        <button type="button" class="remove-btn" onclick="this.parentElement.remove()">✕</button>
    `;
    list.appendChild(row);
}

function addActionRow(type = 'notification', params = null) {
    const list = document.getElementById('actionsList');
    const row = document.createElement('div');
    row.className = 'action-row';

    params = params || {};
    let paramsHtml = '';
    if (type === 'notification') {
        paramsHtml = `
            <input type="text" class="hud-input flex-2 act-title" placeholder="Alert Title" value="${escapeHtml(params.title || 'Incident Alert')}">
            <select class="hud-input flex-1 act-severity">
                <option value="critical" ${params.severity === 'critical' ? 'selected' : ''}>Critical</option>
                <option value="high" ${params.severity === 'high' ? 'selected' : ''}>High</option>
                <option value="warning" ${params.severity === 'warning' ? 'selected' : ''}>Warning</option>
                <option value="info" ${params.severity === 'info' || !params.severity ? 'selected' : ''}>Info</option>
            </select>
        `;
    } else if (type === 'webhook_call') {
        paramsHtml = `
            <input type="text" class="hud-input flex-3 act-url" placeholder="https://api.internal/v1/webhook" value="${escapeHtml(params.url || '')}">
            <select class="hud-input flex-1 act-method">
                <option value="POST" ${params.method === 'POST' ? 'selected' : ''}>POST</option>
                <option value="GET" ${params.method === 'GET' ? 'selected' : ''}>GET</option>
                <option value="PUT" ${params.method === 'PUT' ? 'selected' : ''}>PUT</option>
            </select>
        `;
    } else if (type === 'database_record') {
        paramsHtml = `
            <input type="text" class="hud-input flex-2 act-entity" placeholder="Entity (lead)" value="${escapeHtml(params.entity || 'lead')}">
            <select class="hud-input flex-1 act-status">
                <option value="qualified" ${params.status === 'qualified' ? 'selected' : ''}>Qualified</option>
                <option value="new" ${params.status === 'new' ? 'selected' : ''}>New</option>
                <option value="follow_up" ${params.status === 'follow_up' ? 'selected' : ''}>Follow Up</option>
            </select>
        `;
    } else if (type === 'email_draft') {
        paramsHtml = `
            <input type="text" class="hud-input flex-2 act-template" placeholder="Template (e.g. sales_discovery)" value="${escapeHtml(params.template || 'sales_discovery')}">
            <input type="text" class="hud-input flex-2 act-recipient" placeholder="{{ payload.email }}" value="${escapeHtml(params.recipient || '{{ payload.email }}')}">
        `;
    } else if (type === 'assign_department') {
        paramsHtml = `
            <select class="hud-input flex-3 act-dept">
                <option value="auto" ${params.department === 'auto' ? 'selected' : ''}>AI Auto Smart Routing</option>
                <option value="Sales" ${params.department === 'Sales' ? 'selected' : ''}>Sales (Hot Leads)</option>
                <option value="Support" ${params.department === 'Support' ? 'selected' : ''}>Support</option>
                <option value="Priority Support" ${params.department === 'Priority Support' ? 'selected' : ''}>Priority Support</option>
                <option value="Security Operations" ${params.department === 'Security Operations' ? 'selected' : ''}>Security Operations</option>
            </select>
        `;
    } else {
        paramsHtml = `
            <input type="text" class="hud-input flex-3 act-msg" placeholder="Log / Diagnostic Message" value="${escapeHtml(params.message || '')}">
        `;
    }

    row.innerHTML = `
        <select class="hud-input flex-1 act-type" onchange="updateActionParamsUI(this)">
            <option value="notification" ${type === 'notification' ? 'selected' : ''}>In-App Incident Alert</option>
            <option value="database_record" ${type === 'database_record' ? 'selected' : ''}>CRM Lead / DB Record</option>
            <option value="email_draft" ${type === 'email_draft' ? 'selected' : ''}>AI Email Response Draft</option>
            <option value="assign_department" ${type === 'assign_department' ? 'selected' : ''}>Smart Dept Route</option>
            <option value="webhook_call" ${type === 'webhook_call' ? 'selected' : ''}>Outbound HTTP Webhook</option>
            <option value="log_entry" ${type === 'log_entry' ? 'selected' : ''}>Diagnostic Log Entry</option>
            <option value="email_dispatch" ${type === 'email_dispatch' ? 'selected' : ''}>Simulated Email Dispatch</option>
            <option value="file_append" ${type === 'file_append' ? 'selected' : ''}>File Storage Append</option>
        </select>
        <div class="action-params-container flex-3" style="display:flex; gap:6px;">
            ${paramsHtml}
        </div>
        <button type="button" class="remove-btn" onclick="this.parentElement.remove()">✕</button>
    `;
    list.appendChild(row);
}

function updateActionParamsUI(selectEl) {
    const type = selectEl.value;
    const container = selectEl.parentElement.querySelector('.action-params-container');
    if (type === 'notification') {
        container.innerHTML = `
            <input type="text" class="hud-input flex-2 act-title" placeholder="Alert Title" value="System Alert">
            <select class="hud-input flex-1 act-severity">
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="warning">Warning</option>
                <option value="info" selected>Info</option>
            </select>
        `;
    } else if (type === 'webhook_call') {
        container.innerHTML = `
            <input type="text" class="hud-input flex-3 act-url" placeholder="https://api.internal/v1/webhook" value="">
            <select class="hud-input flex-1 act-method"><option value="POST">POST</option><option value="GET">GET</option></select>
        `;
    } else if (type === 'database_record') {
        container.innerHTML = `
            <input type="text" class="hud-input flex-2 act-entity" placeholder="Entity (lead)" value="lead">
            <select class="hud-input flex-1 act-status"><option value="qualified">Qualified</option><option value="new">New</option><option value="follow_up">Follow Up</option></select>
        `;
    } else if (type === 'email_draft') {
        container.innerHTML = `
            <input type="text" class="hud-input flex-2 act-template" placeholder="Template (e.g. sales_discovery)" value="sales_discovery">
            <input type="text" class="hud-input flex-2 act-recipient" placeholder="{{ payload.email }}" value="{{ payload.email }}">
        `;
    } else if (type === 'assign_department') {
        container.innerHTML = `
            <select class="hud-input flex-3 act-dept">
                <option value="auto">AI Auto Smart Routing</option>
                <option value="Sales">Sales (Hot Leads)</option>
                <option value="Support">Support</option>
                <option value="Priority Support">Priority Support</option>
                <option value="Security Operations">Security Operations</option>
            </select>
        `;
    } else {
        container.innerHTML = `<input type="text" class="hud-input flex-3 act-msg" placeholder="Message or Diagnostic text" value="">`;
    }
}

async function saveRuleForm(e) {
    e.preventDefault();
    const ruleId = document.getElementById('formRuleId').value;
    const isEdit = Boolean(ruleId);

    // Build conditions
    const condRows = document.querySelectorAll('.condition-row');
    const conditions = [];
    condRows.forEach(r => {
        const field = r.querySelector('.cond-field').value.trim();
        const operator = r.querySelector('.cond-op').value;
        let val = r.querySelector('.cond-val').value.trim();
        if (!isNaN(val) && val !== '') val = Number(val);
        conditions.push({ field, operator, value: val });
    });

    // Build actions
    const actRows = document.querySelectorAll('.action-row');
    const actions = [];
    actRows.forEach(r => {
        const type = r.querySelector('.act-type').value;
        const params = {};
        if (type === 'notification') {
            const titleInput = r.querySelector('.act-title');
            const sevInput = r.querySelector('.act-severity');
            params.title = titleInput ? titleInput.value.trim() : 'Alert';
            params.severity = sevInput ? sevInput.value : 'info';
            params.message = `Triggered automation action: ${params.title}`;
        } else if (type === 'webhook_call') {
            const urlInput = r.querySelector('.act-url');
            const methodInput = r.querySelector('.act-method');
            params.url = urlInput ? urlInput.value.trim() : 'https://api.internal/webhook';
            params.method = methodInput ? methodInput.value : 'POST';
        } else if (type === 'database_record') {
            const entityInput = r.querySelector('.act-entity');
            const statusInput = r.querySelector('.act-status');
            params.entity = entityInput ? entityInput.value.trim() : 'lead';
            params.status = statusInput ? statusInput.value : 'qualified';
        } else if (type === 'email_draft') {
            const tmplInput = r.querySelector('.act-template');
            const recipInput = r.querySelector('.act-recipient');
            params.template = tmplInput ? tmplInput.value.trim() : 'sales_discovery';
            params.recipient = recipInput ? recipInput.value.trim() : '{{ payload.email }}';
        } else if (type === 'assign_department') {
            const deptInput = r.querySelector('.act-dept');
            params.department = deptInput ? deptInput.value : 'auto';
        } else {
            const msgInput = r.querySelector('.act-msg');
            params.message = msgInput ? msgInput.value.trim() : 'Rule action executed';
        }
        actions.push({ type, params });
    });

    const payload = {
        name: document.getElementById('formRuleName').value.trim(),
        description: document.getElementById('formRuleDescription').value.trim(),
        category: document.getElementById('formRuleCategory').value,
        priority: parseInt(document.getElementById('formRulePriority').value, 10),
        cooldown_seconds: parseInt(document.getElementById('formRuleCooldown').value, 10),
        enabled: document.getElementById('formRuleEnabled').value === '1' ? 1 : 0,
        trigger: {
            type: document.getElementById('formTriggerType').value,
            event_name: document.getElementById('formTriggerEvent').value.trim()
        },
        condition: {
            logic: document.getElementById('formConditionLogic').value,
            conditions: conditions
        },
        actions: actions
    };

    try {
        const url = isEdit ? `/api/v1/rules/${ruleId}` : '/api/v1/rules';
        const method = isEdit ? 'PUT' : 'POST';
        let res = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (res.status === 401) {
            // Automatically re-authenticate as default admin persona and retry
            await quickLoginPersona('admin@opsflow.io', 'AdminSecure2026!');
            res = await fetch(url, {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        }

        const data = await res.json();
        if (res.ok) {
            showToast(`Workflow '${payload.name}' saved successfully.`, 'success');
            closeRuleModal();
            loadRules();
            pollTelemetry();
        } else if (res.status === 403) {
            showToast(data.error || "Permission denied: Current role cannot edit workflows. Switch to ADMIN at top header.", 'error');
        } else {
            showToast(data.error || 'Failed to save workflow', 'error');
        }
    } catch (err) {
        showToast(`Save error: ${err.message}`, 'error');
    }
}

// ==========================================
// INBOUND WEBHOOKS & MANUAL EVENT GATEWAY
// ==========================================

async function loadWebhooks() {
    try {
        const res = await fetch('/api/v1/webhooks');
        if (!res.ok) return;
        const data = await res.json();
        state.webhooks = data.webhooks || [];
        renderWebhooksTable();
    } catch (e) {
        console.error('Failed to load webhooks:', e);
    }
}

function renderWebhooksTable() {
    const tbody = document.getElementById('webhooksTableBody');
    if (!tbody) return;

    if (state.webhooks.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-cell">No inbound webhooks configured for this workspace.</td></tr>';
        return;
    }

    tbody.innerHTML = state.webhooks.map(wh => {
        return `
            <tr>
                <td><strong>${escapeHtml(wh.name)}</strong></td>
                <td>
                    <div style="display:flex; align-items:center; gap:6px;">
                        <code style="font-size:0.75rem; color:var(--emerald-glow);">${escapeHtml(wh.webhook_url)}</code>
                        <button class="copy-btn" onclick="copyWebhookUrl('${wh.webhook_url}')">Copy</button>
                    </div>
                </td>
                <td><span style="font-size:0.8rem; color:var(--text-muted);">${wh.target_rule_id || 'All Matching Rules'}</span></td>
                <td><span style="font-weight:700; font-family:var(--font-mono);">${wh.request_count || 0}</span></td>
                <td style="font-size:0.75rem; color:var(--text-muted);">${wh.last_received_at || 'Never'}</td>
                <td>
                    <button class="action-btn red-btn" onclick="deleteWebhook('${wh.id}')" title="Delete Webhook">🗑️</button>
                </td>
            </tr>
        `;
    }).join('');
}

function copyWebhookUrl(url) {
    navigator.clipboard.writeText(url).then(() => {
        showToast('Webhook Ingestion URL copied to clipboard!', 'success');
    });
}

function openNewWebhookModal() {
    document.getElementById('newWebhookName').value = '';
    document.getElementById('newWebhookSecret').value = '';
    document.getElementById('newWebhookModal').style.display = 'flex';
}

function closeNewWebhookModal() {
    document.getElementById('newWebhookModal').style.display = 'none';
}

async function submitNewWebhook(e) {
    e.preventDefault();
    const name = document.getElementById('newWebhookName').value.trim();
    const secret = document.getElementById('newWebhookSecret').value.trim();

    try {
        const res = await fetch('/api/v1/webhooks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, secret_token: secret })
        });
        const data = await res.json();
        if (res.ok) {
            showToast('Inbound webhook created successfully!', 'success');
            closeNewWebhookModal();
            loadWebhooks();
            pollTelemetry();
        } else {
            showToast(data.error || 'Failed to create webhook', 'error');
        }
    } catch (err) {
        showToast(`Webhook create error: ${err.message}`, 'error');
    }
}

async function deleteWebhook(id) {
    if (!confirm('Are you sure you want to delete this webhook connector?')) return;
    try {
        const res = await fetch(`/api/v1/webhooks/${id}`, { method: 'DELETE' });
        const data = await res.json();
        if (res.ok) {
            showToast('Webhook connector deleted.', 'info');
            loadWebhooks();
            pollTelemetry();
        } else {
            showToast(data.error || 'Failed to delete webhook', 'error');
        }
    } catch (err) {
        showToast(`Delete error: ${err.message}`, 'error');
    }
}

function preloadPayload(type) {
    const nameInput = document.getElementById('manualEventName');
    const payloadInput = document.getElementById('manualEventPayload');

    if (type === 'cpu_surge') {
        nameInput.value = 'system.metrics';
        payloadInput.value = JSON.stringify({ cpu_percent: 94.2, memory_percent: 86.0, host: 'prod-k8s-node-01' }, null, 2);
    } else if (type === 'failed_auth') {
        nameInput.value = 'auth.failed';
        payloadInput.value = JSON.stringify({ ip: '198.51.100.88', attempts: 5, user: 'root' }, null, 2);
    } else if (type === 'backup_done') {
        nameInput.value = 'backup.completed';
        payloadInput.value = JSON.stringify({ status: 'success', database: 'customer_orders_db', size_mb: 245.5 }, null, 2);
    } else if (type === 'api_503') {
        nameInput.value = 'api.error';
        payloadInput.value = JSON.stringify({ status_code: 503, endpoint: '/v1/billing/charge', duration_ms: 450 }, null, 2);
    }
}

async function handleManualEventDispatch(e) {
    e.preventDefault();
    const eventName = document.getElementById('manualEventName').value.trim();
    const dryRun = document.getElementById('manualEventDryRun').checked;
    let payload = {};

    try {
        payload = JSON.parse(document.getElementById('manualEventPayload').value);
    } catch (err) {
        showToast('Invalid JSON in payload field', 'error');
        return;
    }

    try {
        const res = await fetch('/api/v1/events/dispatch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ event_name: eventName, payload: payload, dry_run: dryRun })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(`Event '${eventName}' dispatched (${dryRun ? 'DRY-RUN' : 'LIVE'})`, 'success');
            const outBox = document.getElementById('manualEventOutput');
            const outJson = document.getElementById('manualEventOutputJson');
            outBox.style.display = 'block';
            outJson.textContent = JSON.stringify(data.result, null, 2);

            loadExecutionLogs();
            loadIncidents();
            pollTelemetry();
        } else {
            showToast(data.error || 'Failed to dispatch event', 'error');
        }
    } catch (err) {
        showToast(`Dispatch error: ${err.message}`, 'error');
    }
}

// ==========================================
// HEURISTIC NLP INCIDENT TRIAGE
// ==========================================

function setNlpSample(idx) {
    const input = document.getElementById('nlpInputText');
    if (idx === 1) {
        input.value = "CRITICAL: Server load surge detected! High CPU spike at 94% on prod-worker-08, system unresponsive.";
    } else if (idx === 2) {
        input.value = "Security Alert: Multiple unauthorized brute-force login attempts detected from host IP 192.168.1.150.";
    } else if (idx === 3) {
        input.value = "Gateway reported 502 Bad Gateway and 503 Service Unavailable on payment checkout route.";
    } else if (idx === 4) {
        input.value = "Snapshot finished successfully for orders-vault-db with verified dump size of 512 MB.";
    }
}

async function runNlpTriage(dryRun) {
    const text = document.getElementById('nlpInputText').value.trim();
    if (!text) {
        showToast('Please enter an incident text prompt', 'warning');
        return;
    }

    const container = document.getElementById('nlpResultContainer');
    container.innerHTML = '<div class="empty-cell">Evaluating heuristic NLP parse trees...</div>';

    try {
        const res = await fetch('/api/v1/nlp/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, dry_run: dryRun })
        });
        const data = await res.json();
        if (res.ok) {
            const nlp = data.nlp;
            const sim = data.simulation || {};
            const executedRules = sim.executed_rules || [];

            let entityBadges = '';
            for (const [key, vals] of Object.entries(nlp.entities || {})) {
                if (vals && vals.length > 0) {
                    vals.forEach(v => {
                        entityBadges += `<span class="category-chip data" style="margin-right:4px;">${key}: ${v}</span>`;
                    });
                }
            }

            container.innerHTML = `
                <div style="background:var(--bg-dark); padding:16px; border-radius:8px; border:1px solid var(--border-color);">
                    <div style="display:flex; justify-content:space-between; margin-bottom:12px;">
                        <div>
                            <span style="font-size:0.75rem; color:var(--text-muted);">CLASSIFIED INTENT:</span>
                            <div style="font-size:1.1rem; font-weight:700; color:var(--cyan-glow);">${nlp.intent.toUpperCase()}</div>
                        </div>
                        <div style="text-align:right;">
                            <span style="font-size:0.75rem; color:var(--text-muted);">URGENCY SCORE:</span>
                            <div style="font-size:1.1rem; font-weight:700; color:${nlp.urgency >= 70 ? 'var(--red-glow)' : 'var(--amber-glow)'};">${nlp.urgency} / 100 [${nlp.severity_level}]</div>
                        </div>
                    </div>

                    <div style="margin-bottom:12px;">
                        <span style="font-size:0.75rem; color:var(--text-muted);">MAPPED INFERRED EVENT:</span>
                        <div><code style="color:var(--emerald-glow);">${data.event_inferred}</code></div>
                    </div>

                    <div style="margin-bottom:12px;">
                        <span style="font-size:0.75rem; color:var(--text-muted);">EXTRACTED OPERATIONAL ENTITIES:</span>
                        <div style="margin-top:4px;">${entityBadges || '<span style="color:var(--text-muted);">None</span>'}</div>
                    </div>

                    <div>
                        <span style="font-size:0.75rem; color:var(--text-muted);">TRIGGERED WORKFLOW ACTIONS (${executedRules.length}):</span>
                        <div style="margin-top:6px;">
                            ${executedRules.map(r => `
                                <div style="display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid var(--border-color); font-size:0.85rem;">
                                    <span>${escapeHtml(r.rule_name)}</span>
                                    <span style="font-weight:700; color:${r.matched ? 'var(--emerald-glow)' : 'var(--text-muted)'};">${r.matched ? 'PASSED & TRIGGERED' : 'CONDITION SKIPPED'}</span>
                                </div>
                            `).join('') || '<div style="color:var(--text-muted);">No rules matched conditions</div>'}
                        </div>
                    </div>
                </div>
            `;
            showToast(`NLP triage complete (${dryRun ? 'DRY-RUN' : 'LIVE'})`, 'success');
            loadExecutionLogs();
            loadIncidents();
            pollTelemetry();
        } else {
            showToast(data.error || 'NLP triage failed', 'error');
        }
    } catch (err) {
        showToast(`NLP error: ${err.message}`, 'error');
    }
}

// ==========================================
// METRICS SIMULATOR
// ==========================================

function updateSimVal(elementId, val) {
    const el = document.getElementById(elementId);
    if (el) el.textContent = val;
}

async function runMetricsSimulation(dryRun) {
    const cpu = parseFloat(document.getElementById('simCpuSlider').value);
    const attempts = parseInt(document.getElementById('simAuthSlider').value, 10);
    const statusCode = parseInt(document.getElementById('simHttpSelect').value, 10);

    const container = document.getElementById('simResultContainer');
    container.innerHTML = '<div class="empty-cell">Evaluating simulation conditions...</div>';

    try {
        const res = await fetch('/api/v1/events/dispatch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                event_name: 'system.metrics',
                payload: { cpu_percent: cpu, attempts: attempts, status_code: statusCode, host: 'simulated-node-01' },
                source: 'metrics_simulator',
                dry_run: dryRun
            })
        });
        const data = await res.json();
        if (res.ok) {
            const rules = data.result.executed_rules || [];
            container.innerHTML = `
                <div style="background:var(--bg-dark); padding:16px; border-radius:8px; border:1px solid var(--border-color);">
                    <div style="display:flex; justify-content:space-between; margin-bottom:12px;">
                        <span>Mode: <strong>${dryRun ? 'DRY-RUN SIMULATION' : 'LIVE DISPATCH'}</strong></span>
                        <span style="color:var(--cyan-glow);">Rules Evaluated: ${rules.length}</span>
                    </div>
                    ${rules.map(r => `
                        <div style="padding:10px 0; border-bottom:1px solid var(--border-color);">
                            <div style="display:flex; justify-content:space-between;">
                                <strong>${escapeHtml(r.rule_name)}</strong>
                                <span style="font-weight:700; color:${r.matched ? 'var(--emerald-glow)' : 'var(--text-muted)'};">${r.matched ? 'PASSED & TRIGGERED' : 'CONDITION SKIPPED'}</span>
                            </div>
                            <div style="font-size:0.8rem; color:var(--text-secondary); margin-top:4px;">
                                ${r.trace && r.trace.length > 0 ? r.trace.map(t => `${t.field} ${t.operator} ${t.target} (Actual: ${t.actual}) -> ${t.passed ? 'PASS' : 'FAIL'}`).join('; ') : ''}
                            </div>
                        </div>
                    `).join('')}
                </div>
            `;
            showToast(`Simulation complete (${dryRun ? 'DRY-RUN' : 'LIVE'})`, 'success');
            loadExecutionLogs();
            loadIncidents();
            pollTelemetry();
        } else {
            showToast(data.error || 'Simulation error', 'error');
        }
    } catch (err) {
        showToast(`Simulation error: ${err.message}`, 'error');
    }
}

// ==========================================
// FORENSICS & AUDIT LOGS
// ==========================================

async function loadExecutionLogs() {
    try {
        let url = '/api/v1/executions?limit=50';
        if (state.selectedLogStatus !== 'all') {
            url += `&status=${state.selectedLogStatus}`;
        }
        const res = await fetch(url);
        if (!res.ok) return;
        const data = await res.json();
        state.logs = data.executions || [];
        renderLogsTable();
        renderDashboardMiniLogs();
    } catch (e) {
        console.error('Failed to load execution logs:', e);
    }
}

function filterLogsStatus(status, btn) {
    state.selectedLogStatus = status;
    document.querySelectorAll('#tab-logs .filter-chip').forEach(c => c.classList.remove('active'));
    if (btn) btn.classList.add('active');
    loadExecutionLogs();
}

function renderLogsTable() {
    const tbody = document.getElementById('logsTableBody');
    if (!tbody) return;

    if (state.logs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-cell">No execution logs found.</td></tr>';
        return;
    }

    tbody.innerHTML = state.logs.map(log => {
        const isSuccess = log.status === 'success';
        const isSkipped = log.status === 'skipped';
        const badgeClass = isSuccess ? 'status-badge resolved' : (isSkipped ? 'status-badge' : 'status-badge open');

        return `
            <tr>
                <td><code style="font-size:0.8rem; color:var(--text-muted);">${log.id}</code></td>
                <td><strong>${escapeHtml(log.rule_name || 'System Dispatcher')}</strong></td>
                <td><code style="color:var(--cyan-glow);">${escapeHtml(log.trigger_event || log.event_name)}</code></td>
                <td><span class="${badgeClass}">${log.status.toUpperCase()}</span></td>
                <td><span style="font-family:var(--font-mono);">${log.duration_ms || log.execution_time_ms || 0} ms</span></td>
                <td style="font-size:0.75rem; color:var(--text-muted);">${log.timestamp || log.executed_at}</td>
                <td>
                    <button class="action-btn cyan-btn" onclick="inspectExecution(${log.id})">🔍 Inspect</button>
                </td>
            </tr>
        `;
    }).join('');
}

function renderDashboardMiniLogs() {
    const tbody = document.getElementById('dashboardRecentLogs');
    if (!tbody) return;

    const recent = state.logs.slice(0, 5);
    if (recent.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-cell">No recent dispatches recorded.</td></tr>';
        return;
    }

    tbody.innerHTML = recent.map(log => {
        const isSuccess = log.status === 'success';
        const isSkipped = log.status === 'skipped';
        const badgeClass = isSuccess ? 'status-badge resolved' : (isSkipped ? 'status-badge' : 'status-badge open');
        return `
            <tr>
                <td><span class="${badgeClass}">${log.status.toUpperCase()}</span></td>
                <td><strong>${escapeHtml(log.rule_name || 'Dispatcher')}</strong></td>
                <td><code style="color:var(--cyan-glow);">${escapeHtml(log.trigger_event || log.event_name)}</code></td>
                <td>${log.duration_ms || log.execution_time_ms || 0} ms</td>
                <td style="font-size:0.75rem; color:var(--text-muted);">${log.timestamp || log.executed_at}</td>
            </tr>
        `;
    }).join('');
}

function inspectExecution(execId) {
    const log = state.logs.find(l => l.id === execId);
    if (!log) return;

    const modal = document.getElementById('logDetailModal');
    const content = document.getElementById('logDetailContent');

    content.innerHTML = `
        <div style="display:flex; justify-content:space-between; margin-bottom:12px;">
            <div>
                <strong>Workflow Rule:</strong> ${escapeHtml(log.rule_name || 'System Dispatcher')}<br>
                <strong>Trigger Event:</strong> <code style="color:var(--cyan-glow);">${escapeHtml(log.trigger_event || log.event_name)}</code>
            </div>
            <div style="text-align:right;">
                <strong>Execution Status:</strong> <span style="font-weight:700; color:${log.status === 'success' ? 'var(--emerald-glow)' : 'var(--red-glow)'};">${log.status.toUpperCase()}</span><br>
                <strong>Execution Duration:</strong> ${log.duration_ms || log.execution_time_ms || 0} ms
            </div>
        </div>

        ${log.ai_result && Object.keys(log.ai_result).length ? `
        <div style="margin-top:16px;">
            <h4 style="color:#06b6d4; margin-bottom:6px;">🧠 Local AI Intelligence Analysis:</h4>
            <div style="background:#0b1120; padding:12px; border-radius:6px; font-family:monospace; font-size:0.85rem;">
                <div><strong>Intent:</strong> ${escapeHtml(log.ai_result.intent || 'N/A')}</div>
                <div><strong>Urgency Score:</strong> ${log.ai_result.urgency || 0}/100</div>
                <div><strong>Lead Score:</strong> ${log.ai_result.lead_score || 0}/100</div>
                <div><strong>Recommended Route:</strong> ${escapeHtml(log.ai_result.recommended_route || 'N/A')}</div>
                ${log.ai_result.draft_response ? `<div style="margin-top:6px; color:#10b981;"><strong>Draft Response:</strong> "${escapeHtml(log.ai_result.draft_response)}"</div>` : ''}
            </div>
        </div>
        ` : ''}

        ${log.steps_trace && log.steps_trace.length ? `
        <div style="margin-top:16px;">
            <h4 style="color:#a855f7; margin-bottom:6px;">⚡ Visual Step Waterfall:</h4>
            <div style="display:flex; flex-direction:column; gap:6px;">
                ${log.steps_trace.map((st, idx) => `
                    <div style="display:flex; justify-content:space-between; align-items:center; background:#0f172a; padding:8px 12px; border-radius:4px; font-size:0.85rem; border-left:3px solid ${st.status === 'SUCCESS' ? '#10b981' : (st.status === 'DRY_RUN' ? '#a855f7' : '#ef4444')};">
                        <span><strong>Step ${idx+1}:</strong> ${escapeHtml(st.name || st.step_name)} (${escapeHtml(st.type || st.step_type)})</span>
                        <div style="display:flex; gap:10px; align-items:center;">
                            <span class="role-badge" style="font-size:0.75rem;">${st.duration_ms || 0}ms</span>
                            <span class="role-badge ${st.status === 'SUCCESS' ? 'admin' : (st.status === 'DRY_RUN' ? 'operator' : 'viewer')}">${st.status}</span>
                        </div>
                    </div>
                `).join('')}
            </div>
        </div>
        ` : ''}

        <div style="margin-top:16px;">
            <h4 style="color:var(--text-primary); margin-bottom:6px;">Input Telemetry / Context Payload:</h4>
            <pre class="curl-snippet" style="max-height:140px;">${escapeHtml(JSON.stringify(log.payload || {}, null, 2))}</pre>
        </div>

        <div style="margin-top:16px;">
            <h4 style="color:var(--text-primary); margin-bottom:6px;">Condition Evaluation Step Trace:</h4>
            <pre class="curl-snippet" style="max-height:140px;">${escapeHtml(JSON.stringify(log.trace || [], null, 2))}</pre>
        </div>

        <div style="margin-top:16px;">
            <h4 style="color:var(--text-primary); margin-bottom:6px;">Action Pipeline Dispatches:</h4>
            <pre class="curl-snippet" style="max-height:140px;">${escapeHtml(JSON.stringify(log.action_results || log.results || [], null, 2))}</pre>
        </div>
    `;

    modal.style.display = 'flex';
}

function closeLogModal() {
    document.getElementById('logDetailModal').style.display = 'none';
}

async function clearAllLogs() {
    if (!confirm('Are you sure you want to purge all execution forensic logs?')) return;
    try {
        const res = await fetch('/api/v1/executions', { method: 'DELETE' });
        const data = await res.json();
        if (res.ok) {
            showToast('Execution logs cleared.', 'info');
            loadExecutionLogs();
            pollTelemetry();
        } else {
            showToast(data.error || 'Failed to clear logs', 'error');
        }
    } catch (e) {
        showToast(`Clear error: ${e.message}`, 'error');
    }
}

// ==========================================
// INCIDENT RESPONSE CENTER
// ==========================================

async function loadIncidents() {
    try {
        let url = '/api/v1/alerts';
        if (state.selectedIncidentStatus !== 'all') {
            url += `?status=${state.selectedIncidentStatus}`;
        }
        const res = await fetch(url);
        if (!res.ok) return;
        const data = await res.json();
        state.incidents = data.alerts || [];

        renderIncidentsQueue();
        renderDashboardIncidents();

        // Update tab counter
        const openCount = state.incidents.filter(i => i.status === 'open').length;
        const countBadge = document.getElementById('tabIncidentCount');
        if (countBadge) countBadge.textContent = openCount;
    } catch (e) {
        console.error('Failed to load incidents:', e);
    }
}

function filterIncidents(status, btn) {
    state.selectedIncidentStatus = status;
    document.querySelectorAll('#tab-incidents .filter-chip').forEach(c => c.classList.remove('active'));
    if (btn) btn.classList.add('active');
    loadIncidents();
}

function renderIncidentsQueue() {
    const container = document.getElementById('incidentsQueueContainer');
    if (!container) return;

    if (state.incidents.length === 0) {
        container.innerHTML = '<div class="empty-cell">No incidents in this queue. All systems operating normally.</div>';
        return;
    }

    const isViewer = state.userRole === 'viewer';

    container.innerHTML = state.incidents.map(inc => {
        const sevClass = `severity-pill ${inc.severity ? inc.severity.toLowerCase() : 'info'}`;
        const statusClass = `status-badge ${inc.status.toLowerCase()}`;

        return `
            <div class="incident-card">
                <div class="incident-main">
                    <div class="incident-title-row">
                        <span class="${sevClass}">${inc.severity.toUpperCase()}</span>
                        <span class="incident-title">${escapeHtml(inc.title)}</span>
                        <span class="${statusClass}">${inc.status.toUpperCase()}</span>
                    </div>
                    <div class="incident-message">${escapeHtml(inc.message)}</div>
                    <div class="incident-meta">
                        <span>Incident ID: #${inc.id}</span>
                        <span>Created: ${inc.created_at}</span>
                        ${inc.acknowledged_at ? `<span>Acked: ${inc.acknowledged_at}</span>` : ''}
                        ${inc.resolved_at ? `<span>Resolved: ${inc.resolved_at}</span>` : ''}
                    </div>
                </div>
                <div style="display:flex; gap:8px; align-items:center;">
                    ${inc.status === 'open' ? `
                        <button class="hud-btn small outline" onclick="acknowledgeIncident(${inc.id})" ${isViewer ? 'disabled' : ''}>Acknowledge</button>
                    ` : ''}
                    ${inc.status !== 'resolved' ? `
                        <button class="hud-btn small primary" onclick="resolveIncident(${inc.id})" ${isViewer ? 'disabled' : ''}>Resolve</button>
                    ` : ''}
                </div>
            </div>
        `;
    }).join('');
}

function renderDashboardIncidents() {
    const container = document.getElementById('dashboardIncidentsList');
    if (!container) return;

    const openList = state.incidents.filter(i => i.status === 'open').slice(0, 3);
    if (openList.length === 0) {
        container.innerHTML = '<div class="empty-cell">No active open incidents. System healthy.</div>';
        return;
    }

    container.innerHTML = openList.map(inc => {
        const sevClass = `severity-pill ${inc.severity ? inc.severity.toLowerCase() : 'info'}`;
        return `
            <div class="incident-card" style="margin-bottom:8px;">
                <div class="incident-main">
                    <div class="incident-title-row">
                        <span class="${sevClass}">${inc.severity.toUpperCase()}</span>
                        <span style="font-weight:600; font-size:0.9rem;">${escapeHtml(inc.title)}</span>
                    </div>
                    <div style="font-size:0.8rem; color:var(--text-secondary);">${escapeHtml(inc.message)}</div>
                </div>
                <button class="hud-btn small outline" onclick="acknowledgeIncident(${inc.id})">Ack</button>
            </div>
        `;
    }).join('');
}

async function acknowledgeIncident(alertId) {
    try {
        const res = await fetch(`/api/v1/alerts/${alertId}/acknowledge`, { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            showToast('Incident acknowledged.', 'info');
            loadIncidents();
            pollTelemetry();
        } else {
            showToast(data.error || 'Failed to acknowledge incident', 'error');
        }
    } catch (e) {
        showToast(`Acknowledge error: ${e.message}`, 'error');
    }
}

async function resolveIncident(alertId) {
    const notes = prompt('Enter resolution notes (optional):', 'Mitigated and verified.');
    if (notes === null) return;

    try {
        const res = await fetch(`/api/v1/alerts/${alertId}/resolve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ notes })
        });
        const data = await res.json();
        if (res.ok) {
            showToast('Incident marked resolved.', 'success');
            loadIncidents();
            pollTelemetry();
        } else {
            showToast(data.error || 'Failed to resolve incident', 'error');
        }
    } catch (e) {
        showToast(`Resolve error: ${e.message}`, 'error');
    }
}

// ==========================================
// API KEYS MANAGEMENT
// ==========================================

async function loadApiKeys() {
    try {
        const res = await fetch('/api/v1/auth/api-keys');
        if (!res.ok) return;
        const data = await res.json();
        state.apiKeys = data.api_keys || [];
        renderApiKeysTable();
    } catch (e) {
        console.error('Failed to load API keys:', e);
    }
}

function renderApiKeysTable() {
    const tbody = document.getElementById('apiKeysTableBody');
    if (!tbody) return;

    if (state.apiKeys.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-cell">No API keys created in this workspace.</td></tr>';
        return;
    }

    tbody.innerHTML = state.apiKeys.map(k => {
        return `
            <tr>
                <td><strong>${escapeHtml(k.name)}</strong></td>
                <td><code style="color:var(--cyan-glow);">${escapeHtml(k.key_prefix)}</code></td>
                <td><span style="font-size:0.8rem; color:var(--text-muted);">${escapeHtml(Array.isArray(k.permissions) ? k.permissions.join(', ') : k.permissions)}</span></td>
                <td style="font-size:0.75rem; color:var(--text-muted);">${k.created_at}</td>
                <td style="font-size:0.75rem; color:var(--text-muted);">${k.last_used_at || 'Never'}</td>
                <td>
                    <button class="action-btn red-btn" onclick="revokeApiKey('${k.id}')" title="Revoke Key">Revoke</button>
                </td>
            </tr>
        `;
    }).join('');
}

function openNewApiKeyModal() {
    document.getElementById('newKeyName').value = '';
    document.getElementById('newApiKeyModal').style.display = 'flex';
}

function closeNewApiKeyModal() {
    document.getElementById('newApiKeyModal').style.display = 'none';
}

async function submitNewApiKey(e) {
    e.preventDefault();
    const name = document.getElementById('newKeyName').value.trim();
    const permissions = document.getElementById('newKeyPermissions').value;

    try {
        const res = await fetch('/api/v1/auth/api-keys', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, permissions })
        });
        const data = await res.json();
        if (res.ok) {
            closeNewApiKeyModal();
            loadApiKeys();

            // Reveal secret token modal
            document.getElementById('revealedSecretToken').textContent = data.secret_token;
            document.getElementById('apiKeyRevealModal').style.display = 'flex';
        } else {
            showToast(data.error || 'Failed to generate API key', 'error');
        }
    } catch (err) {
        showToast(`API Key error: ${err.message}`, 'error');
    }
}

function closeApiKeyRevealModal() {
    document.getElementById('apiKeyRevealModal').style.display = 'none';
}

function copyRevealedToken() {
    const text = document.getElementById('revealedSecretToken').textContent;
    navigator.clipboard.writeText(text).then(() => {
        showToast('Secret API Key copied to clipboard!', 'success');
    });
}

async function revokeApiKey(keyId) {
    if (!confirm('Are you sure you want to revoke this API key? Applications using it will immediately be rejected.')) return;
    try {
        const res = await fetch(`/api/v1/auth/api-keys/${keyId}`, { method: 'DELETE' });
        const data = await res.json();
        if (res.ok) {
            showToast('API key revoked.', 'info');
            loadApiKeys();
        } else {
            showToast(data.error || 'Failed to revoke key', 'error');
        }
    } catch (e) {
        showToast(`Revocation error: ${e.message}`, 'error');
    }
}

// ==========================================
// TEAM DIRECTORY & AUDIT LOGS
// ==========================================

async function loadTeamAndAudits() {
    try {
        const memRes = await fetch('/api/v1/organizations/members');
        if (memRes.ok) {
            const data = await memRes.json();
            state.teamMembers = data.members || [];
            renderTeamMembers();
        }

        const auditRes = await fetch('/api/v1/audit-trail');
        if (auditRes.ok) {
            const data = await auditRes.json();
            state.auditLogs = data.audit_trail || [];
            renderAuditTrail();
        }
    } catch (e) {
        console.error('Failed to load team or audits:', e);
    }
}

function renderTeamMembers() {
    const tbody = document.getElementById('teamMembersTableBody');
    if (!tbody) return;

    if (state.teamMembers.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty-cell">No team members found.</td></tr>';
        return;
    }

    tbody.innerHTML = state.teamMembers.map(m => {
        const u = m.user || {};
        return `
            <tr>
                <td><strong>${escapeHtml(u.full_name || 'Member')}</strong></td>
                <td><code style="color:var(--text-secondary);">${escapeHtml(u.email || '')}</code></td>
                <td><span class="role-badge ${m.role.toLowerCase()}">${m.role.toUpperCase()}</span></td>
                <td style="font-size:0.75rem; color:var(--text-muted);">${m.created_at}</td>
            </tr>
        `;
    }).join('');
}

function renderAuditTrail() {
    const tbody = document.getElementById('auditTrailTableBody');
    if (!tbody) return;

    if (state.auditLogs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-cell">No audit log records yet.</td></tr>';
        return;
    }

    tbody.innerHTML = state.auditLogs.map(a => {
        return `
            <tr>
                <td><strong>${escapeHtml(a.action)}</strong></td>
                <td><span style="font-size:0.8rem; color:var(--text-secondary);">${escapeHtml(a.resource_type)}</span></td>
                <td><code style="font-size:0.75rem; color:var(--cyan-glow);">${escapeHtml(a.resource_id || '-')}</code></td>
                <td><span style="font-family:var(--font-mono); font-size:0.8rem;">${escapeHtml(a.ip_address || '127.0.0.1')}</span></td>
                <td style="font-size:0.75rem; color:var(--text-muted);">${a.created_at}</td>
            </tr>
        `;
    }).join('');
}

function openAddMemberModal() {
    document.getElementById('newMemberName').value = '';
    document.getElementById('newMemberEmail').value = '';
    document.getElementById('addMemberModal').style.display = 'flex';
}

function closeAddMemberModal() {
    document.getElementById('addMemberModal').style.display = 'none';
}

async function submitAddMember(e) {
    e.preventDefault();
    const full_name = document.getElementById('newMemberName').value.trim();
    const email = document.getElementById('newMemberEmail').value.trim();
    const role = document.getElementById('newMemberRole').value;

    try {
        const res = await fetch('/api/v1/organizations/members', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, full_name, role })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(`Added ${email} as ${role.toUpperCase()}`, 'success');
            closeAddMemberModal();
            loadTeamAndAudits();
        } else {
            showToast(data.error || 'Failed to add member', 'error');
        }
    } catch (err) {
        showToast(`Add member error: ${err.message}`, 'error');
    }
}

// ==========================================
// DEMO PERSONA SWITCHER
// ==========================================

function openPersonaModal() {
    document.getElementById('personaModal').style.display = 'flex';
}

function closePersonaModal() {
    document.getElementById('personaModal').style.display = 'none';
}

async function quickLoginPersona(email, password) {
    try {
        const res = await fetch('/api/v1/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        const data = await res.json();
        if (res.ok) {
            state.currentUser = data.user;
            state.currentOrg = data.organization;
            state.userRole = data.role;
            updateUserBadgeUI();
            closePersonaModal();
            showToast(`Logged in as ${data.user.full_name} (${data.role.toUpperCase()})`, 'success');
            refreshAllData();
        } else {
            showToast(data.error || 'Login failed', 'error');
        }
    } catch (err) {
        showToast(`Login error: ${err.message}`, 'error');
    }
}

// ==========================================
// BLUEPRINTS
// ==========================================

async function loadBlueprints() {
    try {
        const res = await fetch('/api/presets');
        if (!res.ok) return;
        const data = await res.json();
        state.blueprints = data.presets || [];
        renderBlueprintsGrid();
    } catch (e) {
        console.error('Failed to load blueprints:', e);
    }
}

function renderBlueprintsGrid() {
    const grid = document.getElementById('blueprintsGrid');
    if (!grid) return;

    grid.innerHTML = state.blueprints.map(bp => {
        return `
            <div class="blueprint-card">
                <div class="bp-header">
                    <span class="category-chip ${bp.category.toLowerCase()}">${bp.category}</span>
                    <span style="font-family:var(--font-mono); font-size:0.75rem; color:var(--text-muted);">Priority: ${bp.priority}</span>
                </div>
                <h3 class="bp-title">${escapeHtml(bp.name)}</h3>
                <p class="bp-desc">${escapeHtml(bp.description)}</p>
                <div class="bp-footer">
                    <button class="hud-btn outline small" onclick="installBlueprint('${bp.id}')">Install Blueprint</button>
                </div>
            </div>
        `;
    }).join('');
}

async function installBlueprint(blueprintId) {
    try {
        const res = await fetch('/api/presets/install', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ preset_id: blueprintId })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'Blueprint installed!', 'success');
            loadRules();
            pollTelemetry();
        } else {
            showToast(data.error || 'Failed to install blueprint', 'error');
        }
    } catch (e) {
        showToast(`Install error: ${e.message}`, 'error');
    }
}

// ==========================================
// NOTIFICATIONS DRAWER
// ==========================================

function toggleNotificationsDrawer() {
    const drawer = document.getElementById('notifDrawer');
    if (drawer) {
        drawer.style.display = drawer.style.display === 'flex' ? 'none' : 'flex';
    }
}

async function pollNotifications() {
    try {
        const res = await fetch('/api/notifications?unread=true');
        if (!res.ok) return;
        const data = await res.json();
        const list = data.notifications || [];

        const badge = document.getElementById('notifCountBadge');
        if (badge) {
            if (list.length > 0) {
                badge.style.display = 'block';
                badge.textContent = list.length;
            } else {
                badge.style.display = 'none';
            }
        }

        const notifList = document.getElementById('notifList');
        if (notifList) {
            if (list.length === 0) {
                notifList.innerHTML = '<div class="notif-empty">No active notifications</div>';
            } else {
                notifList.innerHTML = list.map(n => `
                    <div class="notif-item">
                        <div style="font-weight:700; color:var(--text-primary); font-size:0.85rem;">${escapeHtml(n.title)}</div>
                        <div style="font-size:0.75rem; color:var(--text-secondary); margin-top:2px;">${escapeHtml(n.message)}</div>
                        <div style="font-size:0.7rem; color:var(--text-muted); margin-top:4px;">${n.timestamp}</div>
                    </div>
                `).join('');
            }
        }
    } catch (e) {
        console.error('Failed to poll notifications:', e);
    }
}

async function markNotificationsRead() {
    try {
        await fetch('/api/notifications/read', { method: 'POST' });
        pollNotifications();
        showToast('Notifications marked as read.', 'info');
    } catch (e) {}
}

async function clearNotifications() {
    try {
        await fetch('/api/notifications', { method: 'DELETE' });
        pollNotifications();
        showToast('Notifications cleared.', 'info');
    } catch (e) {}
}

// ==========================================
// UTILITIES & TOASTS
// ==========================================

function showToast(msg, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `hud-toast ${type}`;
    toast.textContent = msg;

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function importRulesFile(event) {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async (e) => {
        try {
            const data = JSON.parse(e.target.result);
            const res = await fetch('/api/import', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            const result = await res.json();
            if (res.ok) {
                showToast(result.message || 'Rules imported successfully.', 'success');
                loadRules();
                pollTelemetry();
            } else {
                showToast(result.error || 'Import failed', 'error');
            }
        } catch (err) {
            showToast('Invalid JSON file format', 'error');
        }
    };
    reader.readAsText(file);
}

// ==========================================
// CRM LEADS CONTROLLER & REAL-TIME PIPELINE
// ==========================================

let leadsCache = [];

async function loadLeads() {
    const tbody = document.getElementById('leadsTableBody');
    if (!tbody) return;

    try {
        const res = await fetch('/api/v1/leads');
        if (!res.ok) {
            tbody.innerHTML = '<tr><td colspan="8" class="text-center" style="color:#ef4444;">Failed to load CRM leads.</td></tr>';
            return;
        }
        const data = await res.json();
        leadsCache = data.leads || [];
        renderLeads(leadsCache);
        updateLeadsKpis(leadsCache);
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center" style="color:#ef4444;">Error fetching leads: ${escapeHtml(err.message)}</td></tr>`;
    }
}

function updateLeadsKpis(leads) {
    const totalEl = document.getElementById('leadsKpiTotal');
    const qualifiedEl = document.getElementById('leadsKpiQualified');
    const salesEl = document.getElementById('leadsKpiSales');
    const supportEl = document.getElementById('leadsKpiSupport');

    if (totalEl) totalEl.textContent = leads.length;
    if (qualifiedEl) qualifiedEl.textContent = leads.filter(l => (l.lead_score || 0) >= 70).length;
    if (salesEl) salesEl.textContent = leads.filter(l => (l.route_department || '').toLowerCase() === 'sales').length;
    if (supportEl) supportEl.textContent = leads.filter(l => (l.route_department || '').toLowerCase().includes('support')).length;

    const tabBadge = document.getElementById('tabLeadCount');
    if (tabBadge) tabBadge.textContent = leads.length;
}

function renderLeads(leads) {
    const tbody = document.getElementById('leadsTableBody');
    if (!tbody) return;

    if (!leads.length) {
        tbody.innerHTML = `
            <tr>
                <td colspan="8" class="text-center" style="padding: 40px; color: #64748b;">
                    <div style="font-size: 2rem; margin-bottom: 8px;">📭</div>
                    <div>No CRM leads found matching current filters.</div>
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = leads.map(l => {
        const score = l.lead_score || 0;
        let scoreBadgeClass = 'viewer';
        if (score >= 75) scoreBadgeClass = 'admin';
        else if (score >= 50) scoreBadgeClass = 'operator';

        const dept = l.route_department || 'General Queue';
        let deptColor = '#94a3b8';
        if (dept === 'Sales') deptColor = '#10b981';
        else if (dept.includes('Support')) deptColor = '#06b6d4';
        else if (dept.includes('Security')) deptColor = '#ef4444';

        const previewMsg = escapeHtml((l.message || '').length > 60 ? (l.message || '').slice(0, 60) + '...' : l.message || 'No inquiry text');

        return `
            <tr>
                <td>
                    <div style="font-weight: 600; color: #fff;">${escapeHtml(l.name || 'Anonymous Lead')}</div>
                    <div style="font-size: 0.8rem; color: #06b6d4; font-family: monospace;">${escapeHtml(l.email || 'No email')}</div>
                    ${l.company ? `<div style="font-size: 0.75rem; color: #94a3b8;">🏢 ${escapeHtml(l.company)}</div>` : ''}
                </td>
                <td style="max-width: 250px; font-size: 0.85rem; color: #cbd5e1;" title="${escapeHtml(l.message || '')}">
                    "${previewMsg}"
                </td>
                <td>
                    <span class="role-badge" style="background: rgba(255,255,255,0.06); font-family: monospace; font-size: 0.75rem;">
                        ${escapeHtml(l.intent || 'inquiry')}
                    </span>
                </td>
                <td>
                    <span class="role-badge ${scoreBadgeClass}" style="font-weight: bold; font-family: monospace;">
                        ${score} / 100
                    </span>
                </td>
                <td>
                    <span style="color: ${deptColor}; font-weight: 600; font-size: 0.85rem;">
                        ● ${escapeHtml(dept)}
                    </span>
                </td>
                <td>
                    <select class="hud-input" style="padding: 4px 8px; font-size: 0.8rem; width: auto;" onchange="updateLeadStatus('${l.id}', this.value)">
                        <option value="new" ${l.status === 'new' ? 'selected' : ''}>New</option>
                        <option value="qualified" ${l.status === 'qualified' ? 'selected' : ''}>Qualified</option>
                        <option value="follow_up" ${l.status === 'follow_up' ? 'selected' : ''}>Follow Up</option>
                        <option value="closed" ${l.status === 'closed' ? 'selected' : ''}>Closed</option>
                        <option value="archived" ${l.status === 'archived' ? 'selected' : ''}>Archived</option>
                    </select>
                </td>
                <td style="font-size: 0.8rem; color: #64748b; font-family: monospace; white-space: nowrap;">
                    ${escapeHtml(l.created_at || 'Just now')}
                </td>
                <td style="white-space: nowrap;">
                    <button class="action-btn cyan-btn" style="padding: 4px 8px; font-size: 0.75rem;" onclick="viewLeadDetail('${l.id}')">Inspect</button>
                    <button class="action-btn red-btn" style="padding: 4px 8px; font-size: 0.75rem;" onclick="deleteLead('${l.id}')">Delete</button>
                </td>
            </tr>
        `;
    }).join('');
}

function filterLeads() {
    const searchVal = (document.getElementById('leadSearchInput')?.value || '').toLowerCase().trim();
    const statusVal = document.getElementById('leadStatusFilter')?.value || 'all';
    const deptVal = document.getElementById('leadDeptFilter')?.value || 'all';

    const filtered = leadsCache.filter(l => {
        const matchesSearch = !searchVal || 
            (l.name || '').toLowerCase().includes(searchVal) ||
            (l.email || '').toLowerCase().includes(searchVal) ||
            (l.company || '').toLowerCase().includes(searchVal) ||
            (l.message || '').toLowerCase().includes(searchVal);

        const matchesStatus = statusVal === 'all' || l.status === statusVal;
        const matchesDept = deptVal === 'all' || (l.route_department || '').toLowerCase() === deptVal.toLowerCase();

        return matchesSearch && matchesStatus && matchesDept;
    });

    renderLeads(filtered);
}

async function updateLeadStatus(leadId, newStatus) {
    try {
        const res = await fetch(`/api/v1/leads/${leadId}/status`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus })
        });
        if (res.ok) {
            showToast(`Lead status updated to '${newStatus}'.`, 'success');
            loadLeads();
            pollTelemetry();
        } else {
            showToast('Failed to update lead status.', 'error');
        }
    } catch (err) {
        showToast(`Update error: ${err.message}`, 'error');
    }
}

async function deleteLead(leadId) {
    if (!confirm('Are you sure you want to delete this CRM lead record?')) return;
    try {
        const res = await fetch(`/api/v1/leads/${leadId}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('Lead record removed successfully.', 'info');
            loadLeads();
            pollTelemetry();
        } else {
            showToast('Failed to delete lead.', 'error');
        }
    } catch (err) {
        showToast(`Delete error: ${err.message}`, 'error');
    }
}

function viewLeadDetail(leadId) {
    const lead = leadsCache.find(l => l.id === leadId);
    if (!lead) return;

    alert(
        `LEAD DETAILS & AI ANALYSIS\n` +
        `-----------------------------------------\n` +
        `Name: ${lead.name || 'N/A'}\n` +
        `Email: ${lead.email || 'N/A'}\n` +
        `Company: ${lead.company || 'N/A'}\n` +
        `Lead Score: ${lead.lead_score || 0} / 100\n` +
        `AI Intent: ${lead.intent || 'N/A'}\n` +
        `Urgency Score: ${lead.urgency_score || 0} / 100\n` +
        `Routed Department: ${lead.route_department || 'General Queue'}\n` +
        `Status: ${lead.status || 'new'}\n\n` +
        `Customer Inquiry Message:\n` +
        `"${lead.message || ''}"\n\n` +
        (lead.draft_response ? `Automated AI Response Draft:\n"${lead.draft_response}"\n` : '')
    );
}

function openNewLeadModal() {
    const name = prompt('Customer / Contact Name:');
    if (!name) return;
    const email = prompt('Contact Email Address:');
    if (!email) return;
    const message = prompt('Customer Inquiry Message / Requirement:');
    if (!message) return;

    fetch('/api/v1/events/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            event: 'lead.created',
            name: name,
            email: email,
            message: message,
            dry_run: false
        })
    }).then(res => res.json()).then(data => {
        showToast('New lead ingested & processed through automation pipeline!', 'success');
        loadLeads();
        pollTelemetry();
    }).catch(err => {
        showToast('Ingestion error: ' + err.message, 'error');
    });
}

