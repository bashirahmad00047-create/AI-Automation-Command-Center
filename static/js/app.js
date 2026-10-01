/**
 * AI AUTOMATION COMMAND CENTER - FRONTEND ENGINE CONTROLLER
 * Handles HUD telemetry, rule creation/execution, NLP sandbox,
 * audit log inspection, blueprints, and live event streaming.
 */

// Application State
const state = {
    currentTab: 'dashboard',
    rules: [],
    logs: [],
    blueprints: [],
    notifications: [],
    selectedCategory: 'All',
    selectedLogStatus: 'all',
    engineRunning: true
};

// ==========================================
// INITIALIZATION & EVENT LOOPS
// ==========================================

document.addEventListener('DOMContentLoaded', () => {
    initClock();
    refreshAllData();

    // Telemetry and status poll (every 2.5 seconds)
    setInterval(pollTelemetry, 2500);

    // Event stream & notifications poll (every 3 seconds)
    setInterval(pollEventStream, 3000);
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

function refreshAllData() {
    pollTelemetry();
    loadRules();
    loadBlueprints();
    loadExecutionLogs();
    pollEventStream();
    pollNotifications();
}

// ==========================================
// HUD TELEMETRY & ENGINE STATUS
// ==========================================

async function pollTelemetry() {
    try {
        const res = await fetch('/api/status');
        if (!res.ok) return;
        const data = await res.json();

        // Update Engine State Badge
        state.engineRunning = data.engine_running;
        const badge = document.getElementById('engineStatusBadge');
        const text = document.getElementById('engineStatusText');
        const toggleBtnLabel = document.getElementById('toggleEngineLabel');

        if (state.engineRunning) {
            badge.innerHTML = '<span class="status-dot green pulse"></span><span class="status-text">ENGINE ONLINE</span>';
            if (toggleBtnLabel) toggleBtnLabel.textContent = 'Pause Engine';
        } else {
            badge.innerHTML = '<span class="status-dot red"></span><span class="status-text">ENGINE PAUSED</span>';
            if (toggleBtnLabel) toggleBtnLabel.textContent = 'Resume Engine';
        }

        // Key stats
        const stats = data.stats || {};
        document.getElementById('statActiveRules').textContent = `${stats.active_rules || 0} / ${stats.total_rules || 0}`;
        document.getElementById('statTotalRules').textContent = `${stats.total_rules || 0} Total Configured`;
        document.getElementById('statTotalExecutions').textContent = stats.total_executions || 0;
        document.getElementById('statSuccessExecutions').textContent = `${stats.successful_executions || 0} Successful Dispatches`;
        document.getElementById('statSuccessRate').textContent = `${stats.success_rate || 100}%`;
        document.getElementById('statUptime').textContent = data.uptime || '0s';

        // Telemetry Gauges
        const telem = data.telemetry || {};
        const cpu = Math.round(telem.cpu_percent || 0);
        const ram = Math.round(telem.memory_percent || 0);
        const disk = Math.round(telem.disk_percent || 0);

        document.getElementById('telemCpuVal').textContent = `${cpu}%`;
        document.getElementById('telemCpuBar').style.width = `${Math.min(100, cpu)}%`;

        document.getElementById('telemRamVal').textContent = `${ram}%`;
        document.getElementById('telemRamBar').style.width = `${Math.min(100, ram)}%`;
        document.getElementById('telemRamGb').textContent = `${telem.memory_used_gb || 0} / ${telem.memory_total_gb || 0}`;

        document.getElementById('telemDiskVal').textContent = `${disk}%`;
        document.getElementById('telemDiskBar').style.width = `${Math.min(100, disk)}%`;
        document.getElementById('telemDiskGb').textContent = telem.disk_free_gb || 0;

        document.getElementById('statProcessMem').textContent = `RSS: ${telem.process_memory_mb || 0} MB`;

    } catch (err) {
        console.error('Error polling telemetry:', err);
    }
}

async function toggleEngineState() {
    try {
        const res = await fetch('/api/engine/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ online: !state.engineRunning })
        });
        const data = await res.json();
        showToast(data.message, data.engine_running ? 'success' : 'error');
        pollTelemetry();
    } catch (err) {
        showToast('Failed to toggle engine state', 'error');
    }
}

// ==========================================
// TAB SWITCHING
// ==========================================

function switchTab(tabId) {
    state.currentTab = tabId;

    // Toggle Tab buttons
    document.querySelectorAll('.hud-tab').forEach(tab => {
        tab.classList.toggle('active', tab.getAttribute('onclick').includes(tabId));
    });

    // Toggle Tab panels
    document.querySelectorAll('.tab-panel').forEach(panel => {
        panel.classList.remove('active');
    });
    const activePanel = document.getElementById(`tab-${tabId}`);
    if (activePanel) activePanel.classList.add('active');

    // Refresh context data on tab switch
    if (tabId === 'rules') loadRules();
    if (tabId === 'logs') loadExecutionLogs();
    if (tabId === 'blueprints') loadBlueprints();
}

// ==========================================
// LIVE EVENT STREAM & QUICK DISPATCH
// ==========================================

async function pollEventStream() {
    try {
        const res = await fetch('/api/events/stream');
        if (!res.ok) return;
        const data = await res.json();
        renderEventStream(data.events || []);
    } catch (err) {
        console.error('Error polling event stream:', err);
    }
}

function renderEventStream(events) {
    const container = document.getElementById('activityStreamContainer');
    if (!container) return;

    if (!events.length) {
        container.innerHTML = '<div class="stream-empty">Waiting for automation events...</div>';
        return;
    }

    container.innerHTML = events.slice(0, 15).map(evt => `
        <div class="stream-item">
            <div class="stream-item-header">
                <span class="stream-event-name">${escapeHtml(evt.name)}</span>
                <span class="stream-time">${escapeHtml(evt.timestamp)}</span>
            </div>
            <div class="stream-details">
                Payload: ${JSON.stringify(evt.payload || {})}
            </div>
        </div>
    `).join('');
}

async function quickDispatchEvent(eventName, payload) {
    try {
        const res = await fetch('/api/events/dispatch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                event_name: eventName,
                payload: payload,
                source: 'quick_dispatcher'
            })
        });
        const data = await res.json();
        showToast(`Dispatched event: ${eventName}`, 'success');
        pollEventStream();
        pollTelemetry();
        loadExecutionLogs();
    } catch (err) {
        showToast(`Failed to dispatch event: ${err.message}`, 'error');
    }
}

// ==========================================
// AUTOMATION RULES MANAGEMENT
// ==========================================

async function loadRules() {
    try {
        const res = await fetch('/api/rules');
        if (!res.ok) return;
        const data = await res.json();
        state.rules = data.rules || [];
        renderRulesGrid();
    } catch (err) {
        console.error('Error loading rules:', err);
    }
}

function filterRulesByCategory(category) {
    state.selectedCategory = category;
    document.querySelectorAll('#categoryFilterContainer .filter-pill').forEach(pill => {
        pill.classList.toggle('active', pill.textContent.trim() === category);
    });
    renderRulesGrid();
}

function searchRules() {
    renderRulesGrid();
}

function renderRulesGrid() {
    const container = document.getElementById('rulesGrid');
    if (!container) return;

    const searchTerm = (document.getElementById('ruleSearchInput')?.value || '').toLowerCase();

    const filtered = state.rules.filter(rule => {
        const matchesCategory = state.selectedCategory === 'All' || rule.category === state.selectedCategory;
        const matchesSearch = !searchTerm ||
            rule.name.toLowerCase().includes(searchTerm) ||
            (rule.description && rule.description.toLowerCase().includes(searchTerm)) ||
            rule.category.toLowerCase().includes(searchTerm);
        return matchesCategory && matchesSearch;
    });

    if (!filtered.length) {
        container.innerHTML = '<div class="stream-empty" style="grid-column: 1 / -1;">No matching automation rules found.</div>';
        return;
    }

    container.innerHTML = filtered.map(rule => `
        <div class="rule-card" id="card-${rule.id}">
            <div>
                <div class="rule-card-top">
                    <span class="rule-category-badge">${escapeHtml(rule.category)}</span>
                    <span class="rule-priority-tag">P${rule.priority}</span>
                </div>
                <div class="rule-name">${escapeHtml(rule.name)}</div>
                <div class="rule-desc">${escapeHtml(rule.description || 'No description provided.')}</div>
                <div class="rule-specs">
                    <div class="rule-spec-row">
                        <span>Trigger:</span>
                        <span>${escapeHtml(rule.trigger?.type || 'event')}: <strong>${escapeHtml(rule.trigger?.event_name || '*')}</strong></span>
                    </div>
                    <div class="rule-spec-row">
                        <span>Conditions:</span>
                        <span>${(rule.condition?.conditions || []).length} (${escapeHtml(rule.condition?.logic || 'AND')})</span>
                    </div>
                    <div class="rule-spec-row">
                        <span>Actions:</span>
                        <span>${(rule.actions || []).length} Dispatched</span>
                    </div>
                    <div class="rule-spec-row">
                        <span>Executions:</span>
                        <span>${rule.execution_count || 0} times</span>
                    </div>
                </div>
            </div>

            <div class="rule-card-footer">
                <label class="switch">
                    <input type="checkbox" ${rule.enabled ? 'checked' : ''} onchange="toggleRuleState('${rule.id}', this.checked)">
                    <span class="slider"></span>
                </label>
                <div class="rule-actions-group">
                    <button class="hud-btn outline" style="padding: 4px 8px; font-size: 11px;" onclick="runRuleManually('${rule.id}')">▶ Run</button>
                    <button class="hud-btn outline" style="padding: 4px 8px; font-size: 11px;" onclick="openEditRuleModal('${rule.id}')">✏️ Edit</button>
                    <button class="hud-btn red-btn" style="padding: 4px 8px; font-size: 11px;" onclick="deleteRule('${rule.id}')">🗑️</button>
                </div>
            </div>
        </div>
    `).join('');
}

async function toggleRuleState(ruleId, isEnabled) {
    try {
        const res = await fetch(`/api/rules/${ruleId}/toggle`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: isEnabled })
        });
        const data = await res.json();
        showToast(`Rule ${isEnabled ? 'Enabled' : 'Disabled'}`, 'success');
        loadRules();
        pollTelemetry();
    } catch (err) {
        showToast('Failed to toggle rule state', 'error');
    }
}

async function runRuleManually(ruleId) {
    try {
        showToast('Executing rule...', 'info');
        const res = await fetch(`/api/rules/${ruleId}/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const data = await res.json();
        if (data.matched) {
            showToast(`Rule executed successfully! (${data.duration_ms}ms)`, 'success');
        } else {
            showToast(`Rule conditions not met for current state.`, 'error');
        }
        pollEventStream();
        loadExecutionLogs();
        pollTelemetry();
    } catch (err) {
        showToast(`Error executing rule: ${err.message}`, 'error');
    }
}

async function deleteRule(ruleId) {
    if (!confirm('Are you sure you want to delete this automation rule?')) return;
    try {
        const res = await fetch(`/api/rules/${ruleId}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('Rule deleted', 'success');
            loadRules();
            pollTelemetry();
        } else {
            showToast('Failed to delete rule', 'error');
        }
    } catch (err) {
        showToast('Error deleting rule', 'error');
    }
}

// ==========================================
// RULE BUILDER MODAL & DYNAMIC FORM
// ==========================================

function openCreateRuleModal() {
    document.getElementById('modalTitle').textContent = 'Create New Automation Rule';
    document.getElementById('ruleForm').reset();
    document.getElementById('formRuleId').value = '';
    document.getElementById('conditionsList').innerHTML = '';
    document.getElementById('actionsList').innerHTML = '';

    // Add 1 default condition and 1 default action
    addConditionRow('payload.cpu_percent', '>=', '85');
    addActionRow('notification', { title: 'Alert Title', message: 'Alert Details', severity: 'warning' });

    document.getElementById('ruleModal').style.display = 'flex';
}

function openEditRuleModal(ruleId) {
    const rule = state.rules.find(r => r.id === ruleId);
    if (!rule) return;

    document.getElementById('modalTitle').textContent = 'Edit Automation Rule';
    document.getElementById('formRuleId').value = rule.id;
    document.getElementById('formRuleName').value = rule.name;
    document.getElementById('formRuleCategory').value = rule.category;
    document.getElementById('formRuleDescription').value = rule.description || '';
    document.getElementById('formRulePriority').value = rule.priority || 10;
    document.getElementById('formRuleCooldown').value = rule.cooldown_seconds || 0;
    document.getElementById('formRuleEnabled').value = rule.enabled ? '1' : '0';

    document.getElementById('formTriggerType').value = rule.trigger?.type || 'event';
    document.getElementById('formTriggerEvent').value = rule.trigger?.event_name || '*';

    document.getElementById('formConditionLogic').value = rule.condition?.logic || 'AND';

    // Populate conditions
    const condContainer = document.getElementById('conditionsList');
    condContainer.innerHTML = '';
    const conditions = rule.condition?.conditions || [];
    if (conditions.length) {
        conditions.forEach(c => addConditionRow(c.field, c.operator, c.value));
    } else {
        addConditionRow('', 'equals', '');
    }

    // Populate actions
    const actContainer = document.getElementById('actionsList');
    actContainer.innerHTML = '';
    const actions = rule.actions || [];
    if (actions.length) {
        actions.forEach(a => addActionRow(a.type, a.params));
    } else {
        addActionRow('notification', {});
    }

    document.getElementById('ruleModal').style.display = 'flex';
}

function closeRuleModal() {
    document.getElementById('ruleModal').style.display = 'none';
}

function addConditionRow(field = '', operator = 'equals', value = '') {
    const container = document.getElementById('conditionsList');
    const row = document.createElement('div');
    row.className = 'builder-row condition-row';
    row.innerHTML = `
        <input type="text" class="hud-input flex-2 cond-field" placeholder="Field path (e.g. payload.cpu_percent)" value="${escapeHtml(String(field))}" required>
        <select class="hud-input flex-1 cond-operator">
            <option value="equals" ${operator === 'equals' ? 'selected' : ''}>Equals (==)</option>
            <option value="not_equals" ${operator === 'not_equals' ? 'selected' : ''}>Not Equals (!=)</option>
            <option value=">=" ${operator === '>=' ? 'selected' : ''}>&gt;=</option>
            <option value="<=" ${operator === '<=' ? 'selected' : ''}>&lt;=</option>
            <option value=">" ${operator === '>' ? 'selected' : ''}>&gt;</option>
            <option value="<" ${operator === '<' ? 'selected' : ''}>&lt;</option>
            <option value="contains" ${operator === 'contains' ? 'selected' : ''}>Contains</option>
            <option value="regex_match" ${operator === 'regex_match' ? 'selected' : ''}>Regex Match</option>
            <option value="in_list" ${operator === 'in_list' ? 'selected' : ''}>In List (comma separated)</option>
        </select>
        <input type="text" class="hud-input flex-2 cond-value" placeholder="Target Value" value="${escapeHtml(String(value))}">
        <button type="button" class="remove-btn" onclick="this.parentElement.remove()">&times;</button>
    `;
    container.appendChild(row);
}

function addActionRow(type = 'notification', params = {}) {
    const container = document.getElementById('actionsList');
    const row = document.createElement('div');
    row.className = 'builder-row action-row';

    const paramStr = typeof params === 'object' ? JSON.stringify(params) : params;

    row.innerHTML = `
        <select class="hud-input flex-1 act-type">
            <option value="notification" ${type === 'notification' ? 'selected' : ''}>Notification</option>
            <option value="log_entry" ${type === 'log_entry' ? 'selected' : ''}>Audit Log Entry</option>
            <option value="file_append" ${type === 'file_append' ? 'selected' : ''}>Append to File</option>
            <option value="email_dispatch" ${type === 'email_dispatch' ? 'selected' : ''}>Email Alert</option>
            <option value="webhook_call" ${type === 'webhook_call' ? 'selected' : ''}>Webhook HTTP Call</option>
        </select>
        <input type="text" class="hud-input flex-2 act-params" placeholder='JSON params e.g. {"title":"Alert","message":"Spike"}' value='${escapeHtml(paramStr)}'>
        <button type="button" class="remove-btn" onclick="this.parentElement.remove()">&times;</button>
    `;
    container.appendChild(row);
}

async function saveRuleForm(event) {
    event.preventDefault();

    const ruleId = document.getElementById('formRuleId').value;
    const name = document.getElementById('formRuleName').value.trim();
    const category = document.getElementById('formRuleCategory').value;
    const description = document.getElementById('formRuleDescription').value.trim();
    const priority = parseInt(document.getElementById('formRulePriority').value, 10);
    const cooldown = parseInt(document.getElementById('formRuleCooldown').value, 10);
    const enabled = document.getElementById('formRuleEnabled').value === '1';

    const triggerType = document.getElementById('formTriggerType').value;
    const triggerEvent = document.getElementById('formTriggerEvent').value.trim();

    const conditionLogic = document.getElementById('formConditionLogic').value;

    // Collect conditions
    const conditions = [];
    document.querySelectorAll('.condition-row').forEach(row => {
        const field = row.querySelector('.cond-field').value.trim();
        const operator = row.querySelector('.cond-operator').value;
        const valStr = row.querySelector('.cond-value').value.trim();

        let parsedVal = valStr;
        if (!isNaN(valStr) && valStr !== '') {
            parsedVal = Number(valStr);
        }

        if (field) {
            conditions.push({ field, operator, value: parsedVal });
        }
    });

    // Collect actions
    const actions = [];
    document.querySelectorAll('.action-row').forEach(row => {
        const type = row.querySelector('.act-type').value;
        const paramStr = row.querySelector('.act-params').value.trim();
        let params = {};
        try {
            params = JSON.parse(paramStr);
        } catch {
            params = { message: paramStr };
        }
        actions.push({ type, params });
    });

    const rulePayload = {
        name,
        category,
        description,
        priority,
        cooldown_seconds: cooldown,
        enabled,
        trigger: {
            type: triggerType,
            event_name: triggerEvent
        },
        condition: {
            logic: conditionLogic,
            conditions
        },
        actions
    };

    if (ruleId) rulePayload.id = ruleId;

    try {
        const res = await fetch('/api/rules', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(rulePayload)
        });
        const data = await res.json();
        if (data.success) {
            showToast('Automation rule saved successfully', 'success');
            closeRuleModal();
            loadRules();
            pollTelemetry();
        } else {
            showToast(`Error: ${data.error}`, 'error');
        }
    } catch (err) {
        showToast('Failed to save rule', 'error');
    }
}

// ==========================================
// AI NLP SANDBOX
// ==========================================

function setNlpPrompt(text) {
    const input = document.getElementById('nlpPromptInput');
    if (input) {
        input.value = text;
        input.focus();
    }
}

async function analyzeNlpPrompt() {
    const text = document.getElementById('nlpPromptInput')?.value.trim();
    if (!text) {
        showToast('Please enter a natural language text prompt', 'error');
        return;
    }

    const dryRun = document.getElementById('nlpDryRunCheck')?.checked ?? true;

    try {
        showToast('Analyzing text with local heuristic engine...', 'info');
        const res = await fetch('/api/nlp/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, dry_run: dryRun })
        });
        const data = await res.json();
        if (data.error) {
            showToast(data.error, 'error');
            return;
        }

        renderNlpResults(data.nlp, data.simulation);
        showToast('Analysis and automation simulation complete!', 'success');
    } catch (err) {
        showToast(`NLP analysis failed: ${err.message}`, 'error');
    }
}

function renderNlpResults(nlp, sim) {
    const container = document.getElementById('nlpResultsContainer');
    if (!container) return;

    container.style.display = 'block';

    document.getElementById('nlpConfidenceBadge').textContent = `Confidence: ${Math.round((nlp.confidence || 0) * 100)}%`;
    document.getElementById('nlpIntentVal').textContent = (nlp.intent || 'general_query').toUpperCase();
    document.getElementById('nlpUrgencyVal').textContent = `${nlp.urgency || 0} / 100`;

    const sevEl = document.getElementById('nlpSeverityVal');
    sevEl.textContent = nlp.severity_level || 'LOW';
    sevEl.style.color = nlp.severity_level === 'CRITICAL' ? 'var(--red-glow)' :
                       nlp.severity_level === 'HIGH' ? 'var(--amber-glow)' : 'var(--emerald-glow)';

    document.getElementById('nlpSentimentVal').textContent = `${nlp.sentiment_label || 'neutral'} (${nlp.sentiment || 0})`;

    // Entities
    const entitiesBox = document.getElementById('nlpEntitiesContainer');
    const entities = nlp.entities || {};
    const tags = [];

    for (const [category, values] of Object.entries(entities)) {
        if (Array.isArray(values)) {
            values.forEach(v => tags.push(`<span class="entity-tag">${escapeHtml(category)}: ${escapeHtml(String(v))}</span>`));
        }
    }

    entitiesBox.innerHTML = tags.length ? tags.join('') : '<span style="font-size:12px; color:var(--text-muted);">No structured entities detected.</span>';

    // Matched rules
    const matchedRulesBox = document.getElementById('nlpMatchedRulesContainer');
    const executedRules = sim.executed_rules || [];

    if (!executedRules.length) {
        matchedRulesBox.innerHTML = '<span style="font-size:12px; color:var(--text-muted);">No rules matched this prompt trigger.</span>';
        return;
    }

    matchedRulesBox.innerHTML = executedRules.map(r => `
        <div class="matched-rule-row">
            <div class="matched-rule-header">
                <span>Rule: <strong>${escapeHtml(r.rule_name)}</strong></span>
                <span class="status-badge ${r.matched ? 'success' : 'skipped'}">${r.matched ? 'MATCHED & TRIGGERED' : 'CONDITION SKIPPED'}</span>
            </div>
            <div class="eval-trace-steps">
                ${r.trace && r.trace.length ? r.trace.map(t => `<div>• Checked <code>${escapeHtml(t.field || 'group')}</code> ${escapeHtml(t.operator || '')} ${escapeHtml(String(t.target || ''))}: actual=<strong>${escapeHtml(String(t.actual))}</strong> (${t.passed ? 'PASS' : 'FAIL'})</div>`).join('') : 'Evaluated as true'}
            </div>
        </div>
    `).join('');
}

// ==========================================
// EXECUTION LOGS TAB
// ==========================================

async function loadExecutionLogs() {
    try {
        const res = await fetch(`/api/logs?status=${state.selectedLogStatus}&limit=50`);
        if (!res.ok) return;
        const data = await res.json();
        state.logs = data.logs || [];
        renderLogsTable();
    } catch (err) {
        console.error('Error loading execution logs:', err);
    }
}

function filterLogsByStatus(status) {
    state.selectedLogStatus = status;
    document.querySelectorAll('#tab-logs .filter-pill').forEach(pill => {
        pill.classList.toggle('active', pill.textContent.toLowerCase().includes(status));
    });
    loadExecutionLogs();
}

function renderLogsTable() {
    const tbody = document.getElementById('logsTableBody');
    if (!tbody) return;

    if (!state.logs.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center" style="padding: 24px; color: var(--text-muted);">No execution logs found.</td></tr>';
        return;
    }

    tbody.innerHTML = state.logs.map((log, idx) => `
        <tr>
            <td style="font-family: var(--font-mono); font-size: 11px;">${escapeHtml(log.timestamp)}</td>
            <td><strong>${escapeHtml(log.rule_name)}</strong></td>
            <td><code style="color: var(--cyan-glow);">${escapeHtml(log.event_name)}</code></td>
            <td><span class="status-badge ${log.status}">${log.status.toUpperCase()}</span></td>
            <td style="font-family: var(--font-mono);">${log.duration_ms} ms</td>
            <td>
                <button class="hud-btn outline" style="padding: 3px 8px; font-size: 11px;" onclick="openLogDetail(${idx})">Inspect Trace</button>
            </td>
        </tr>
    `).join('');
}

function openLogDetail(idx) {
    const log = state.logs[idx];
    if (!log) return;

    const modalBody = document.getElementById('logDetailContent');
    modalBody.innerHTML = `
        <div style="font-size: 13px; line-height: 1.8;">
            <p><strong>Rule:</strong> ${escapeHtml(log.rule_name)} (ID: <code>${escapeHtml(log.rule_id)}</code>)</p>
            <p><strong>Trigger Event:</strong> <code>${escapeHtml(log.event_name)}</code> (${escapeHtml(log.trigger_type)})</p>
            <p><strong>Execution Status:</strong> <span class="status-badge ${log.status}">${log.status.toUpperCase()}</span></p>
            <p><strong>Execution Latency:</strong> ${log.duration_ms} ms</p>
            ${log.error_message ? `<p style="color:var(--red-glow);"><strong>Error:</strong> ${escapeHtml(log.error_message)}</p>` : ''}
            
            <h4 style="margin: 16px 0 8px 0; color: var(--cyan-glow); font-family: var(--font-heading);">Condition Evaluation Trace:</h4>
            <div style="background: rgba(0,0,0,0.4); padding: 12px; border-radius: 6px; font-family: var(--font-mono); font-size: 12px;">
                ${log.trace && log.trace.length ? log.trace.map(t => `
                    <div>• Condition [<code>${escapeHtml(t.field || 'subgroup')}</code>] ${escapeHtml(t.operator || '')} ${escapeHtml(String(t.target || ''))}: actual=<strong>${escapeHtml(String(t.actual))}</strong> &rarr; ${t.passed ? '<span style="color:var(--emerald-glow);">TRUE</span>' : '<span style="color:var(--red-glow);">FALSE</span>'}</div>
                `).join('') : 'No explicit condition checks recorded.'}
            </div>

            <h4 style="margin: 16px 0 8px 0; color: var(--cyan-glow); font-family: var(--font-heading);">Dispatched Action Outputs:</h4>
            <div style="background: rgba(0,0,0,0.4); padding: 12px; border-radius: 6px; font-family: var(--font-mono); font-size: 11px; max-height: 200px; overflow-y: auto;">
                <pre>${escapeHtml(JSON.stringify(log.results, null, 2))}</pre>
            </div>
        </div>
    `;
    document.getElementById('logDetailModal').style.display = 'flex';
}

function closeLogModal() {
    document.getElementById('logDetailModal').style.display = 'none';
}

async function clearAllLogs() {
    if (!confirm('Are you sure you want to clear all execution audit logs?')) return;
    try {
        const res = await fetch('/api/logs', { method: 'DELETE' });
        if (res.ok) {
            showToast('Execution logs cleared', 'success');
            loadExecutionLogs();
            pollTelemetry();
        }
    } catch (err) {
        showToast('Failed to clear logs', 'error');
    }
}

// ==========================================
// BLUEPRINTS GALLERY
// ==========================================

async function loadBlueprints() {
    try {
        const res = await fetch('/api/presets');
        if (!res.ok) return;
        const data = await res.json();
        state.blueprints = data.presets || [];
        renderBlueprintsGrid();
    } catch (err) {
        console.error('Error loading blueprints:', err);
    }
}

function renderBlueprintsGrid() {
    const container = document.getElementById('blueprintsGrid');
    if (!container) return;

    container.innerHTML = state.blueprints.map(bp => `
        <div class="blueprint-card">
            <div>
                <div class="blueprint-header">
                    <span class="rule-category-badge">${escapeHtml(bp.category)}</span>
                    <span class="rule-priority-tag">P${bp.priority}</span>
                </div>
                <div class="blueprint-name">${escapeHtml(bp.name)}</div>
                <div class="blueprint-desc">${escapeHtml(bp.description)}</div>
                <div class="rule-specs">
                    <div class="rule-spec-row">
                        <span>Trigger:</span>
                        <span>${escapeHtml(bp.trigger?.event_name || '*')}</span>
                    </div>
                    <div class="rule-spec-row">
                        <span>Actions:</span>
                        <span>${(bp.actions || []).length} Configured</span>
                    </div>
                </div>
            </div>
            <button class="hud-btn primary" style="width: 100%; justify-content: center; margin-top: 14px;" onclick="installBlueprint('${bp.id}')">
                ⚡ Install Blueprint
            </button>
        </div>
    `).join('');
}

async function installBlueprint(blueprintId) {
    try {
        const res = await fetch('/api/presets/install', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ preset_id: blueprintId })
        });
        const data = await res.json();
        if (data.success) {
            showToast(data.message, 'success');
            loadRules();
            pollTelemetry();
        } else {
            showToast(`Install error: ${data.error}`, 'error');
        }
    } catch (err) {
        showToast('Failed to install blueprint', 'error');
    }
}

// ==========================================
// IN-APP NOTIFICATIONS DRAWER
// ==========================================

function toggleNotificationsDrawer() {
    const drawer = document.getElementById('notifDrawer');
    if (!drawer) return;
    drawer.style.display = drawer.style.display === 'block' ? 'none' : 'block';
}

async function pollNotifications() {
    try {
        const res = await fetch('/api/notifications');
        if (!res.ok) return;
        const data = await res.json();
        state.notifications = data.notifications || [];

        const unreadCount = state.notifications.filter(n => !n.read).length;
        const badge = document.getElementById('notifCountBadge');
        if (badge) {
            if (unreadCount > 0) {
                badge.textContent = unreadCount;
                badge.style.display = 'inline-block';
            } else {
                badge.style.display = 'none';
            }
        }

        renderNotificationsList();
    } catch (err) {
        console.error('Error polling notifications:', err);
    }
}

function renderNotificationsList() {
    const list = document.getElementById('notifList');
    if (!list) return;

    if (!state.notifications.length) {
        list.innerHTML = '<div class="notif-empty">No alerts in system</div>';
        return;
    }

    list.innerHTML = state.notifications.slice(0, 10).map(n => `
        <div class="notif-item ${n.severity}">
            <div class="title">${escapeHtml(n.title)}</div>
            <div class="msg">${escapeHtml(n.message)}</div>
            <div class="time">${escapeHtml(n.timestamp)}</div>
        </div>
    `).join('');
}

async function markNotificationsRead() {
    try {
        await fetch('/api/notifications/read', { method: 'POST' });
        pollNotifications();
    } catch (err) {}
}

async function clearNotifications() {
    try {
        await fetch('/api/notifications', { method: 'DELETE' });
        pollNotifications();
        showToast('Alerts cleared', 'success');
    } catch (err) {}
}

// ==========================================
// SETTINGS IMPORT
// ==========================================

async function importRulesFile(event) {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async (e) => {
        try {
            const json = JSON.parse(e.target.result);
            const res = await fetch('/api/import', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(json)
            });
            const data = await res.json();
            if (data.success) {
                showToast(data.message, 'success');
                loadRules();
                pollTelemetry();
            } else {
                showToast(data.error, 'error');
            }
        } catch (err) {
            showToast('Invalid JSON file format', 'error');
        }
    };
    reader.readAsText(file);
}

// ==========================================
// TOAST MESSAGES & UTILITIES
// ==========================================

function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    const icon = type === 'success' ? '✓' : type === 'error' ? '⚠' : 'ℹ';
    toast.innerHTML = `<span>${icon}</span> <span>${escapeHtml(message)}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
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
