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
    initTheme();
    initClock();
    initEnterpriseSidebar();
    initCommandPalette();
    initAuthAndTenancy();
    checkBillingUrlParams();
    checkAuthUrlParams();
    checkSystemReadiness();
    refreshAllData();

    // Telemetry and status poll (every 2.5 seconds)
    setInterval(pollTelemetry, 2500);

    // Event stream & notifications poll (every 5 seconds)
    setInterval(pollNotifications, 5000);

    // Section 22 Performance: Immediate poll when user switches back to active tab
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            pollTelemetry(true);
            pollNotifications(true);
        }
    });
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
        if (res.ok) {
            const data = await res.json();
            state.currentUser = data.user;
            state.currentOrg = data.current_organization || data.organization;
            state.userRole = data.role || 'admin';
            updateUserBadgeUI();
            updateAuthHeaderUI(true);
            closeAuthModal(true);
            loadOrganizationsList();
        } else {
            state.currentUser = null;
            state.currentOrg = null;
            state.userRole = 'guest';
            updateUserBadgeUI();
            updateAuthHeaderUI(false);
            openAuthModal('login', true);
        }
    } catch (e) {
        console.error('Failed to load user/org state:', e);
        state.currentUser = null;
        state.currentOrg = null;
        state.userRole = 'guest';
        updateUserBadgeUI();
        updateAuthHeaderUI(false);
        openAuthModal('login', true);
    }
}

function updateAuthHeaderUI(isLoggedIn) {
    const signOutBtn = document.getElementById('headerSignOutBtn');
    const signInBtn = document.getElementById('headerSignInBtn');
    const registerBtn = document.getElementById('headerRegisterBtn');
    const nameEl = document.getElementById('currentUserName');
    const badgeEl = document.getElementById('currentUserRoleBadge');
    const authControls = document.getElementById('headerAuthControls');
    const accountWrapper = document.getElementById('accountMenuWrapper');
    const avatarEl = document.getElementById('userAvatarCircle');
    const menuNameEl = document.getElementById('accountMenuName');
    const menuEmailEl = document.getElementById('accountMenuEmail');
    const menuOrgEl = document.getElementById('accountMenuOrg');

    if (isLoggedIn) {
        if (authControls) authControls.style.display = 'none';
        if (accountWrapper) accountWrapper.style.display = 'flex';
        if (signOutBtn) signOutBtn.style.display = 'inline-flex';
        if (signInBtn) signInBtn.style.display = 'none';
        if (registerBtn) registerBtn.style.display = 'none';

        const fullName = (state.currentUser && (state.currentUser.full_name || state.currentUser.email)) || 'Sarah Lin';
        const email = (state.currentUser && state.currentUser.email) || 'admin@opsflow.io';
        const orgName = (state.currentOrg && state.currentOrg.name) || 'Acme Enterprise Global';

        if (nameEl) nameEl.textContent = fullName;
        if (badgeEl) {
            const role = (state.userRole || 'admin').toUpperCase();
            badgeEl.textContent = role;
            badgeEl.className = `role-badge ${role.toLowerCase()}`;
        }
        if (avatarEl) {
            const initials = fullName.split(' ').map(p => p[0]).join('').substring(0, 2).toUpperCase() || 'SL';
            avatarEl.textContent = initials;
        }
        if (menuNameEl) menuNameEl.textContent = fullName;
        if (menuEmailEl) menuEmailEl.textContent = email;
        if (menuOrgEl) menuOrgEl.textContent = orgName;
    } else {
        if (authControls) authControls.style.display = 'flex';
        if (accountWrapper) accountWrapper.style.display = 'none';
        if (signOutBtn) signOutBtn.style.display = 'none';
        if (signInBtn) signInBtn.style.display = 'inline-flex';
        if (registerBtn) registerBtn.style.display = 'inline-flex';
        if (nameEl) nameEl.textContent = 'Guest / Unauthenticated';
        if (badgeEl) {
            badgeEl.textContent = 'GUEST';
            badgeEl.className = 'role-badge viewer';
        }
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
                opt.textContent = org.name;
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
    loadBillingStatus();
    pollNotifications();
}

// ==========================================
// NAVIGATION & TABS
// ==========================================

function switchTab(tabId) {
    if (tabId === 'studio') tabId = 'rules';
    state.currentTab = tabId;
    updateBreadcrumb(tabId);

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
    if (tabId === 'whatsapp') {
        loadWhatsAppDashboard();
        startWhatsAppAutoPoll();
    } else {
        stopWhatsAppAutoPoll();
    }
    if (tabId === 'logs') loadExecutionLogs();
    if (tabId === 'incidents') loadIncidents();
    if (tabId === 'apikeys') loadApiKeys();
    if (tabId === 'team') loadTeamAndAudits();
    if (tabId === 'billing') loadBillingDashboard();
    if (tabId === 'settings') loadAllSettings();
}

// ==========================================
// TELEMETRY & SYSTEM HEALTH
// ==========================================

function updateNavBadge(id, count) {
    const el = document.getElementById(id);
    if (!el) return;
    const num = parseInt(count, 10) || 0;
    el.textContent = num;
    el.style.display = num > 0 ? 'inline-flex' : 'none';
}

async function pollTelemetry(force = false) {
    if (!force && typeof document !== 'undefined' && document.hidden) return;
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
        const totalExecs = stats.total_executions || 0;
        const successExecs = stats.successful_executions || 0;
        const failedExecs = stats.failed_executions !== undefined ? stats.failed_executions : Math.max(0, totalExecs - successExecs);

        const totalRules = stats.total_rules || 0;
        const activeRules = stats.active_rules || 0;

        const statActiveRulesEl = document.getElementById('statActiveRules');
        if (statActiveRulesEl) statActiveRulesEl.textContent = `${activeRules} / ${totalRules}`;
        const statTotalRulesEl = document.getElementById('statTotalRules');
        if (statTotalRulesEl) statTotalRulesEl.textContent = `${totalRules} Total Configured`;

        const statTotalExecsEl = document.getElementById('statTotalExecutions');
        if (statTotalExecsEl) statTotalExecsEl.textContent = totalExecs.toLocaleString();
        const statSuccessExecsEl = document.getElementById('statSuccessExecutions');
        if (statSuccessExecsEl) statSuccessExecsEl.textContent = `${successExecs.toLocaleString()} Successful Dispatches`;

        const statFailedExecsEl = document.getElementById('statFailedExecutions');
        if (statFailedExecsEl) statFailedExecsEl.textContent = failedExecs.toLocaleString();
        const statFailedExecsSubEl = document.getElementById('statFailedExecutionsSub');
        if (statFailedExecsSubEl) statFailedExecsSubEl.textContent = `${failedExecs.toLocaleString()} Unresolved Failures`;

        const statSuccessRateEl = document.getElementById('statSuccessRate');
        const statSuccessRateSubEl = document.getElementById('statSuccessRateSub');
        if (statSuccessRateEl) {
            if (totalExecs === 0) {
                statSuccessRateEl.textContent = '—';
                if (statSuccessRateSubEl) statSuccessRateSubEl.textContent = 'No executions yet';
            } else {
                const rate = stats.success_rate !== undefined ? stats.success_rate : Math.round((successExecs / totalExecs) * 100);
                statSuccessRateEl.textContent = `${rate}%`;
                if (statSuccessRateSubEl) statSuccessRateSubEl.textContent = `${successExecs} / ${totalExecs} succeeded`;
            }
        }

        const statOpenIncidentsEl = document.getElementById('statOpenIncidents');
        if (statOpenIncidentsEl) statOpenIncidentsEl.textContent = stats.open_alerts || 0;
        const statAckIncidentsEl = document.getElementById('statAckIncidents');
        if (statAckIncidentsEl) statAckIncidentsEl.textContent = `${stats.acknowledged_alerts || 0} Acknowledged`;

        const statActiveWebhooksEl = document.getElementById('statActiveWebhooks');
        if (statActiveWebhooksEl) statActiveWebhooksEl.textContent = stats.active_webhooks || 0;

        const highLeadsEl = document.getElementById('statHighPriorityLeads');
        if (highLeadsEl) highLeadsEl.textContent = stats.high_priority_leads || 0;
        const totalLeadsEl = document.getElementById('statTotalLeads');
        if (totalLeadsEl) totalLeadsEl.textContent = `${stats.total_leads || 0} Total Inquiries`;

        updateNavBadge('tabLeadCount', stats.total_leads || 0);
        updateNavBadge('tabIncidentCount', stats.open_alerts || 0);

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
        if (!res.ok) {
            const tbody = document.getElementById('rulesTableBody');
            if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="empty-cell" style="color: #ef4444;">Failed to load rules: ${res.statusText} (Please Sign In)</td></tr>`;
            return;
        }
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

    // Update summary pills
    const activeCount = state.rules.filter(r => r.enabled === 1 || r.enabled === true).length;
    const totalRuns = state.rules.reduce((acc, r) => acc + (r.execution_count || 0), 0);
    const activePill = document.getElementById('wfStudioActiveCount');
    if (activePill) activePill.textContent = activeCount;
    const totalPill = document.getElementById('wfStudioTotalCount');
    if (totalPill) totalPill.textContent = state.rules.length;
    const runsPill = document.getElementById('wfStudioRunsCount');
    if (runsPill) runsPill.textContent = totalRuns.toLocaleString();

    if (state.rules.length === 0) {
        tbody.innerHTML = renderEmptyStateRow({
            colspan: 7,
            icon: '⚡',
            title: 'No workflows found in this category',
            description: 'Automate incident remediation, lead routing, webhook processing, and alert escalation with custom workflows.',
            actionHtml: '<button type="button" class="hud-btn primary small" onclick="openNewRuleModal()"><span>+</span> Create New Workflow</button>'
        });
        return;
    }

    tbody.innerHTML = state.rules.map(rule => {
        const isEnabled = rule.enabled === 1 || rule.enabled === true;
        const trigger = rule.trigger || {};
        let triggerDisplay = '';
        const trigType = (trigger.type || 'event').toLowerCase();
        if (trigType === 'webhook') {
            triggerDisplay = `🔌 Webhook: ${escapeHtml(trigger.event_name || '*')}`;
        } else if (trigType === 'cron' || trigType === 'schedule') {
            triggerDisplay = `⏱️ Cron: ${escapeHtml(trigger.schedule || '*')}`;
        } else if (trigType === 'natural_text' || trigType === 'nlp') {
            triggerDisplay = `🧠 NLP Intent`;
        } else {
            triggerDisplay = `⚡ Event: ${escapeHtml(trigger.event_name || 'custom')}`;
        }

        const isViewer = state.userRole === 'viewer';
        const runsCount = rule.execution_count || 0;
        const lastRunText = runsCount === 0 || !rule.last_triggered || rule.last_triggered === 'Never'
            ? '<span class="never-run-badge">Never run</span>'
            : `<span style="font-size: 0.78rem; color: #cbd5e1;">${escapeHtml(rule.last_triggered)}</span>`;

        return `
            <tr class="workflow-row" style="cursor: pointer;" onclick="handleRuleRowClick(event, '${rule.id}')" title="Click row to inspect full workflow details">
                <td>
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <button type="button" class="toggle-switch ${isEnabled ? 'on' : 'off'}" 
                                onclick="toggleRuleEnabled('${rule.id}')"
                                title="Toggle Rule State: ${isEnabled ? 'Active' : 'Paused'}" ${isViewer ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : ''}>
                            <span class="toggle-slider"></span>
                        </button>
                        <span class="status-pill ${isEnabled ? 'active' : 'paused'}" style="font-size: 10px; padding: 2px 7px;">
                            ${isEnabled ? '● Active' : '⏸ Paused'}
                        </span>
                    </div>
                </td>
                <td>
                    <div class="wf-title-cell">
                        <strong class="wf-name-text">${escapeHtml(rule.name)}</strong>
                        <div class="wf-desc-sub" title="${escapeHtml(rule.description || '')}">${escapeHtml(rule.description || 'No description provided')}</div>
                    </div>
                </td>
                <td><span class="category-chip ${rule.category ? rule.category.toLowerCase() : 'system'}">${rule.category || 'System'}</span></td>
                <td><code class="trigger-code-pill">${triggerDisplay}</code></td>
                <td style="text-align: center;"><span style="font-family: var(--font-mono); font-size: 0.85rem; font-weight: 700; color: #f1f5f9;">${runsCount.toLocaleString()}</span></td>
                <td>${lastRunText}</td>
                <td style="text-align: right;" onclick="event.stopPropagation()">
                    <div class="action-btn-row" style="justify-content: flex-end; align-items: center; gap: 6px;">
                        <button type="button" class="hud-btn primary small run-primary-btn" onclick="executeRuleDirectly(this, '${rule.id}')" title="Execute Workflow Now">
                            <span>⚡</span> Run
                        </button>
                        <div class="action-overflow-wrapper" style="position: relative; display: inline-block;">
                            <button type="button" class="action-overflow-btn" onclick="toggleActionOverflow(event, '${rule.id}')" title="More Actions">
                                &bull;&bull;&bull;
                            </button>
                            <div class="action-overflow-menu" id="overflow-menu-${rule.id}" style="display: none;">
                                <button type="button" class="overflow-item" onclick="openRuleDetailsDrawer('${rule.id}')">
                                    <span class="overflow-icon">ℹ️</span> View Details
                                </button>
                                <button type="button" class="overflow-item" onclick="runDryRunTest('${rule.id}')">
                                    <span class="overflow-icon">🧪</span> Test (Dry Run)
                                </button>
                                <button type="button" class="overflow-item" onclick="duplicateRule('${rule.id}')" ${isViewer ? 'disabled style="opacity:0.5;"' : ''}>
                                    <span class="overflow-icon">📋</span> Duplicate
                                </button>
                                <button type="button" class="overflow-item" onclick="editRule('${rule.id}')" ${isViewer ? 'disabled style="opacity:0.5;"' : ''}>
                                    <span class="overflow-icon">✏️</span> Edit Rule
                                </button>
                                <div class="overflow-divider"></div>
                                <button type="button" class="overflow-item danger" onclick="deleteRule('${rule.id}')" ${isViewer ? 'disabled style="opacity:0.5;"' : ''}>
                                    <span class="overflow-icon">🗑️</span> Delete Rule
                                </button>
                            </div>
                        </div>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function handleRuleRowClick(event, ruleId) {
    if (event.target.closest('button') || event.target.closest('.toggle-switch') || event.target.closest('input') || event.target.closest('a') || event.target.closest('.action-overflow-wrapper') || event.target.closest('.action-btn-row')) {
        return;
    }
    openRuleDetailsDrawer(ruleId);
}

function toggleActionOverflow(event, ruleId) {
    event.stopPropagation();
    const menuId = `overflow-menu-${ruleId}`;
    const allMenus = document.querySelectorAll('.action-overflow-menu');
    allMenus.forEach(m => {
        if (m.id !== menuId) m.style.display = 'none';
    });
    const currentMenu = document.getElementById(menuId);
    if (currentMenu) {
        currentMenu.style.display = currentMenu.style.display === 'block' ? 'none' : 'block';
    }
}

function openRuleDetailsDrawer(ruleId) {
    const rule = state.rules.find(r => String(r.id) === String(ruleId));
    if (!rule) return;
    state.activeDrawerRuleId = ruleId;

    const drawer = document.getElementById('workflowDetailsDrawer');
    const overlay = document.getElementById('workflowDetailsDrawerOverlay');
    if (!drawer || !overlay) return;

    document.getElementById('drawerRuleName').textContent = rule.name || 'Unnamed Workflow';
    document.getElementById('drawerRuleDesc').textContent = rule.description || 'No description provided.';
    const catEl = document.getElementById('drawerRuleCategory');
    if (catEl) {
        catEl.textContent = rule.category || 'System';
        catEl.className = `category-chip ${rule.category ? rule.category.toLowerCase() : 'system'}`;
    }
    document.getElementById('drawerRulePriority').textContent = rule.priority || 10;
    document.getElementById('drawerRuleCooldown').textContent = `${rule.cooldown_seconds || 0}s`;
    document.getElementById('drawerRuleRuns').textContent = (rule.execution_count || 0).toLocaleString();

    const isEnabled = rule.enabled === 1 || rule.enabled === true;
    document.getElementById('drawerRuleStatus').innerHTML = isEnabled
        ? '<span class="status-dot green"></span> Active'
        : '<span class="status-dot red"></span> Paused';

    const trigger = rule.trigger || {};
    const triggerBox = document.getElementById('drawerTriggerBox');
    if (triggerBox) {
        triggerBox.innerHTML = `<code>Type: <strong>${escapeHtml(trigger.type || 'event')}</strong> &bull; Event: <strong>${escapeHtml(trigger.event_name || '*')}</strong></code>`;
    }

    const conditionsBox = document.getElementById('drawerConditionsBox');
    if (conditionsBox) {
        const conds = (rule.conditions && rule.conditions.all) ? rule.conditions.all : (rule.conditions || []);
        if (Array.isArray(conds) && conds.length > 0) {
            conditionsBox.innerHTML = conds.map(c => `
                <div style="background:#0b1120; border:1px solid var(--border-color); border-radius:6px; padding:8px 12px; font-size:12px; font-family:var(--font-mono); color:#38bdf8; margin-bottom:6px;">
                    ${escapeHtml(c.field || '')} <strong style="color:#f59e0b;">${escapeHtml(c.operator || '==')}</strong> "${escapeHtml(String(c.value !== undefined ? c.value : ''))}"
                </div>
            `).join('');
        } else {
            conditionsBox.innerHTML = '<span style="color:#64748b; font-size:13px;">No evaluation conditions (rule triggers on all matching events).</span>';
        }
    }

    const actionsBox = document.getElementById('drawerActionsBox');
    if (actionsBox) {
        const actions = rule.actions || [];
        if (actions.length > 0) {
            actionsBox.innerHTML = actions.map((a, idx) => `
                <div style="background:#0b1120; border:1px solid var(--border-color); border-radius:6px; padding:10px 12px; font-size:12px; display:flex; align-items:flex-start; gap:10px; margin-bottom:6px;">
                    <span style="display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; border-radius:50%; background:rgba(0,240,255,0.15); color:var(--cyan-glow); font-weight:700; font-size:11px;">${idx + 1}</span>
                    <div style="flex:1;">
                        <strong style="color:#f8fafc; font-size:13px;">${escapeHtml(a.type || 'Action')}</strong>
                        <div style="font-size:11px; color:#94a3b8; font-family:var(--font-mono); margin-top:2px;">${escapeHtml(JSON.stringify(a.params || {}))}</div>
                    </div>
                </div>
            `).join('');
        } else {
            actionsBox.innerHTML = '<span style="color:#64748b; font-size:13px;">No actions configured.</span>';
        }
    }

    overlay.style.display = 'block';
    setTimeout(() => drawer.classList.add('open'), 10);
}

function closeRuleDetailsDrawer() {
    const drawer = document.getElementById('workflowDetailsDrawer');
    const overlay = document.getElementById('workflowDetailsDrawerOverlay');
    if (drawer) drawer.classList.remove('open');
    if (overlay) {
        setTimeout(() => overlay.style.display = 'none', 250);
    }
}

function openExecutionConsoleFromDrawer() {
    if (state.activeDrawerRuleId) {
        const id = state.activeDrawerRuleId;
        closeRuleDetailsDrawer();
        openExecutionConsole(id);
    }
}

function runDryRunFromDrawer() {
    if (state.activeDrawerRuleId) {
        runDryRunTest(state.activeDrawerRuleId);
    }
}

function editRuleFromDrawer() {
    if (state.activeDrawerRuleId) {
        const id = state.activeDrawerRuleId;
        closeRuleDetailsDrawer();
        editRule(id);
    }
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

async function executeRuleDirectly(btn, ruleId) {
    const originalText = btn.innerHTML;
    try {
        btn.disabled = true;
        btn.innerHTML = '<span>⏳</span> Running...';
        
        const res = await fetch(`/api/v1/rules/${ruleId}/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dry_run: false, payload: { test_source: "manual_ui", timestamp: new Date().toISOString() } })
        });
        
        const data = await res.json();
        if (res.ok) {
            showToast(`Workflow executed: ${data.status.toUpperCase()}`, 'success');
            loadExecutionLogs();
            loadRules();
        } else {
            showToast(data.error || 'Execution failed', 'error');
        }
    } catch (e) {
        showToast(`Execution error: ${e.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
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

async function editRule(ruleId) {
    let rule = state.rules.find(r => String(r.id) === String(ruleId));
    if (!rule) {
        try {
            const res = await fetch(`/api/v1/rules/${ruleId}`);
            if (res.ok) {
                const data = await res.json();
                rule = data.rule || data;
            }
        } catch (e) {
            console.error('Failed to fetch rule details:', e);
        }
    }
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

    if (!state.webhooks || state.webhooks.length === 0) {
        tbody.innerHTML = renderEmptyStateRow({
            colspan: 7,
            icon: '🔗',
            title: 'No webhooks configured yet',
            description: 'Connect Datadog, Stripe, GitHub, AWS SNS, or custom services to trigger automated workflows.',
            actionHtml: '<button type="button" class="hud-btn primary small" onclick="openNewWebhookModal()"><span>+</span> Create Inbound Webhook</button>'
        });
        return;
    }

    tbody.innerHTML = state.webhooks.map(wh => {
        const securityBadge = wh.secret_configured
            ? '<span class="status-pill green" style="font-size: 0.75rem;">🛡️ HMAC Protected</span>'
            : '<span class="status-pill blue" style="font-size: 0.75rem;">Standard Token</span>';

        return `
            <tr>
                <td>
                    <div style="font-weight: 600; color: #f8fafc;">${escapeHtml(wh.name)}</div>
                    <div style="font-size: 0.75rem; color: #94a3b8; font-family: monospace;">${escapeHtml(wh.id)}</div>
                </td>
                <td>${securityBadge}</td>
                <td>
                    <div style="display: flex; align-items: center; gap: 8px; max-width: 380px;">
                        <code style="font-size: 0.75rem; color: var(--emerald-glow); background: rgba(16, 185, 129, 0.08); padding: 4px 8px; border-radius: 6px; border: 1px solid rgba(16, 185, 129, 0.2); word-break: break-all; flex: 1;">${escapeHtml(wh.webhook_url)}</code>
                        <button class="hud-btn small outline" style="padding: 3px 8px; font-size: 0.72rem; white-space: nowrap; flex-shrink: 0;" onclick="copyWebhookUrl('${wh.webhook_url}')" title="Copy Ingestion URL">📋 Copy</button>
                    </div>
                </td>
                <td><span style="font-size:0.8rem; color:var(--text-muted);">${escapeHtml(wh.target_rule_id || 'All Matching Rules')}</span></td>
                <td><span style="font-weight:700; font-family:var(--font-mono); color: #f8fafc;">${wh.request_count || 0} reqs</span></td>
                <td style="font-size:0.75rem; color:var(--text-muted);">${escapeHtml(wh.last_received_at || 'Never run')}</td>
                <td>
                    <div style="display: flex; gap: 6px; align-items: center;">
                        <button class="action-btn cyan-btn" style="padding: 4px 8px; font-size: 0.75rem;" onclick="testWebhookEndpoint('${wh.id}', '${wh.webhook_url}', ${Boolean(wh.secret_configured)})" title="Test Webhook Ingestion">⚡ Test</button>
                        <button class="action-btn destructive-danger" style="padding: 4px 8px; font-size: 0.75rem;" onclick="promptDeleteWebhook('${wh.id}', '${escapeHtml(wh.name)}')" title="Delete Webhook">🗑️ Delete</button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

async function testWebhookEndpoint(id, url, isHmac) {
    if (isHmac) {
        showToast('Webhook has HMAC verification active. In live environments, send signed payloads with X-Hub-Signature-256.', 'info');
    }
    showToast('Sending test signal to webhook endpoint...', 'info');
    try {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                event: 'system.metrics',
                cpu_percent: 91.2,
                source: 'OpsFlow Webhook Test Console',
                test_id: id,
                timestamp: new Date().toISOString()
            })
        });
        const data = await res.json();
        if (res.ok) {
            showToast('✅ Webhook test successful! Signal received and processed.', 'success');
            loadWebhooks();
            pollTelemetry();
        } else {
            showToast(`Webhook responded (${res.status}): ${data.error || 'Check signature / payload'}`, res.status === 401 ? 'warning' : 'error');
        }
    } catch (err) {
        showToast(`Webhook network test error: ${err.message}`, 'error');
    }
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

function promptDeleteWebhook(id, name) {
    openSafetyConfirmModal({
        title: 'Delete Webhook Endpoint',
        message: `Are you sure you want to permanently delete webhook connector "${name || id}"? Inbound events targeting this endpoint will be rejected.`,
        detail: `Target Endpoint: /api/v1/webhooks/${id} (DELETE)`,
        confirmBtnText: 'Delete Webhook',
        onConfirm: () => executeDeleteWebhook(id)
    });
}

function deleteWebhook(id) {
    promptDeleteWebhook(id);
}

async function executeDeleteWebhook(id) {
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

    if (!state.logs || state.logs.length === 0) {
        tbody.innerHTML = renderEmptyStateRow({
            colspan: 7,
            icon: '📊',
            title: 'No execution records yet',
            description: 'When automated workflows or incident responders trigger, complete telemetry and step traces will appear here.',
            actionHtml: '<button type="button" class="hud-btn primary small" onclick="switchTab(\'rules\')"><span>⚡</span> View Workflows</button>'
        });
        return;
    }

    tbody.innerHTML = state.logs.map(log => {
        const rawStatus = (log.status || '').toLowerCase();
        const isSuccess = rawStatus === 'success' || rawStatus === 'completed' || rawStatus === 'ok';
        const isSkipped = rawStatus === 'skipped' || rawStatus === 'ignored';
        const badgeClass = isSuccess ? 'status-badge success' : (isSkipped ? 'status-badge skipped' : 'status-badge failed');
        const statusIcon = isSuccess ? '✓' : (isSkipped ? '○' : '✕');

        return `
            <tr>
                <td><code style="font-size:0.8rem; color:var(--text-muted);">${log.id}</code></td>
                <td><strong>${escapeHtml(log.rule_name || 'System Dispatcher')}</strong></td>
                <td><code style="color:var(--cyan-glow);">${escapeHtml(log.trigger_event || log.event_name)}</code></td>
                <td><span class="${badgeClass}">${statusIcon} ${(log.status || 'SUCCESS').toUpperCase()}</span></td>
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
    if (!recent || recent.length === 0) {
        tbody.innerHTML = renderEmptyStateRow({
            colspan: 5,
            icon: '⚡',
            title: 'No workflow executions yet',
            description: 'Create or run a workflow to start tracking operational activity.',
            actionHtml: '<button type="button" class="hud-btn primary small" onclick="switchTab(\'rules\')">⚡ View Workflows</button>'
        });
        return;
    }

    tbody.innerHTML = recent.map(log => {
        const rawStatus = (log.status || '').toLowerCase();
        const isSuccess = rawStatus === 'success' || rawStatus === 'completed' || rawStatus === 'ok';
        const isSkipped = rawStatus === 'skipped' || rawStatus === 'ignored';
        const badgeClass = isSuccess ? 'status-badge success' : (isSkipped ? 'status-badge skipped' : 'status-badge failed');
        const statusIcon = isSuccess ? '✓' : (isSkipped ? '○' : '✕');
        return `
            <tr>
                <td><span class="${badgeClass}">${statusIcon} ${(log.status || 'SUCCESS').toUpperCase()}</span></td>
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
    const rawStatus = (log.status || '').toLowerCase();
    const isSuccess = rawStatus === 'success' || rawStatus === 'completed' || rawStatus === 'ok';

    content.innerHTML = `
        <div style="display:flex; justify-content:space-between; margin-bottom:12px;">
            <div>
                <strong>Workflow Rule:</strong> ${escapeHtml(log.rule_name || 'System Dispatcher')}<br>
                <strong>Trigger Event:</strong> <code style="color:var(--cyan-glow);">${escapeHtml(log.trigger_event || log.event_name)}</code>
            </div>
            <div style="text-align:right;">
                <strong>Execution Status:</strong> <span style="font-weight:700; color:${isSuccess ? '#10b981' : '#f87171'};">${(log.status || 'SUCCESS').toUpperCase()}</span><br>
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

// Safety Confirmation Modal Handlers
let pendingSafetyAction = null;

function openSafetyConfirmModal({ title, message, detail, confirmBtnText = 'Proceed & Confirm', onConfirm }) {
    const modal = document.getElementById('safetyConfirmModal');
    if (!modal) {
        if (confirm(message)) onConfirm();
        return;
    }
    document.getElementById('safetyModalTitle').textContent = title || 'Confirm Destructive Action';
    document.getElementById('safetyModalMessage').textContent = message || 'Are you sure?';

    const detailBox = document.getElementById('safetyModalDetailBox');
    if (detail) {
        detailBox.textContent = detail;
        detailBox.style.display = 'block';
    } else {
        detailBox.style.display = 'none';
    }

    const confirmBtn = document.getElementById('safetyModalConfirmBtn');
    confirmBtn.textContent = confirmBtnText;
    pendingSafetyAction = onConfirm;

    confirmBtn.onclick = async () => {
        closeSafetyConfirmModal();
        if (typeof pendingSafetyAction === 'function') {
            await pendingSafetyAction();
        }
    };

    modal.style.display = 'flex';
}

function closeSafetyConfirmModal() {
    const modal = document.getElementById('safetyConfirmModal');
    if (modal) modal.style.display = 'none';
    pendingSafetyAction = null;
}

function handleSafetyModalOverlayClick(e) {
    if (e.target && e.target.id === 'safetyConfirmModal') {
        closeSafetyConfirmModal();
    }
}

function promptPurgeLogsModal() {
    openSafetyConfirmModal({
        title: 'Purge Execution Forensic Logs',
        message: 'Are you sure you want to permanently clear all historical workflow execution logs and mock test traces? This action cannot be undone.',
        detail: 'Target Endpoint: /api/v1/executions (DELETE)',
        confirmBtnText: 'Purge All Logs',
        onConfirm: executePurgeAllLogs
    });
}

async function executePurgeAllLogs() {
    try {
        let res = await fetch('/api/v1/executions', { method: 'DELETE' });
        if (!res.ok) {
            res = await fetch('/api/executions', { method: 'DELETE' });
        }
        const data = await res.json();
        if (res.ok) {
            state.logs = [];
            renderLogsTable();
            renderDashboardMiniLogs();
            showToast('Execution forensic logs purged successfully.', 'success');
            pollTelemetry(true);
        } else {
            showToast(data.error || 'Failed to clear logs', 'error');
        }
    } catch (e) {
        showToast(`Clear error: ${e.message}`, 'error');
    }
}

function clearAllLogs() {
    promptPurgeLogsModal();
}

function promptClearAlertsModal() {
    openSafetyConfirmModal({
        title: 'Clear All Active Incident Alerts',
        message: 'Are you sure you want to dismiss and clear all active alerts across the workspace?',
        detail: 'Target Endpoint: /api/v1/alerts/clear & /api/notifications (DELETE)',
        confirmBtnText: 'Clear All Alerts',
        onConfirm: executeClearAllNotifications
    });
}

async function executeClearAllNotifications() {
    try {
        let res = await fetch('/api/v1/alerts/clear', { method: 'POST' });
        if (!res.ok) {
            res = await fetch('/api/notifications', { method: 'DELETE' });
        }
        showToast('All alerts cleared successfully.', 'success');
        loadIncidents();
        pollTelemetry(true);
    } catch (e) {
        showToast(`Clear alerts error: ${e.message}`, 'error');
    }
}

function clearNotifications() {
    promptClearAlertsModal();
}

function formatManualPayloadJson() {
    const el = document.getElementById('manualEventPayload');
    if (!el) return;
    try {
        const parsed = JSON.parse(el.value);
        el.value = JSON.stringify(parsed, null, 2);
        showToast('JSON payload formatted.', 'info');
    } catch (e) {
        showToast('Invalid JSON: ' + e.message, 'error');
    }
}

function formatConsolePayloadJson() {
    const el = document.getElementById('execConsolePayload');
    if (!el) return;
    try {
        const parsed = JSON.parse(el.value);
        el.value = JSON.stringify(parsed, null, 2);
        showToast('Console payload formatted.', 'info');
    } catch (e) {
        showToast('Invalid JSON: ' + e.message, 'error');
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
        updateNavBadge('tabIncidentCount', openCount);
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

    if (!state.incidents || state.incidents.length === 0) {
        container.innerHTML = renderEmptyStateCard({
            icon: '🛡️',
            title: 'All systems operational',
            description: 'No incidents in this queue. Security and reliability guardrails are actively monitoring events.'
        });
        return;
    }

    const isViewer = state.userRole === 'viewer';

    container.innerHTML = state.incidents.map(inc => {
        const sevClass = `severity-pill ${inc.severity ? inc.severity.toLowerCase() : 'info'}`;
        const statusClass = `status-badge ${inc.status.toLowerCase()}`;
        const statusIcon = inc.status === 'open' ? '⚠' : (inc.status === 'acknowledged' ? '👁' : '✓');

        return `
            <div class="incident-card">
                <div class="incident-main">
                    <div class="incident-title-row">
                        <span class="${sevClass}">${inc.severity.toUpperCase()}</span>
                        <span class="incident-title">${escapeHtml(inc.title)}</span>
                        <span class="${statusClass}">${statusIcon} ${inc.status.toUpperCase()}</span>
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
    if (!openList || openList.length === 0) {
        container.innerHTML = `
            <div style="padding: 32px 16px; text-align: center;">
                <div style="font-size: 1.8rem; margin-bottom: 8px;">🛡️</div>
                <div style="font-weight: 600; color: #10b981; font-size: 0.95rem; margin-bottom: 4px;">No incidents</div>
                <div style="font-size: 0.8rem; color: #94a3b8;">Your workspace currently has no open incidents. All operational systems are healthy.</div>
            </div>
        `;
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

    if (!state.apiKeys || state.apiKeys.length === 0) {
        tbody.innerHTML = renderEmptyStateRow({
            colspan: 6,
            icon: '🔑',
            title: 'No API keys yet',
            description: 'Generate programmatic API tokens to integrate OpsFlow Cloud into your CI/CD pipelines, backend services, or monitoring scripts.',
            actionHtml: '<button type="button" class="hud-btn primary small" onclick="openNewApiKeyModal()"><span>+</span> Generate API Key</button>'
        });
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
        loadBillingStatus();

        const memRes = await fetch('/api/v1/team/members');
        if (memRes.ok) {
            const data = await memRes.json();
            state.teamMembers = data.members || [];

            // Update seats count in panel header if present
            const seatCountEl = document.getElementById('teamSeatCount');
            const seatLimitEl = document.getElementById('teamSeatLimit');
            if (data.seats) {
                if (seatCountEl) seatCountEl.textContent = data.seats.current;
                if (seatLimitEl) seatLimitEl.textContent = data.seats.limit;
            } else if (seatCountEl && seatLimitEl) {
                seatCountEl.textContent = state.teamMembers.length;
                seatLimitEl.textContent = '10';
            }

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

    if (!state.teamMembers || state.teamMembers.length === 0) {
        tbody.innerHTML = renderEmptyStateRow({
            colspan: 5,
            icon: '👥',
            title: 'No team members found',
            description: 'Collaborate with engineers and operators by inviting members with role-based access control.',
            actionHtml: '<button type="button" class="hud-btn primary small" onclick="openAddMemberModal()"><span>+</span> Invite Member</button>'
        });
        return;
    }

    const isManager = ['owner', 'admin'].includes((state.userRole || '').toLowerCase());
    const currentUserId = state.currentUser ? state.currentUser.id : null;

    tbody.innerHTML = state.teamMembers.map(m => {
        const u = m.user || {};
        const memberId = m.user_id || u.id || m.membership_id || m.id;
        const fullName = m.full_name || u.full_name || 'Team Member';
        const email = m.email || u.email || '';
        const role = (m.role || 'viewer').toLowerCase();
        const joined = m.joined_at || m.created_at || 'Active';
        const isSelf = currentUserId && (currentUserId === memberId || (u && u.id === currentUserId));

        let roleCol = `<span class="role-badge ${role}">${role.toUpperCase()}</span>`;
        let actionsCol = '<span style="color:var(--text-dim); font-size:11px;">-</span>';

        if (isManager) {
            roleCol = `
                <select class="custom-sleek-select" style="min-width: 105px; padding: 4px 8px; font-size: 11px;" onchange="changeMemberRole('${memberId}', this.value)">
                    <option value="owner" ${role === 'owner' ? 'selected' : ''}>Owner</option>
                    <option value="admin" ${role === 'admin' ? 'selected' : ''}>Admin</option>
                    <option value="operator" ${role === 'operator' ? 'selected' : ''}>Operator</option>
                    <option value="viewer" ${role === 'viewer' ? 'selected' : ''}>Viewer</option>
                </select>
            `;
            if (isSelf) {
                actionsCol = `<span style="font-size: 11px; color: var(--text-dim);">(You)</span>`;
            } else {
                actionsCol = `
                    <button class="hud-btn small destructive-danger" style="padding: 3px 8px; font-size: 11px;" onclick="promptRemoveTeamMember('${memberId}', '${escapeHtml(fullName)}')">Remove</button>
                `;
            }
        }

        return `
            <tr>
                <td><strong>${escapeHtml(fullName)}</strong></td>
                <td><code style="color:var(--text-secondary); font-size:12px;">${escapeHtml(email)}</code></td>
                <td>${roleCol}</td>
                <td style="font-size:0.75rem; color:var(--text-muted);">${joined}</td>
                <td>${actionsCol}</td>
            </tr>
        `;
    }).join('');
}

async function changeMemberRole(targetId, newRole) {
    try {
        const res = await fetch(`/api/v1/team/members/${targetId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ role: newRole })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(`Member role updated to ${newRole.toUpperCase()}`, 'success');
            loadTeamAndAudits();
        } else {
            showToast(data.error || 'Failed to update member role', 'error');
            loadTeamAndAudits();
        }
    } catch (err) {
        showToast('Role update error: ' + err.message, 'error');
        loadTeamAndAudits();
    }
}

function promptRemoveTeamMember(targetId, name) {
    openSafetyConfirmModal({
        title: 'Remove Team Member',
        message: `Are you sure you want to remove "${name || 'this member'}" from the workspace? They will immediately lose all RBAC access and permissions.`,
        detail: `Target: Member ID ${targetId} (/api/v1/team/members/${targetId})`,
        confirmBtnText: 'Remove Member',
        onConfirm: () => executeRemoveTeamMember(targetId)
    });
}

function removeTeamMember(targetId, name) {
    promptRemoveTeamMember(targetId, name);
}

async function executeRemoveTeamMember(targetId) {
    try {
        const res = await fetch(`/api/v1/team/members/${targetId}`, {
            method: 'DELETE'
        });
        const data = await res.json();
        if (res.ok) {
            showToast('Member removed from workspace', 'success');
            loadTeamAndAudits();
        } else {
            showToast(data.error || 'Failed to remove member', 'error');
        }
    } catch (err) {
        showToast('Member removal error: ' + err.message, 'error');
    }
}

function renderAuditTrail() {
    const tbody = document.getElementById('auditTrailTableBody');
    if (!tbody) return;

    if (!state.auditLogs || state.auditLogs.length === 0) {
        tbody.innerHTML = renderEmptyStateRow({
            colspan: 5,
            icon: '📋',
            title: 'No audit events recorded yet',
            description: 'Administrative actions, authentication events, and workflow modifications will appear here with cryptographic integrity.'
        });
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
        const res = await fetch('/api/v1/team/invite', {
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
// STRIPE BILLING & SUBSCRIPTIONS (Phase 4)
// ==========================================

let currentBillingInterval = 'month';

async function loadBillingStatus() {
    try {
        const res = await fetch('/api/v1/billing/status');
        if (!res.ok) return;
        const data = await res.json();

        const planBadge = document.getElementById('orgPlanTier');
        const billingBadge = document.getElementById('billingBadge');
        const maxRules = document.getElementById('orgMaxRules');
        const maxEvents = document.getElementById('orgMaxEvents');
        const slug = document.getElementById('orgSlug');
        const billingPlanName = document.getElementById('billingPlanName');
        const billingPeriodInfo = document.getElementById('billingPeriodInfo');
        const billingStatusBadge = document.getElementById('billingStatusBadge');

        const tierName = (data.plan_tier || 'free').toUpperCase();
        const tierTitle = (data.plan_tier || 'free').charAt(0).toUpperCase() + (data.plan_tier || 'free').slice(1);
        const sub = data.subscription || {};
        const rawSubStatus = (sub.status || (data.plan_tier === 'free' ? 'active' : 'unmanaged')).toUpperCase();
        const subStatus = ['UNMANAGED'].includes(rawSubStatus) ? 'ACTIVE' : rawSubStatus;

        // Top Header Plan Indicator
        const headerPlanText = document.getElementById('headerPlanText');
        if (headerPlanText) headerPlanText.textContent = tierName;
        const headerPlanTextSecondary = document.getElementById('headerPlanTextSecondary');
        if (headerPlanTextSecondary) headerPlanTextSecondary.textContent = tierName;

        // Executive Overview Dashboard (tab-dashboard) Cards & Strip
        const dashPlanTier = document.getElementById('dashPlanTier');
        if (dashPlanTier) dashPlanTier.textContent = `${tierTitle} Tier`;

        const dashBillingBadge = document.getElementById('dashBillingBadge');
        if (dashBillingBadge) {
            dashBillingBadge.textContent = subStatus;
            dashBillingBadge.className = `metric-badge ${['ACTIVE', 'TRIALING'].includes(subStatus) ? 'active' : 'warn'}`;
        }

        const dashPlanDesc = document.getElementById('dashPlanDesc');
        if (dashPlanDesc) {
            dashPlanDesc.textContent = data.is_stripe_configured
                ? (sub.cancel_at_period_end ? 'Cancels at period end' : 'Stripe Connected')
                : 'Local / Free Tier';
        }

        const dashBannerPlanBadge = document.getElementById('dashBannerPlanBadge');
        if (dashBannerPlanBadge) {
            dashBannerPlanBadge.textContent = `${tierName} TIER`;
            dashBannerPlanBadge.className = `status-badge ${data.plan_tier === 'free' ? '' : 'active'}`;
        }

        const dashBannerSubBadge = document.getElementById('dashBannerSubBadge');
        if (dashBannerSubBadge) dashBannerSubBadge.textContent = `${subStatus} SUBSCRIPTION`;

        const dashBannerRules = document.getElementById('dashBannerRulesCount');
        if (dashBannerRules && data.quotas) {
            dashBannerRules.textContent = `${data.quotas.current_rules || 0} / ${data.quotas.max_rules || 3}`;
        }

        const dashBannerEvents = document.getElementById('dashBannerEventsCount');
        if (dashBannerEvents && data.quotas) {
            dashBannerEvents.textContent = `${Number(data.quotas.current_monthly_events || 0).toLocaleString()} / ${Number(data.quotas.max_monthly_events || 1000).toLocaleString()}`;
        }

        const dashBannerSeats = document.getElementById('dashBannerSeatsCount');
        if (dashBannerSeats) {
            const curSeats = state.teamMembers ? state.teamMembers.length : 1;
            const maxSeats = (data.entitlements && data.entitlements.quotas && data.entitlements.quotas.team_members && data.entitlements.quotas.team_members.limit) || 1;
            dashBannerSeats.textContent = `${curSeats} / ${maxSeats}`;
        }

        // Team & RBAC Tab (tab-team) Elements
        if (planBadge) planBadge.textContent = `${tierName} TIER`;
        if (slug && data.organization_slug) slug.textContent = `slug: ${data.organization_slug}`;
        if (maxRules && data.quotas) maxRules.textContent = `${data.quotas.max_rules} Rules`;
        if (maxEvents && data.quotas) maxEvents.textContent = Number(data.quotas.max_monthly_events).toLocaleString();

        if (billingBadge) billingBadge.textContent = subStatus;
        if (billingStatusBadge) {
            billingStatusBadge.textContent = `${subStatus} SUBSCRIPTION`;
            billingStatusBadge.className = `status-badge ${sub.status === 'active' ? 'active' : 'warn'}`;
        }
        if (billingPlanName) {
            billingPlanName.textContent = `Current Plan: ${tierTitle} Tier`;
        }
        if (billingPeriodInfo) {
            const interval = sub.billing_interval || 'monthly';
            const gateway = data.is_stripe_configured ? 'Stripe Gateway Connected' : 'Local / Free Tier Mode';
            billingPeriodInfo.textContent = `Billing Cycle: ${interval.toUpperCase()} | ${gateway}`;
        }
    } catch (e) {
        console.error('Failed to load billing status:', e);
    }
}

function openUpgradePlanModal() {
    const modal = document.getElementById('upgradePlanModal');
    if (modal) modal.style.display = 'flex';
}

function closeUpgradePlanModal() {
    const modal = document.getElementById('upgradePlanModal');
    if (modal) modal.style.display = 'none';
}

function setBillingInterval(interval) {
    setTabBillingInterval(interval);
}

function setTabBillingInterval(interval) {
    currentBillingInterval = interval;

    const tabBtnMonth = document.getElementById('tabBillingIntervalMonth');
    const tabBtnYear = document.getElementById('tabBillingIntervalYear');
    const tabPriceStarter = document.getElementById('tabPriceStarter');
    const tabPricePro = document.getElementById('tabPricePro');
    const tabPriceEnterprise = document.getElementById('tabPriceEnterprise');

    const modalBtnMonth = document.getElementById('btnIntervalMonth');
    const modalBtnYear = document.getElementById('btnIntervalYear');
    const modalPriceStarter = document.getElementById('priceStarter');
    const modalPricePro = document.getElementById('pricePro');
    const modalPriceEnterprise = document.getElementById('priceEnterprise');

    if (interval === 'year') {
        if (tabBtnYear) tabBtnYear.className = 'hud-btn primary';
        if (tabBtnMonth) tabBtnMonth.className = 'hud-btn outline';
        if (tabPriceStarter) tabPriceStarter.innerHTML = '$290<span style="font-size: 13px; color: var(--text-dim);">/yr</span>';
        if (tabPricePro) tabPricePro.innerHTML = '$990<span style="font-size: 13px; color: var(--text-dim);">/yr</span>';
        if (tabPriceEnterprise) tabPriceEnterprise.innerHTML = '$4,990<span style="font-size: 13px; color: var(--text-dim);">/yr</span>';

        if (modalBtnYear) modalBtnYear.className = 'hud-btn primary';
        if (modalBtnMonth) modalBtnMonth.className = 'hud-btn outline';
        if (modalPriceStarter) modalPriceStarter.innerHTML = '$290<span style="font-size: 13px; color: var(--text-dim, #888);">/yr</span>';
        if (modalPricePro) modalPricePro.innerHTML = '$990<span style="font-size: 13px; color: var(--text-dim, #888);">/yr</span>';
        if (modalPriceEnterprise) modalPriceEnterprise.innerHTML = '$4,990<span style="font-size: 13px; color: var(--text-dim, #888);">/yr</span>';
    } else {
        if (tabBtnMonth) tabBtnMonth.className = 'hud-btn primary';
        if (tabBtnYear) tabBtnYear.className = 'hud-btn outline';
        if (tabPriceStarter) tabPriceStarter.innerHTML = '$29<span style="font-size: 13px; color: var(--text-dim);">/mo</span>';
        if (tabPricePro) tabPricePro.innerHTML = '$99<span style="font-size: 13px; color: var(--text-dim);">/mo</span>';
        if (tabPriceEnterprise) tabPriceEnterprise.innerHTML = '$499<span style="font-size: 13px; color: var(--text-dim);">/mo</span>';

        if (modalBtnMonth) modalBtnMonth.className = 'hud-btn primary';
        if (modalBtnYear) modalBtnYear.className = 'hud-btn outline';
        if (modalPriceStarter) modalPriceStarter.innerHTML = '$29<span style="font-size: 13px; color: var(--text-dim, #888);">/mo</span>';
        if (modalPricePro) modalPricePro.innerHTML = '$99<span style="font-size: 13px; color: var(--text-dim, #888);">/mo</span>';
        if (modalPriceEnterprise) modalPriceEnterprise.innerHTML = '$499<span style="font-size: 13px; color: var(--text-dim, #888);">/mo</span>';
    }
}

async function selectPlanForCheckout(planTier) {
    try {
        showToast(`Starting Stripe Checkout for ${planTier.toUpperCase()} plan...`, 'info');
        const res = await fetch('/api/v1/billing/checkout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                plan_tier: planTier,
                interval: currentBillingInterval
            })
        });
        const data = await res.json();
        if (res.ok && data.checkout_url) {
            window.location.href = data.checkout_url;
        } else {
            showToast(data.error || 'Failed to start Stripe checkout.', 'error');
        }
    } catch (err) {
        showToast(`Checkout error: ${err.message}`, 'error');
    }
}

async function openCustomerPortal() {
    try {
        showToast('Accessing Stripe Customer Portal...', 'info');
        const res = await fetch('/api/v1/billing/portal', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const data = await res.json();
        if (res.ok && data.portal_url) {
            window.location.href = data.portal_url;
        } else {
            showToast(data.error || 'Could not open billing portal.', 'error');
        }
    } catch (err) {
        showToast(`Billing portal error: ${err.message}`, 'error');
    }
}

async function confirmCancelSubscription() {
    if (!confirm('Are you sure you want to cancel your paid subscription? Your workspace will downgrade to the Free tier.')) {
        return;
    }
    try {
        showToast('Processing subscription cancellation...', 'info');
        const res = await fetch('/api/v1/billing/cancel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'Subscription cancelled successfully.', 'success');
            loadBillingDashboard();
            loadBillingStatus();
            pollTelemetry();
        } else {
            showToast(data.error || 'Failed to cancel subscription.', 'error');
        }
    } catch (err) {
        showToast(`Cancellation error: ${err.message}`, 'error');
    }
}

function updatePlanCardsUI(currentTier) {
    const tiers = ['free', 'starter', 'pro', 'enterprise'];
    const rank = { 'free': 0, 'starter': 1, 'pro': 2, 'enterprise': 3 };
    const curRank = rank[currentTier] !== undefined ? rank[currentTier] : 0;

    tiers.forEach(t => {
        const titleCase = t.charAt(0).toUpperCase() + t.slice(1);
        const card = document.getElementById(`planCard${titleCase}`);
        const action = document.getElementById(`planAction${titleCase}`);
        if (!action) return;

        if (t === currentTier) {
            action.innerHTML = '<span class="status-badge active" style="width: 100%; display: block; text-align: center; padding: 8px 0; font-weight: 600;">✓ Current Plan</span>';
            if (card) card.style.borderColor = 'var(--cyan-glow, #00f0ff)';
        } else if (t === 'free') {
            action.innerHTML = '<button class="hud-btn outline" style="width: 100%;" onclick="confirmCancelSubscription()">Downgrade to Free</button>';
            if (card) card.style.borderColor = 'var(--border-color, #2a2e3d)';
        } else {
            const isUpgrade = rank[t] > curRank;
            const btnClass = t === 'pro' ? 'hud-btn primary' : (t === 'enterprise' ? 'hud-btn emerald' : 'hud-btn outline');
            const label = isUpgrade ? `Upgrade to ${titleCase}` : `Switch to ${titleCase}`;
            action.innerHTML = `<button class="${btnClass}" style="width: 100%;" onclick="selectPlanForCheckout('${t}')">${label}</button>`;
            if (card && t !== 'pro') {
                card.style.borderColor = t === 'enterprise' ? '#10b981' : (t === 'starter' ? 'var(--cyan-glow, #00f0ff)' : 'var(--border-color, #2a2e3d)');
            }
        }
    });
}

async function loadBillingDashboard() {
    try {
        const [billingRes, membersRes] = await Promise.all([
            fetch('/api/v1/billing/status'),
            fetch('/api/v1/organizations/members')
        ]);

        if (!billingRes.ok) {
            console.error('Failed to load billing status for dashboard');
            return;
        }

        const data = await billingRes.json();
        let teamMembersCount = 1;
        if (membersRes.ok) {
            const memData = await membersRes.json();
            if (memData.members && Array.isArray(memData.members)) {
                teamMembersCount = memData.members.length;
                state.teamMembers = memData.members;
            }
        }

        const tier = (data.plan_tier || 'free').toLowerCase();
        const tierName = tier.charAt(0).toUpperCase() + tier.slice(1);
        const rawStatus = (sub.status || (tier === 'free' ? 'active' : 'active')).toUpperCase();
        const displayStatus = ['UNMANAGED'].includes(rawStatus) ? 'ACTIVE' : rawStatus;

        // 1. Header & Gateway Notices
        const headerBadge = document.getElementById('tabBillingHeaderBadge');
        if (headerBadge) {
            headerBadge.textContent = `${tier.toUpperCase()} TIER`;
            headerBadge.className = `status-badge ${tier === 'free' ? '' : 'active'}`;
        }

        const devNotice = document.getElementById('stripeDevNotice');
        if (devNotice) {
            devNotice.style.display = data.is_stripe_configured ? 'none' : 'block';
        }

        // 2. Overview Card
        const overviewBadge = document.getElementById('tabBillingOverviewBadge');
        if (overviewBadge) {
            overviewBadge.textContent = displayStatus;
            overviewBadge.className = `metric-badge ${['ACTIVE', 'TRIALING'].includes(displayStatus) ? 'active' : 'warn'}`;
        }

        const overviewPlan = document.getElementById('tabBillingOverviewPlan');
        if (overviewPlan) {
            overviewPlan.textContent = `${tierName} Plan`;
        }

        const overviewCycle = document.getElementById('tabBillingOverviewCycle');
        if (overviewCycle) {
            if (tier === 'free') {
                overviewCycle.textContent = 'Free Community Tier • Unlimited Duration';
            } else {
                const interval = (sub.billing_interval || 'month') === 'year' ? 'Annually' : 'Monthly';
                let renewText = sub.cancel_at_period_end ? 'Cancels at period end' : 'Auto-renewing';
                if (sub.current_period_end) {
                    try {
                        const d = new Date(sub.current_period_end * 1000);
                        if (!isNaN(d.getTime())) {
                            renewText += ` • Next renewal: ${d.toLocaleDateString()}`;
                        }
                    } catch (e) {}
                }
                overviewCycle.textContent = `Billed ${interval} • ${renewText}`;
            }
        }

        // 3. Quota Capacity Meters
        const quotas = data.quotas || {};
        const entitlements = data.entitlements || {};

        // Rules Quota
        const curRules = quotas.current_rules || 0;
        const maxRules = quotas.max_rules || (entitlements.max_rules || 3);
        const rulesPct = maxRules > 0 ? Math.min(100, Math.round((curRules / maxRules) * 100)) : 0;

        const rulesBadge = document.getElementById('tabBillingRulesUsageBadge');
        if (rulesBadge) rulesBadge.textContent = `${rulesPct}% used`;

        const rulesLimit = document.getElementById('tabBillingRulesLimit');
        if (rulesLimit) rulesLimit.textContent = `${curRules} / ${maxRules}`;

        const rulesProg = document.getElementById('tabBillingRulesProgress');
        if (rulesProg) {
            rulesProg.style.width = `${rulesPct}%`;
            rulesProg.style.background = rulesPct >= 90 ? '#ef4444' : (rulesPct >= 75 ? '#f59e0b' : 'var(--cyan-glow, #00f0ff)');
        }

        // Monthly Events Quota
        const curEvents = quotas.current_monthly_events || 0;
        const maxEvents = quotas.max_monthly_events || (entitlements.max_monthly_events || 1000);
        const eventsPct = maxEvents > 0 ? Math.min(100, Math.round((curEvents / maxEvents) * 100)) : 0;

        const eventsBadge = document.getElementById('tabBillingEventsUsageBadge');
        if (eventsBadge) eventsBadge.textContent = `${eventsPct}% used`;

        const eventsLimit = document.getElementById('tabBillingEventsLimit');
        if (eventsLimit) eventsLimit.textContent = `${curEvents.toLocaleString()} / ${Number(maxEvents).toLocaleString()}`;

        const eventsProg = document.getElementById('tabBillingEventsProgress');
        if (eventsProg) {
            eventsProg.style.width = `${eventsPct}%`;
            eventsProg.style.background = eventsPct >= 90 ? '#ef4444' : (eventsPct >= 75 ? '#f59e0b' : '#10b981');
        }

        // Team Seats Capacity
        const maxSeats = (entitlements.quotas && entitlements.quotas.team_members && entitlements.quotas.team_members.limit) || entitlements.max_team_members || (tier === 'free' ? 1 : (tier === 'starter' ? 2 : (tier === 'pro' ? 10 : 100)));
        const curSeats = teamMembersCount;
        const seatsPct = maxSeats > 0 ? Math.min(100, Math.round((curSeats / maxSeats) * 100)) : 0;

        const seatsBadge = document.getElementById('tabBillingSeatsUsageBadge');
        if (seatsBadge) seatsBadge.textContent = `${seatsPct}% used`;

        const seatsLimit = document.getElementById('tabBillingSeatsLimit');
        if (seatsLimit) seatsLimit.textContent = `${curSeats} / ${maxSeats}`;

        const seatsProg = document.getElementById('tabBillingSeatsProgress');
        if (seatsProg) {
            seatsProg.style.width = `${seatsPct}%`;
            seatsProg.style.background = seatsPct >= 90 ? '#ef4444' : '#f59e0b';
        }

        // 4. Update Plan Matrix Action Buttons
        updatePlanCardsUI(tier);

        // 5. Subscription & Gateway Details Section
        const subIdEl = document.getElementById('tabBillingDetailsSubId');
        if (subIdEl) {
            if (sub.stripe_subscription_id) {
                subIdEl.textContent = `Stripe Subscription ID: ${sub.stripe_subscription_id} (${subStatus})`;
            } else if (tier === 'free') {
                subIdEl.textContent = 'Stripe Subscription: Active Free Community Tier';
            } else {
                subIdEl.textContent = `Stripe Subscription: Direct ${tierName} Allocation`;
            }
        }

        const custIdEl = document.getElementById('tabBillingDetailsCustId');
        if (custIdEl) {
            if (data.stripe_customer_id) {
                custIdEl.textContent = `Stripe Customer ID: ${data.stripe_customer_id} | Portal: Fully Enabled`;
            } else {
                custIdEl.textContent = 'Billing Profile: Not yet provisioned on Stripe (Created automatically upon checkout)';
            }
        }

        // Also synchronize the Team tab billing summary card
        loadBillingStatus();
    } catch (err) {
        console.error('Failed to load billing dashboard:', err);
    }
}

function checkBillingUrlParams() {
    const urlParams = new URLSearchParams(window.location.search);
    const billingStatus = urlParams.get('billing_status') || urlParams.get('status');
    const sessionId = urlParams.get('billing_session') || urlParams.get('session_id');

    if (sessionId && billingStatus === 'success') {
        showToast('Payment successful! Your Stripe subscription is active.', 'success');
        const cleanUrl = window.location.protocol + "//" + window.location.host + window.location.pathname;
        window.history.replaceState({ path: cleanUrl }, '', cleanUrl);
        setTimeout(() => {
            if (typeof switchTab === 'function') {
                switchTab('billing');
            }
        }, 300);
    } else if (billingStatus === 'cancelled') {
        showToast('Stripe checkout was cancelled. No charges were made.', 'info');
        const cleanUrl = window.location.protocol + "//" + window.location.host + window.location.pathname;
        window.history.replaceState({ path: cleanUrl }, '', cleanUrl);
    }
}

function checkAuthUrlParams() {
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('token') || urlParams.get('reset_token');
    const isResetPage = window.location.pathname.includes('reset-password');

    if (token || isResetPage) {
        openAuthModal('reset', false);
        if (token) {
            const tokenInput = document.getElementById('resetTokenInput');
            if (tokenInput) tokenInput.value = token;
        }
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
            state.currentOrg = data.organization || (data.active_org_id ? { id: data.active_org_id } : null);
            state.userRole = data.role;
            updateUserBadgeUI();
            closePersonaModal();
            showToast(`Logged in as ${data.user.full_name} (${data.role.toUpperCase()})`, 'success');
            await initAuthAndTenancy();
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
            <div class="blueprint-card" style="cursor: pointer;" onclick="if (!event.target.closest('button')) installBlueprint('${bp.id}')" title="Click to install template into active workspace">
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

async function pollNotifications(force = false) {
    if (!force && typeof document !== 'undefined' && document.hidden) return;
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

/**
 * Reusable Enterprise Empty State Card generator (Section 26).
 */
function renderEmptyStateCard({ icon = '📂', title = 'No records found', description = '', actionHtml = '' } = {}) {
    return `
        <div class="hud-empty-state">
            <div class="empty-icon">${icon}</div>
            <div class="empty-title">${escapeHtml(title)}</div>
            ${description ? `<p class="empty-desc">${escapeHtml(description)}</p>` : ''}
            ${actionHtml ? `<div class="empty-action">${actionHtml}</div>` : ''}
        </div>
    `;
}

/**
 * Reusable Enterprise Empty State Row generator for HTML tables (Section 26).
 */
function renderEmptyStateRow({ colspan = 7, icon = '📂', title = 'No records found', description = '', actionHtml = '' } = {}) {
    return `
        <tr>
            <td colspan="${colspan}" class="hud-empty-state-cell">
                ${renderEmptyStateCard({ icon, title, description, actionHtml })}
            </td>
        </tr>
    `;
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

    updateNavBadge('tabLeadCount', leads.length);
}

function renderLeads(leads) {
    const tbody = document.getElementById('leadsTableBody');
    if (!tbody) return;

    if (!leads || !leads.length) {
        if (!leadsCache || !leadsCache.length) {
            tbody.innerHTML = renderEmptyStateRow({
                colspan: 8,
                icon: '📭',
                title: 'No customer inquiries yet',
                description: 'New leads will appear here when received via webhook, website contact forms, or manual intake.',
                actionHtml: '<button type="button" class="hud-btn primary small" onclick="openNewLeadModal()"><span>+</span> Ingest New Lead</button>'
            });
        } else {
            tbody.innerHTML = renderEmptyStateRow({
                colspan: 8,
                icon: '🔍',
                title: 'No matching leads found',
                description: 'No CRM leads match current filter criteria.',
                actionHtml: '<button type="button" class="hud-btn outline small" onclick="resetLeadFilters()">Reset Filters</button>'
            });
        }
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
    const intentVal = document.getElementById('leadIntentFilter')?.value || 'all';
    const deptVal = document.getElementById('leadDeptFilter')?.value || 'all';

    const filtered = leadsCache.filter(l => {
        const matchesSearch = !searchVal || 
            (l.name || '').toLowerCase().includes(searchVal) ||
            (l.email || '').toLowerCase().includes(searchVal) ||
            (l.company || '').toLowerCase().includes(searchVal) ||
            (l.message || '').toLowerCase().includes(searchVal);

        const matchesStatus = statusVal === 'all' || l.status === statusVal;
        const matchesIntent = intentVal === 'all' || (l.intent || '').toLowerCase() === intentVal.toLowerCase();
        const matchesDept = deptVal === 'all' || (l.route_department || '').toLowerCase() === deptVal.toLowerCase();

        return matchesSearch && matchesStatus && matchesIntent && matchesDept;
    });

    renderLeads(filtered);
}

function resetLeadFilters() {
    const s = document.getElementById('leadSearchInput'); if (s) s.value = '';
    const st = document.getElementById('leadStatusFilter'); if (st) st.value = 'all';
    const it = document.getElementById('leadIntentFilter'); if (it) it.value = 'all';
    const dp = document.getElementById('leadDeptFilter'); if (dp) dp.value = 'all';
    renderLeads(leadsCache);
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

// ==========================================
// PHASE 5: CUSTOMER AUTHENTICATION & ONBOARDING
// ==========================================

function openAuthModal(mode = 'login', isForced = false) {
    const modal = document.getElementById('authModal');
    if (!modal) return;
    switchAuthTab(mode);
    const closeBtn = document.getElementById('authModalCloseBtn');
    if (closeBtn) {
        closeBtn.style.display = 'block';
    }
    modal.style.display = 'flex';
}

function closeAuthModal(force = false) {
    const modal = document.getElementById('authModal');
    if (modal) modal.style.display = 'none';
}

function switchAuthTab(tab) {
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');
    const forgotForm = document.getElementById('forgotPasswordForm');
    const resetForm = document.getElementById('resetPasswordForm');
    const tabLogin = document.getElementById('authTabLogin');
    const tabRegister = document.getElementById('authTabRegister');
    const tabForgot = document.getElementById('authTabForgot');
    const title = document.getElementById('authModalTitle');
    const subtitle = document.getElementById('authModalSubtitle');
    const tabsContainer = document.getElementById('authTabsContainer');

    // Hide error and success banners
    ['loginErrorMessage', 'registerErrorMessage', 'forgotErrorMessage', 'forgotSuccessMessage', 'forgotDevHelper', 'resetErrorMessage', 'resetSuccessMessage'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });

    // Reset tab active styles
    [tabLogin, tabRegister, tabForgot].forEach(t => {
        if (t) {
            t.classList.remove('active');
            t.style.color = 'var(--text-muted, #94a3b8)';
            t.style.borderBottom = '2px solid transparent';
        }
    });

    // Hide all form panels
    [loginForm, registerForm, forgotForm, resetForm].forEach(f => {
        if (f) f.style.display = 'none';
    });

    if (tab === 'register') {
        if (tabsContainer) tabsContainer.style.display = 'flex';
        if (registerForm) registerForm.style.display = 'block';
        if (tabRegister) {
            tabRegister.classList.add('active');
            tabRegister.style.color = 'var(--cyan-glow, #00f0ff)';
            tabRegister.style.borderBottom = '2px solid var(--cyan-glow, #00f0ff)';
        }
        if (title) title.textContent = 'Create New Workspace';
        if (subtitle) subtitle.textContent = 'Launch your dedicated tenant instance';
    } else if (tab === 'forgot') {
        if (tabsContainer) tabsContainer.style.display = 'none';
        if (forgotForm) forgotForm.style.display = 'block';
        if (title) title.textContent = 'Reset Password';
        if (subtitle) subtitle.textContent = 'Request a secure single-use recovery token';
    } else if (tab === 'reset') {
        if (tabsContainer) tabsContainer.style.display = 'none';
        if (resetForm) resetForm.style.display = 'block';
        if (title) title.textContent = 'Set New Password';
        if (subtitle) subtitle.textContent = 'Enter verification token & choose password';
    } else {
        if (tabsContainer) tabsContainer.style.display = 'flex';
        if (loginForm) loginForm.style.display = 'block';
        if (tabLogin) {
            tabLogin.classList.add('active');
            tabLogin.style.color = 'var(--cyan-glow, #00f0ff)';
            tabLogin.style.borderBottom = '2px solid var(--cyan-glow, #00f0ff)';
        }
        if (title) title.textContent = 'OpsFlow Cloud Authentication';
        if (subtitle) subtitle.textContent = 'Access enterprise automation workspace';
    }
}

function togglePasswordVisibility(inputId, btn) {
    const input = document.getElementById(inputId);
    if (!input) return;
    if (input.type === 'password') {
        input.type = 'text';
        if (btn) btn.textContent = '🙈';
    } else {
        input.type = 'password';
        if (btn) btn.textContent = '👁️';
    }
}

let devResetTokenCache = null;

async function handleForgotPassword(e) {
    if (e) e.preventDefault();
    const email = document.getElementById('forgotEmail').value.trim();
    const errBox = document.getElementById('forgotErrorMessage');
    const succBox = document.getElementById('forgotSuccessMessage');
    const devHelper = document.getElementById('forgotDevHelper');
    const submitBtn = document.getElementById('forgotSubmitBtn');

    if (errBox) errBox.style.display = 'none';
    if (succBox) succBox.style.display = 'none';
    if (devHelper) devHelper.style.display = 'none';

    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Processing request...';
    }

    try {
        const res = await fetch('/api/v1/auth/forgot-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email })
        });
        const data = await res.json();
        if (res.ok) {
            if (succBox) {
                succBox.textContent = data.message || 'If an account exists with that email, a password reset link has been dispatched.';
                succBox.style.display = 'block';
            }
            const resetToken = data.dev_reset_token || data.dev_token;
            if (resetToken) {
                devResetTokenCache = resetToken;
                if (devHelper) devHelper.style.display = 'block';
            }
        } else {
            if (errBox) {
                errBox.textContent = data.error || 'Failed to request password reset.';
                errBox.style.display = 'block';
            }
        }
    } catch (err) {
        if (errBox) {
            errBox.textContent = 'Network error: ' + err.message;
            errBox.style.display = 'block';
        }
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Request Password Reset Link';
        }
    }
}

function applyDevResetToken() {
    if (!devResetTokenCache) return;
    switchAuthTab('reset');
    const tokenInput = document.getElementById('resetTokenInput');
    if (tokenInput) tokenInput.value = devResetTokenCache;
    const newPass = document.getElementById('resetNewPassword');
    if (newPass) setTimeout(() => newPass.focus(), 150);
}

async function handleResetPassword(e) {
    if (e) e.preventDefault();
    const token = document.getElementById('resetTokenInput').value.trim();
    const newPassword = document.getElementById('resetNewPassword').value;
    const confirmPassword = document.getElementById('resetConfirmPassword').value;
    const errBox = document.getElementById('resetErrorMessage');
    const succBox = document.getElementById('resetSuccessMessage');
    const submitBtn = document.getElementById('resetSubmitBtn');

    if (errBox) errBox.style.display = 'none';
    if (succBox) succBox.style.display = 'none';

    if (newPassword.length < 8) {
        if (errBox) {
            errBox.textContent = 'New password must be at least 8 characters.';
            errBox.style.display = 'block';
        }
        return;
    }

    if (newPassword !== confirmPassword) {
        if (errBox) {
            errBox.textContent = 'Passwords do not match.';
            errBox.style.display = 'block';
        }
        return;
    }

    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Updating Password...';
    }

    try {
        const res = await fetch('/api/v1/auth/reset-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token, new_password: newPassword })
        });
        const data = await res.json();
        if (res.ok) {
            if (succBox) {
                succBox.textContent = data.message || 'Password reset successfully! Please sign in with your new password.';
                succBox.style.display = 'block';
            }
            showToast('Password updated successfully. Please sign in.', 'success');
            setTimeout(() => {
                switchAuthTab('login');
                const loginPassword = document.getElementById('loginPassword');
                if (loginPassword) loginPassword.value = '';
            }, 1800);
        } else {
            if (errBox) {
                errBox.textContent = data.error || 'Password reset failed.';
                errBox.style.display = 'block';
            }
        }
    } catch (err) {
        if (errBox) {
            errBox.textContent = 'Network error: ' + err.message;
            errBox.style.display = 'block';
        }
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Update Password & Sign In';
        }
    }
}


function fillDemoCredentials() {
    const email = document.getElementById('loginEmail');
    const pass = document.getElementById('loginPassword');
    if (email) email.value = 'admin@opsflow.io';
    if (pass) pass.value = 'AdminSecure2026!';
}

let slugDebounceTimer = null;

function autoPopulateSlug(name) {
    const slugInput = document.getElementById('regOrgSlug');
    if (!slugInput) return;
    const slug = name.toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '');
    slugInput.value = slug;
    handleSlugInput(slug);
}

function handleSlugInput(val) {
    if (slugDebounceTimer) clearTimeout(slugDebounceTimer);
    slugDebounceTimer = setTimeout(() => {
        checkSlugAvailability(val);
    }, 300);
}

async function checkSlugAvailability(slug) {
    const feedback = document.getElementById('slugFeedback');
    if (!feedback) return;
    const cleanSlug = (slug || '').trim().toLowerCase();
    if (!cleanSlug) {
        feedback.innerHTML = '';
        return;
    }
    feedback.innerHTML = '<span style="color:var(--text-dim, #888);">Checking slug availability...</span>';

    try {
        const res = await fetch(`/api/v1/auth/check-slug?slug=${encodeURIComponent(cleanSlug)}`);
        const data = await res.json();
        if (res.ok && data.available) {
            feedback.innerHTML = `<span style="color:#10b981;">✓ <strong>${escapeHtml(data.slug)}</strong> is available!</span>`;
        } else {
            const suggestion = data.suggestion ? ` (suggestion: <code>${escapeHtml(data.suggestion)}</code>)` : '';
            feedback.innerHTML = `<span style="color:#ef4444;">✗ "${escapeHtml(cleanSlug)}" is taken${suggestion}.</span>`;
        }
    } catch (e) {
        feedback.innerHTML = '';
    }
}

async function handleLogin(e) {
    if (e) e.preventDefault();
    const email = document.getElementById('loginEmail').value.trim();
    const password = document.getElementById('loginPassword').value;
    const errBox = document.getElementById('loginErrorMessage');
    const submitBtn = document.getElementById('loginSubmitBtn');

    if (errBox) errBox.style.display = 'none';
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Authenticating...';
    }

    try {
        const res = await fetch('/api/v1/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        const data = await res.json();
        if (res.ok) {
            closeAuthModal(true);
            showToast(`Welcome back, ${data.user ? data.user.full_name : 'Operator'}!`, 'success');
            await initAuthAndTenancy();
            refreshAllData();
        } else {
            if (errBox) {
                errBox.textContent = data.error || 'Authentication failed. Please check your credentials.';
                errBox.style.display = 'block';
            }
        }
    } catch (err) {
        if (errBox) {
            errBox.textContent = 'Login network error: ' + err.message;
            errBox.style.display = 'block';
        }
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Sign In to Workspace';
        }
    }
}

async function handleRegister(e) {
    if (e) e.preventDefault();
    const full_name = (document.getElementById('regFullName')?.value || '').trim();
    const email = (document.getElementById('regEmail')?.value || '').trim();
    const password = document.getElementById('regPassword')?.value || '';
    const organization_name = (document.getElementById('regOrgName')?.value || '').trim();
    let organization_slug = (document.getElementById('regOrgSlug')?.value || '').trim();
    if (!organization_slug && organization_name) {
        organization_slug = organization_name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
    }
    const plan_tier = document.getElementById('regPlanTier')?.value || 'free';
    const starter_blueprints = document.getElementById('regStarterBlueprints') ? document.getElementById('regStarterBlueprints').checked : true;
    const errBox = document.getElementById('registerErrorMessage');
    const submitBtn = document.getElementById('registerSubmitBtn');

    if (errBox) errBox.style.display = 'none';

    if (password.length < 8) {
        if (errBox) {
            errBox.textContent = 'Password must be at least 8 characters long.';
            errBox.style.display = 'block';
        }
        return;
    }

    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Provisioning Workspace...';
    }

    try {
        const res = await fetch('/api/v1/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                full_name,
                email,
                password,
                organization_name,
                org_name: organization_name,
                organization_slug,
                slug: organization_slug,
                plan_tier,
                starter_blueprints,
                install_starter_blueprints: starter_blueprints
            })
        });
        const data = await res.json();
        if (res.ok) {
            closeAuthModal(true);
            showToast(`Workspace '${data.organization ? data.organization.name : organization_name}' created!`, 'success');
            await initAuthAndTenancy();
            refreshAllData();
            // Launch the 5-step onboarding wizard
            openOnboardingWizard(data);
        } else {
            if (errBox) {
                errBox.textContent = data.error || 'Failed to register workspace.';
                errBox.style.display = 'block';
            }
        }
    } catch (err) {
        if (errBox) {
            errBox.textContent = 'Registration network error: ' + err.message;
            errBox.style.display = 'block';
        }
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Launch Workspace & Begin Tour';
        }
    }
}

async function handleLogout() {
    try {
        await fetch('/api/v1/auth/logout', { method: 'POST' });
    } catch (e) {
        console.error('Logout error:', e);
    }
    state.currentUser = null;
    state.currentOrg = null;
    state.userRole = 'guest';
    updateUserBadgeUI();
    updateAuthHeaderUI(false);
    showToast('Signed out of OpsFlow Cloud.', 'info');
    openAuthModal('login', true);
}

// Onboarding Wizard Implementation
const wizardState = {
    currentStep: 1,
    totalSteps: 5,
    registrationData: null
};

function openOnboardingWizard(data) {
    wizardState.registrationData = data || {};
    wizardState.currentStep = 1;

    const org = (data && data.organization) || {};
    const orgNameEl = document.getElementById('wizOrgName');
    const orgSlugEl = document.getElementById('wizOrgSlug');
    const orgPlanEl = document.getElementById('wizOrgPlan');
    const apiKeyInput = document.getElementById('wizApiKeyInput');

    if (orgNameEl) orgNameEl.textContent = org.name || 'Your Workspace';
    if (orgSlugEl) orgSlugEl.textContent = org.slug || 'workspace-slug';
    if (orgPlanEl) orgPlanEl.textContent = (org.plan_tier || 'FREE').toUpperCase();
    if (apiKeyInput) apiKeyInput.value = (data && data.api_key) || 'sk_live_generated_key';

    renderWizardStep();
    const modal = document.getElementById('onboardingWizardModal');
    if (modal) modal.style.display = 'flex';
}

function closeOnboardingWizard() {
    const modal = document.getElementById('onboardingWizardModal');
    if (modal) modal.style.display = 'none';
}

function renderWizardStep() {
    for (let i = 1; i <= wizardState.totalSteps; i++) {
        const stepEl = document.getElementById(`wizardStep${i}`);
        const pillEl = document.getElementById(`wizardPill${i}`);
        if (stepEl) {
            stepEl.style.display = (i === wizardState.currentStep) ? 'block' : 'none';
        }
        if (pillEl) {
            if (i === wizardState.currentStep) {
                pillEl.classList.add('active');
                pillEl.style.color = 'var(--cyan-glow, #00f0ff)';
                pillEl.style.fontWeight = '700';
            } else if (i < wizardState.currentStep) {
                pillEl.classList.remove('active');
                pillEl.style.color = '#10b981';
                pillEl.style.fontWeight = '500';
            } else {
                pillEl.classList.remove('active');
                pillEl.style.color = 'var(--text-dim, #888)';
                pillEl.style.fontWeight = '400';
            }
        }
    }

    const counter = document.getElementById('wizStepCounter');
    if (counter) counter.textContent = `Step ${wizardState.currentStep} of ${wizardState.totalSteps}`;

    const prevBtn = document.getElementById('wizPrevBtn');
    const nextBtn = document.getElementById('wizNextBtn');

    if (prevBtn) {
        prevBtn.style.visibility = (wizardState.currentStep > 1) ? 'visible' : 'hidden';
    }

    if (nextBtn) {
        if (wizardState.currentStep === wizardState.totalSteps) {
            nextBtn.textContent = 'Finish Tour & Open Dashboard ✓';
            nextBtn.onclick = finishOnboarding;
        } else {
            nextBtn.textContent = 'Next Step →';
            nextBtn.onclick = nextWizardStep;
        }
    }
}

function nextWizardStep() {
    if (wizardState.currentStep < wizardState.totalSteps) {
        wizardState.currentStep++;
        renderWizardStep();
    } else {
        finishOnboarding();
    }
}

function prevWizardStep() {
    if (wizardState.currentStep > 1) {
        wizardState.currentStep--;
        renderWizardStep();
    }
}

function copyOnboardingApiKey() {
    const input = document.getElementById('wizApiKeyInput');
    const btn = document.getElementById('wizCopyKeyBtn');
    if (!input) return;
    input.select();
    navigator.clipboard.writeText(input.value).then(() => {
        if (btn) {
            const origText = btn.innerHTML;
            btn.innerHTML = '✓ Copied!';
            setTimeout(() => { btn.innerHTML = origText; }, 2000);
        }
        showToast('API Key copied to clipboard!', 'success');
    }).catch(() => {
        document.execCommand('copy');
        showToast('API Key copied to clipboard!', 'success');
    });
}

async function sendWizardInvite() {
    const emailInput = document.getElementById('wizInviteEmail');
    const roleSelect = document.getElementById('wizInviteRole');
    const statusBox = document.getElementById('wizInviteStatus');

    if (!emailInput || !emailInput.value.trim()) {
        if (statusBox) statusBox.innerHTML = '<span style="color:#ef4444;">Please enter an email address.</span>';
        return;
    }

    const email = emailInput.value.trim();
    const role = roleSelect ? roleSelect.value : 'operator';

    try {
        const res = await fetch('/api/v1/team/invite', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, role })
        });
        const data = await res.json();
        if (res.ok) {
            if (statusBox) {
                statusBox.innerHTML = `<span style="color:#10b981;">✓ Successfully invited ${escapeHtml(email)} as ${role.toUpperCase()}</span>`;
            }
            emailInput.value = '';
        } else {
            if (statusBox) {
                statusBox.innerHTML = `<span style="color:#ef4444;">✗ ${escapeHtml(data.error || 'Failed to invite team member')}</span>`;
            }
        }
    } catch (e) {
        if (statusBox) statusBox.innerHTML = `<span style="color:#ef4444;">Error: ${escapeHtml(e.message)}</span>`;
    }
}

function finishOnboarding() {
    closeOnboardingWizard();
    switchTab('dashboard');
    refreshAllData();
    showToast('Workspace onboarding complete! Welcome aboard.', 'success');
}

// ==========================================
// Phase 6: Production Automation Console & DLQ / Jobs
// ==========================================

let activeConsoleRuleId = null;

function openExecutionConsole(ruleId) {
    activeConsoleRuleId = ruleId;
    const rule = state.rules.find(r => String(r.id) === String(ruleId)) || {};

    const titleElem = document.getElementById('execConsoleTitle');
    const subtitleElem = document.getElementById('execConsoleSubtitle');
    const resultArea = document.getElementById('execConsoleResultArea');

    if (titleElem) titleElem.textContent = `Workflow Console: ${rule.name || ruleId}`;
    if (subtitleElem) subtitleElem.textContent = `Rule ID: ${ruleId} • Category: ${rule.category || 'System'}`;
    if (resultArea) resultArea.style.display = 'none';

    // Populate initial sample payload
    loadSamplePayloadForCurrentRule();

    const modal = document.getElementById('executionConsoleModal');
    if (modal) modal.style.display = 'flex';
}

function closeExecutionConsole() {
    const modal = document.getElementById('executionConsoleModal');
    if (modal) modal.style.display = 'none';
    activeConsoleRuleId = null;
}

function loadSamplePayloadForCurrentRule() {
    const payloadBox = document.getElementById('execConsolePayload');
    if (!payloadBox) return;

    const rule = state.rules.find(r => String(r.id) === String(activeConsoleRuleId)) || {};
    const trigger = rule.trigger || {};
    const evName = (trigger.event_name || 'system.metrics').toLowerCase();

    let sample = {
        test_source: "execution_console",
        timestamp: new Date().toISOString()
    };

    if (evName.includes('metric') || evName.includes('cpu')) {
        sample.cpu_percent = 92.5;
        sample.ram_percent = 84.0;
        sample.disk_percent = 71.0;
        sample.host = "prod-k8s-node-01";
    } else if (evName.includes('lead')) {
        sample.name = "Alexander Wright";
        sample.email = "awright@fintech-global.corp";
        sample.company = "Fintech Global Corp";
        sample.message = "We need an enterprise contract for 500 seats with dedicated HIPAA SLA.";
    } else if (evName.includes('incident') || evName.includes('alert')) {
        sample.severity = "critical";
        sample.service = "postgres-primary";
        sample.message = "FATAL: Connection pool exhausted. Worker threads unresponsive.";
    } else if (evName.includes('auth')) {
        sample.ip = "192.168.1.100";
        sample.attempts = 15;
        sample.user = "root";
    }

    payloadBox.value = JSON.stringify(sample, null, 2);
}

async function executeWorkflowFromConsole() {
    if (!activeConsoleRuleId) return;

    const payloadBox = document.getElementById('execConsolePayload');
    let payload = {};
    try {
        payload = JSON.parse(payloadBox.value);
    } catch (err) {
        showToast('Invalid JSON in payload editor. Please fix formatting.', 'error');
        return;
    }

    const modeInputs = document.querySelectorAll('input[name="execMode"]');
    let mode = 'live';
    modeInputs.forEach(inp => { if (inp.checked) mode = inp.value; });

    const btn = document.getElementById('btnExecuteWorkflowNow');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Executing...';
    }

    try {
        let endpoint = `/api/v1/rules/${activeConsoleRuleId}/run`;
        let requestBody = { payload: payload };

        if (mode === 'dry_run') {
            requestBody.dry_run = true;
        } else if (mode === 'async') {
            endpoint = `/api/v1/workflows/${activeConsoleRuleId}/dispatch-async`;
        }

        const startTs = performance.now();
        const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody)
        });
        const elapsedMs = Math.round((performance.now() - startTs) * 10) / 10;
        const data = await res.json();

        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Execute Workflow';
        }

        if (!res.ok && res.status !== 202) {
            showToast(data.error || 'Execution failed', 'error');
            return;
        }

        renderExecutionConsoleResult(data, mode, elapsedMs);
        showToast(mode === 'async' ? 'Job dispatched to background worker pool' : `Executed: ${data.status ? data.status.toUpperCase() : 'OK'}`, 'success');

        loadExecutionLogs();
        loadRules();
    } catch (e) {
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Execute Workflow';
        }
        showToast(`Execution request error: ${e.message}`, 'error');
    }
}

function renderExecutionConsoleResult(data, mode, elapsedMs) {
    const resultArea = document.getElementById('execConsoleResultArea');
    const badge = document.getElementById('execConsoleResultBadge');
    const durElem = document.getElementById('execConsoleResultDuration');
    const execIdElem = document.getElementById('execConsoleExecId');
    const stepsContainer = document.getElementById('execConsoleWaterfallSteps');
    const rawJson = document.getElementById('execConsoleRawJson');

    if (!resultArea) return;
    resultArea.style.display = 'block';

    const status = (data.status || (mode === 'async' ? 'QUEUED' : 'SUCCESS')).toUpperCase();
    badge.textContent = status;
    badge.className = `status-badge ${status === 'SUCCESS' || status === 'COMPLETED' ? 'active' : (status === 'QUEUED' || status === 'RUNNING' ? 'amber' : 'failed')}`;

    durElem.textContent = `${data.duration_ms || elapsedMs}ms`;
    execIdElem.textContent = data.execution_id || data.job_id || 'exec-simulated';

    // Steps trace waterfall
    stepsContainer.innerHTML = '';
    const steps = data.steps_trace || [];
    const conditionTrace = data.trace || [];

    // First render condition evaluation step
    if (conditionTrace.length > 0) {
        const condDiv = document.createElement('div');
        condDiv.className = 'hud-panel';
        condDiv.style.padding = '8px 12px';
        condDiv.style.borderRadius = '6px';
        condDiv.style.borderLeft = `3px solid ${data.matched !== false ? '#10b981' : '#f59e0b'}`;
        condDiv.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <strong style="font-size: 12px;">Condition Evaluation</strong>
                <span class="status-badge ${data.matched !== false ? 'active' : 'amber'}" style="font-size: 10px;">${data.matched !== false ? 'MATCHED' : 'NOT MATCHED'}</span>
            </div>
            <div style="font-size: 11px; color: var(--text-dim, #888); margin-top: 4px;">
                ${conditionTrace.map(t => `<code>${escapeHtml(t.field)} ${escapeHtml(t.operator)} ${escapeHtml(String(t.target_value))}</code> (Actual: <code>${escapeHtml(String(t.actual_value))}</code> &rarr; ${t.passed ? '✓' : '✗'})`).join('<br>')}
            </div>
        `;
        stepsContainer.appendChild(condDiv);
    }

    if (steps.length === 0 && (!data.action_results || data.action_results.length === 0)) {
        const emptyDiv = document.createElement('div');
        emptyDiv.style.fontSize = '12px';
        emptyDiv.style.color = 'var(--text-dim, #888)';
        emptyDiv.textContent = mode === 'async' ? 'Job queued in background. Inspect Background Async Jobs tab for live progress.' : 'No pipeline steps executed (conditions evaluated).';
        stepsContainer.appendChild(emptyDiv);
    } else {
        steps.forEach((st, idx) => {
            const stepDiv = document.createElement('div');
            stepDiv.className = 'hud-panel';
            stepDiv.style.padding = '8px 12px';
            stepDiv.style.borderRadius = '6px';
            const isSuccess = st.status === 'SUCCESS' || st.status === 'success';
            stepDiv.style.borderLeft = `3px solid ${isSuccess ? '#10b981' : '#ef4444'}`;
            stepDiv.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span style="font-size: 11px; font-weight: 700; color: var(--text-dim, #888);">#${idx + 1}</span>
                        <strong style="font-size: 12px; color: var(--cyan-glow, #00f0ff);">${escapeHtml(st.name || st.type)}</strong>
                        <span style="font-size: 10px; background: rgba(255,255,255,0.06); padding: 2px 6px; border-radius: 4px; font-family: var(--font-mono);">${escapeHtml(st.type)}</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span style="font-size: 11px; color: var(--text-dim, #888); font-family: var(--font-mono);">${st.duration_ms || 0}ms</span>
                        <span class="status-badge ${isSuccess ? 'active' : 'failed'}" style="font-size: 10px;">${(st.status || 'OK').toUpperCase()}</span>
                    </div>
                </div>
                ${st.error ? `<div style="font-size: 11px; color: #ef4444; margin-top: 4px;">Error: ${escapeHtml(st.error)}</div>` : ''}
                ${st.output ? `<div style="font-size: 11px; color: var(--text-dim, #888); margin-top: 4px; font-family: var(--font-mono); overflow-x: auto;">Output: ${escapeHtml(JSON.stringify(st.output))}</div>` : ''}
            `;
            stepsContainer.appendChild(stepDiv);
        });
    }

    if (rawJson) {
        rawJson.textContent = JSON.stringify(data, null, 2);
    }
}

// Sub-Tab Navigation for Forensics / DLQ / Background Jobs
function switchLogsSubTab(subTabName) {
    const vForensics = document.getElementById('logsSubViewForensics');
    const vDlq = document.getElementById('logsSubViewDlq');
    const vJobs = document.getElementById('logsSubViewJobs');

    const btnForensics = document.getElementById('subtabForensicsBtn');
    const btnDlq = document.getElementById('subtabDlqBtn');
    const btnJobs = document.getElementById('subtabJobsBtn');

    [btnForensics, btnDlq, btnJobs].forEach(b => { if (b) b.classList.remove('active'); });
    if (vForensics) vForensics.style.display = 'none';
    if (vDlq) vDlq.style.display = 'none';
    if (vJobs) vJobs.style.display = 'none';

    if (subTabName === 'dlq') {
        if (btnDlq) btnDlq.classList.add('active');
        if (vDlq) vDlq.style.display = 'block';
        loadDlqItems();
    } else if (subTabName === 'jobs') {
        if (btnJobs) btnJobs.classList.add('active');
        if (vJobs) vJobs.style.display = 'block';
        loadAsyncJobs();
    } else {
        if (btnForensics) btnForensics.classList.add('active');
        if (vForensics) vForensics.style.display = 'block';
        loadExecutionLogs();
    }
}

async function loadDlqItems() {
    const tbody = document.getElementById('dlqTableBody');
    const badge = document.getElementById('countDlqBadge');
    try {
        const res = await fetch('/api/v1/dlq');
        if (!res.ok) return;
        const data = await res.json();
        const items = data.dlq || [];

        if (badge) badge.textContent = items.length;

        if (!tbody) return;
        if (items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="empty-cell">No quarantined payloads in Dead-Letter Queue.</td></tr>';
            return;
        }

        tbody.innerHTML = items.map(item => `
            <tr>
                <td><code style="font-size: 11px; color: #ef4444;">${escapeHtml(item.id || item.dlq_id)}</code></td>
                <td><strong style="color: var(--text-primary); font-size: 12px;">${escapeHtml(item.rule_name || item.rule_id)}</strong></td>
                <td><span class="category-chip system" style="font-size: 11px;">${escapeHtml(item.event_name || 'event')}</span></td>
                <td><div style="font-size: 11px; color: #ef4444; max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(item.error || '')}">${escapeHtml(item.error || 'Execution failed')}</div></td>
                <td><span style="font-family: var(--font-mono); font-size: 12px;">${item.retry_count || 0}</span></td>
                <td style="font-size: 11px; color: var(--text-dim, #888);">${item.timestamp ? item.timestamp.split('T')[0] : 'Just now'}</td>
                <td>
                    <div style="display: flex; gap: 6px;">
                        <button class="action-btn cyan-btn" onclick="replayDlqItem('${item.id || item.dlq_id}')" title="Replay from DLQ">🔄 Replay</button>
                        <button class="action-btn red-btn" onclick="purgeDlqItem('${item.id || item.dlq_id}')" title="Purge DLQ item">🗑️</button>
                    </div>
                </td>
            </tr>
        `).join('');
    } catch (e) {
        console.error('Failed to load DLQ:', e);
    }
}

async function replayDlqItem(dlqId) {
    try {
        const res = await fetch(`/api/v1/dlq/${dlqId}/replay`, { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            showToast(`DLQ item replayed: ${data.status ? data.status.toUpperCase() : 'OK'}`, 'success');
            loadDlqItems();
            loadExecutionLogs();
        } else {
            showToast(data.error || 'DLQ replay failed', 'error');
        }
    } catch (e) {
        showToast(`Replay error: ${e.message}`, 'error');
    }
}

async function purgeDlqItem(dlqId) {
    if (!confirm(`Purge DLQ item '${dlqId}'?`)) return;
    try {
        const res = await fetch(`/api/v1/dlq/${dlqId}`, { method: 'DELETE' });
        const data = await res.json();
        if (res.ok) {
            showToast('DLQ item purged.', 'info');
            loadDlqItems();
        } else {
            showToast(data.error || 'Failed to purge item', 'error');
        }
    } catch (e) {
        showToast(`Purge error: ${e.message}`, 'error');
    }
}

async function loadAsyncJobs() {
    const tbody = document.getElementById('jobsTableBody');
    const badge = document.getElementById('countJobsBadge');
    try {
        const res = await fetch('/api/v1/jobs');
        if (!res.ok) return;
        const data = await res.json();
        const jobs = data.jobs || [];

        if (badge) badge.textContent = jobs.length;

        if (!tbody) return;
        if (jobs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="empty-cell">No background async jobs recorded.</td></tr>';
            return;
        }

        tbody.innerHTML = jobs.map(job => {
            const st = (job.status || 'QUEUED').toUpperCase();
            const badgeClass = st === 'COMPLETED' ? 'active' : (st === 'RUNNING' ? 'running' : (st === 'QUEUED' ? 'amber' : (st === 'CANCELLED' ? 'dim' : 'failed')));
            const stIcon = st === 'COMPLETED' ? '✓' : (st === 'RUNNING' ? '⚡' : (st === 'QUEUED' ? '⏱' : (st === 'CANCELLED' ? '⊘' : '✕')));
            return `
                <tr>
                    <td><code style="font-size: 11px; color: var(--cyan-glow, #00f0ff);">${escapeHtml(job.job_id || job.id)}</code></td>
                    <td><strong style="color: var(--text-primary); font-size: 12px;">${escapeHtml(job.rule_name || job.workflow_name || job.rule_id)}</strong></td>
                    <td><span class="status-badge ${badgeClass}" style="font-size: 11px;">${stIcon} ${st}</span></td>
                    <td><div style="font-size: 11px; color: var(--text-dim, #888);">${escapeHtml(job.current_step_name || 'Executing')} (${job.current_step_index || 0}/${job.total_steps || 1})</div></td>
                    <td style="font-size: 11px; color: var(--text-dim, #888);">${job.started_at ? job.started_at.split('T')[1].split('.')[0] : 'Pending'}</td>
                    <td style="font-size: 11px; color: var(--text-dim, #888);">${job.completed_at ? job.completed_at.split('T')[1].split('.')[0] : (st === 'RUNNING' ? 'Running...' : '-')}</td>
                    <td>
                        ${st === 'RUNNING' || st === 'QUEUED' ? `<button class="action-btn red-btn" onclick="cancelAsyncJob('${job.job_id || job.id}')" title="Cancel Job">✕ Cancel</button>` : `<span style="font-size: 11px; color: var(--text-dim, #888);">Finished</span>`}
                    </td>
                </tr>
            `;
        }).join('');
    } catch (e) {
        console.error('Failed to load async jobs:', e);
    }
}

async function cancelAsyncJob(jobId) {
    try {
        const res = await fetch(`/api/v1/jobs/${jobId}/cancel`, { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            showToast('Job cancelled.', 'info');
            loadAsyncJobs();
        } else {
            showToast(data.error || 'Failed to cancel job', 'error');
        }
    } catch (e) {
        showToast(`Cancel error: ${e.message}`, 'error');
    }
}

// ==========================================
// WHATSAPP BUSINESS / META CLOUD API & GREEN-API
// ==========================================

let waPollTimer = null;
let waActiveChatPartner = null;
let waAllMessagesCache = [];
let waChatSearchTerm = '';
let waCurrentAudio = null;
let waCurrentAudioMsgId = null;
let waVoiceProgressInterval = null;

const WA_AVATAR_PALETTE = ['#00a884', '#53bdeb', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981', '#06b6d4', '#6366f1'];

function getWaAvatarColor(str) {
    let hash = 0;
    for (let i = 0; i < (str || '').length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
    return WA_AVATAR_PALETTE[Math.abs(hash) % WA_AVATAR_PALETTE.length];
}

function formatAudioSeconds(sec) {
    if (!sec || isNaN(sec)) return '0:00';
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${s < 10 ? '0' : ''}${s}`;
}

function setWhatsAppViewMode(mode) {
    const btnWeb = document.getElementById('btnViewWaWeb');
    const btnClassic = document.getElementById('btnViewWaClassic');
    const webContainer = document.getElementById('waWebViewContainer');
    const classicContainer = document.getElementById('waClassicViewContainer');

    if (mode === 'web') {
        if (btnWeb) btnWeb.classList.add('active');
        if (btnClassic) btnClassic.classList.remove('active');
        if (webContainer) webContainer.style.display = 'flex';
        if (classicContainer) classicContainer.style.display = 'none';
        renderWhatsAppWebUI(waAllMessagesCache);
    } else {
        if (btnWeb) btnWeb.classList.remove('active');
        if (btnClassic) btnClassic.classList.add('active');
        if (webContainer) webContainer.style.display = 'none';
        if (classicContainer) classicContainer.style.display = 'flex';
    }
}

function startWhatsAppAutoPoll(intervalMs = 20000) {
    stopWhatsAppAutoPoll();
    waPollTimer = setInterval(async () => {
        const activeTab = document.getElementById('tab-whatsapp');
        if (!activeTab || !activeTab.classList.contains('active')) {
            stopWhatsAppAutoPoll();
            return;
        }
        if (typeof document !== 'undefined' && document.hidden) {
            return;
        }
        await syncWhatsAppMessagesNow(true);
    }, intervalMs);
}

function stopWhatsAppAutoPoll() {
    if (waPollTimer) {
        clearInterval(waPollTimer);
        waPollTimer = null;
    }
}

async function syncWhatsAppMessagesNow(silent = false) {
    const syncBtn = document.getElementById('btnSyncWhatsApp');
    const syncBtnWeb = document.getElementById('btnSyncWhatsAppWeb');
    if (!silent) {
        if (syncBtn) {
            syncBtn.disabled = true;
            syncBtn.innerHTML = '🔄 Syncing...';
        }
        if (syncBtnWeb) {
            syncBtnWeb.disabled = true;
            syncBtnWeb.innerHTML = '⌛';
        }
    }

    try {
        const res = await fetch('/api/v1/whatsapp/poll?sync_history=true&batch=15', { method: 'POST' });
        const data = res.ok ? await res.json() : null;

        await loadWhatsAppMessagesOnly();

        if (!silent) {
            const count = data ? (data.saved_count || data.processed || 0) : 0;
            if (syncBtn) syncBtn.innerHTML = count > 0 ? `✓ ${count} new` : '✓ Up to date';
            if (syncBtnWeb) syncBtnWeb.innerHTML = '✓';
            if (count > 0 && typeof showToast === 'function') {
                showToast(`WhatsApp sync complete: ${count} new message(s) retrieved`, 'success');
            }
            setTimeout(() => {
                if (syncBtn) {
                    syncBtn.disabled = false;
                    syncBtn.innerHTML = '🔄 Sync Now';
                }
                if (syncBtnWeb) {
                    syncBtnWeb.disabled = false;
                    syncBtnWeb.innerHTML = '🔄';
                }
            }, 2000);
        }
    } catch (err) {
        console.error('WhatsApp sync failed:', err);
        if (!silent) {
            if (syncBtn) {
                syncBtn.disabled = false;
                syncBtn.innerHTML = '⚠️ Sync Failed';
                setTimeout(() => {
                    if (syncBtn) syncBtn.innerHTML = '🔄 Sync Now';
                }, 2500);
            }
            if (syncBtnWeb) {
                syncBtnWeb.disabled = false;
                syncBtnWeb.innerHTML = '🔄';
            }
        }
    }
}

function groupWhatsAppConversations(messages) {
    const map = {};
    (messages || []).forEach(m => {
        const isInbound = m.direction === 'inbound';
        const rawPartner = isInbound ? m.sender : m.recipient;
        const partner = (rawPartner || '').replace(/@c\.us|@g\.us/g, '').trim() || 'Unknown';

        if (!map[partner]) {
            map[partner] = {
                phone: partner,
                name: (isInbound ? m.sender_name : '') || partner,
                lastMessage: m.body || (m.is_audio ? '🎙️ Voice note' : '(no text)'),
                timestamp: m.created_at || '',
                is_audio: Boolean(m.is_audio),
                messages: []
            };
        }
        map[partner].messages.push(m);
        if (m.sender_name && (!map[partner].name || map[partner].name === partner)) {
            map[partner].name = m.sender_name;
        }
    });

    const list = Object.values(map);
    list.sort((a, b) => {
        const timeA = a.messages[0]?.created_at || '';
        const timeB = b.messages[0]?.created_at || '';
        return timeB.localeCompare(timeA);
    });
    return list;
}

function handleWhatsAppChatSearch(val) {
    waChatSearchTerm = (val || '').toLowerCase().trim();
    renderWhatsAppWebUI(waAllMessagesCache, false);
}

function selectWhatsAppChat(partner) {
    waActiveChatPartner = partner;
    renderWhatsAppWebUI(waAllMessagesCache, true);
}

function promptNewConversation() {
    const phone = prompt('Enter recipient phone number to message (e.g. +923209350858):');
    if (!phone) return;
    const cleanPhone = phone.replace(/[^0-9+]/g, '');
    if (!cleanPhone) {
        showToast('Invalid phone number format', 'error');
        return;
    }
    waActiveChatPartner = cleanPhone;
    renderWhatsAppWebUI(waAllMessagesCache, true);
    const replyInput = document.getElementById('waReplyInput');
    if (replyInput) replyInput.focus();
}

function resetVoicePlayback(id) {
    if (waVoiceProgressInterval) {
        clearInterval(waVoiceProgressInterval);
        waVoiceProgressInterval = null;
    }
    if (waCurrentAudio) {
        try { waCurrentAudio.pause(); } catch(e) {}
        waCurrentAudio = null;
    }
    if (typeof window !== 'undefined' && window.speechSynthesis) {
        try { window.speechSynthesis.cancel(); } catch(e) {}
    }
    if (id) {
        const btn = document.getElementById(`waPlayBtn_${id}`);
        if (btn) btn.innerHTML = '▶';
        const prog = document.getElementById(`waAudioProg_${id}`);
        if (prog) prog.style.width = '0%';
    }
    waCurrentAudioMsgId = null;
}

function fallbackSpeechPlayback(id, textBody) {
    const btn = document.getElementById(`waPlayBtn_${id}`);
    const prog = document.getElementById(`waAudioProg_${id}`);
    const timeEl = document.getElementById(`waAudioTime_${id}`);
    if (btn) btn.innerHTML = '❚❚';

    if (typeof window === 'undefined' || !window.speechSynthesis) {
        let p = 0;
        waVoiceProgressInterval = setInterval(() => {
            p += 10;
            if (prog) prog.style.width = `${Math.min(p, 100)}%`;
            if (p >= 100) resetVoicePlayback(id);
        }, 120);
        return;
    }

    window.speechSynthesis.cancel();
    const cleanText = (textBody || 'Voice note audio playback demo.').replace(/\[.*?\]/g, '').trim() || 'WhatsApp voice message.';
    const utter = new SpeechSynthesisUtterance(cleanText);
    utter.rate = 1.0;
    utter.pitch = 1.0;

    const start = Date.now();
    const estDuration = Math.max(3000, cleanText.length * 70);

    waVoiceProgressInterval = setInterval(() => {
        const elapsed = Date.now() - start;
        const pct = Math.min(100, (elapsed / estDuration) * 100);
        if (prog) prog.style.width = `${pct}%`;
        if (timeEl) timeEl.textContent = formatAudioSeconds(elapsed / 1000);
        if (pct >= 100) {
            clearInterval(waVoiceProgressInterval);
            waVoiceProgressInterval = null;
        }
    }, 60);

    utter.onend = () => resetVoicePlayback(id);
    utter.onerror = () => resetVoicePlayback(id);
    window.speechSynthesis.speak(utter);
}

function togglePlayVoiceMessage(id, mediaUrl, textBody) {
    if (waCurrentAudioMsgId === id) {
        resetVoicePlayback(id);
        return;
    }
    if (waCurrentAudioMsgId) {
        resetVoicePlayback(waCurrentAudioMsgId);
    }

    waCurrentAudioMsgId = id;
    const btn = document.getElementById(`waPlayBtn_${id}`);
    if (btn) btn.innerHTML = '❚❚';

    if (mediaUrl && (mediaUrl.startsWith('http://') || mediaUrl.startsWith('https://'))) {
        const proxyUrl = `/api/v1/whatsapp/media/proxy?url=${encodeURIComponent(mediaUrl)}`;
        const audio = new Audio(proxyUrl);
        waCurrentAudio = audio;

        audio.ontimeupdate = () => {
            const prog = document.getElementById(`waAudioProg_${id}`);
            const timeEl = document.getElementById(`waAudioTime_${id}`);
            if (audio.duration && !isNaN(audio.duration)) {
                const pct = (audio.currentTime / audio.duration) * 100;
                if (prog) prog.style.width = `${pct}%`;
                if (timeEl) timeEl.textContent = `${formatAudioSeconds(audio.currentTime)} / ${formatAudioSeconds(audio.duration)}`;
            }
        };
        audio.onended = () => resetVoicePlayback(id);
        audio.onerror = () => fallbackSpeechPlayback(id, textBody);
        audio.play().catch(e => {
            console.warn('Audio element play failed, falling back to speech synthesizer:', e);
            fallbackSpeechPlayback(id, textBody);
        });
    } else {
        fallbackSpeechPlayback(id, textBody);
    }
}

async function deleteWhatsAppMsg(msgId) {
    if (!confirm('Are you sure you want to delete this message from conversation history?')) return;
    try {
        const res = await fetch(`/api/v1/whatsapp/messages/${encodeURIComponent(msgId)}`, {
            method: 'DELETE'
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast('Message deleted successfully', 'success');
            waAllMessagesCache = waAllMessagesCache.filter(m => m.id !== msgId && m.whatsapp_message_id !== msgId);
            renderWhatsAppWebUI(waAllMessagesCache, false);
            loadWhatsAppMessagesOnly();
        } else {
            showToast(data.error || 'Failed to delete message', 'error');
        }
    } catch (err) {
        showToast(`Error deleting message: ${err.message}`, 'error');
    }
}

async function clearCurrentConversation() {
    if (!waActiveChatPartner) {
        showToast('No active conversation selected to clear', 'info');
        return;
    }
    if (!confirm(`Are you sure you want to clear all messages for ${waActiveChatPartner}?`)) return;
    try {
        const res = await fetch(`/api/v1/whatsapp/conversations/${encodeURIComponent(waActiveChatPartner)}`, {
            method: 'DELETE'
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast(`Conversation cleared (${data.deleted_count || 0} messages removed)`, 'success');
            waAllMessagesCache = waAllMessagesCache.filter(m => {
                const cleanSender = (m.sender || '').replace(/@c\.us|@g\.us/g, '').trim();
                const cleanRecipient = (m.recipient || '').replace(/@c\.us|@g\.us/g, '').trim();
                return cleanSender !== waActiveChatPartner && cleanRecipient !== waActiveChatPartner;
            });
            waActiveChatPartner = null;
            renderWhatsAppWebUI(waAllMessagesCache, true);
            loadWhatsAppMessagesOnly();
        } else {
            showToast(data.error || 'Failed to clear conversation', 'error');
        }
    } catch (err) {
        showToast(`Error clearing conversation: ${err.message}`, 'error');
    }
}

function handleWaReplyKeydown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendWhatsAppReply();
    }
}

async function sendWhatsAppReply() {
    const input = document.getElementById('waReplyInput');
    if (!input) return;
    const message = input.value.trim();
    if (!message) return;

    let recipient = waActiveChatPartner;
    if (!recipient) {
        recipient = prompt('Enter recipient phone number (e.g. +923209350858):');
        if (!recipient) return;
        waActiveChatPartner = recipient.replace(/[^0-9+]/g, '');
        recipient = waActiveChatPartner;
    }

    input.value = '';

    const isVoice = message.startsWith('[voiceMessage]') || message.startsWith('[audioMessage]');
    const optimisticId = `opt_${Date.now()}`;
    const optimisticMsg = {
        id: optimisticId,
        whatsapp_message_id: 'pending...',
        direction: 'outbound',
        sender: 'You',
        recipient: recipient,
        body: message,
        status: 'sending',
        is_audio: isVoice,
        created_at: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    waAllMessagesCache.push(optimisticMsg);
    renderWhatsAppWebUI(waAllMessagesCache, true);

    const sendBtn = document.getElementById('waReplySendBtn');
    if (sendBtn) sendBtn.disabled = true;

    try {
        const res = await fetch('/api/whatsapp/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                to: recipient,
                message: message
            })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            optimisticMsg.status = 'sent';
            optimisticMsg.whatsapp_message_id = data.whatsapp_message_id || 'sent';
            showToast(`Delivered to ${recipient}`, 'success');
        } else {
            optimisticMsg.status = 'failed';
            optimisticMsg.error_message = data.error || 'Failed';
            showToast(data.error || 'Failed to dispatch message', 'error');
        }
    } catch (err) {
        optimisticMsg.status = 'failed';
        showToast(`Network error: ${err.message}`, 'error');
    } finally {
        if (sendBtn) sendBtn.disabled = false;
        renderWhatsAppWebUI(waAllMessagesCache, true);
        syncWhatsAppMessagesNow(true).catch(e => console.warn(e));
    }
}

function toggleEmojiTray() {
    const tray = document.getElementById('waEmojiTray');
    if (tray) tray.style.display = tray.style.display === 'none' || !tray.style.display ? 'flex' : 'none';
}

function insertEmojiIntoReply(emoji) {
    const input = document.getElementById('waReplyInput');
    if (input) {
        input.value = (input.value || '') + emoji;
        input.focus();
    }
    toggleEmojiTray();
}

function toggleTemplatesTray() {
    const tray = document.getElementById('waTemplatesTray');
    if (tray) tray.style.display = tray.style.display === 'none' || !tray.style.display ? 'flex' : 'none';
}

function insertTemplateReply(text) {
    const input = document.getElementById('waReplyInput');
    if (input) {
        input.value = text;
        input.focus();
    }
    toggleTemplatesTray();
}

function promptSendVoiceNote() {
    if (!waActiveChatPartner) {
        showToast('Please select a conversation from the sidebar first', 'info');
        return;
    }
    const text = prompt(`Enter speech text for outbound Voice Note to ${waActiveChatPartner}:`, 'Incident update: All automated workflow checks completed successfully.');
    if (!text) return;
    const input = document.getElementById('waReplyInput');
    if (input) {
        input.value = `[voiceMessage] ${text}`;
        sendWhatsAppReply();
    }
}

function simulateInboundVoiceNote() {
    const partner = waActiveChatPartner || '923209350858';
    const demoId = `wam_demo_${Date.now()}`;
    const mockVoice = {
        id: demoId,
        whatsapp_message_id: `wamid.voice_${demoId}`,
        direction: 'inbound',
        sender: partner,
        recipient: 'system',
        sender_name: 'Verified Customer',
        message_type: 'voiceMessage',
        is_audio: true,
        body: '[voiceMessage] Hello, this is an automated voice playback demo on your WhatsApp Web console. Click play to listen.',
        status: 'received',
        created_at: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };
    waAllMessagesCache.push(mockVoice);
    waActiveChatPartner = partner;
    renderWhatsAppWebUI(waAllMessagesCache, true);
    showToast('Inbound voice note simulated. Click ▶ to listen to audio playback!', 'info');
}

function renderWhatsAppWebUI(messages, shouldScrollToBottom = false) {
    const convList = document.getElementById('waConversationList');
    const msgStream = document.getElementById('waMessagesStream');
    if (!convList || !msgStream) return;

    const conversations = groupWhatsAppConversations(messages);

    // Apply search filter if present
    const filteredConv = waChatSearchTerm
        ? conversations.filter(c => c.name.toLowerCase().includes(waChatSearchTerm) || c.phone.toLowerCase().includes(waChatSearchTerm) || c.lastMessage.toLowerCase().includes(waChatSearchTerm))
        : conversations;

    // Default active chat partner
    if (!waActiveChatPartner && filteredConv.length > 0) {
        waActiveChatPartner = filteredConv[0].phone;
    }

    // Render Conversation List
    if (filteredConv.length === 0) {
        convList.innerHTML = `
            <div style="padding: 40px 20px; text-align: center; color: #8696a0; font-size: 13px;">
                <div style="font-size: 2.2rem; margin-bottom: 8px;">💬</div>
                <div style="font-weight: 600; color: #e9edef; margin-bottom: 4px;">No conversations found</div>
                <p style="font-size: 11.5px; line-height: 1.4;">Click ➕ to start a new chat or sync to retrieve incoming messages.</p>
                <button type="button" class="hud-btn primary small" onclick="promptNewConversation()" style="margin-top: 10px;">➕ New Chat</button>
            </div>
        `;
    } else {
        convList.innerHTML = filteredConv.map(c => {
            const isActive = c.phone === waActiveChatPartner;
            const avatarColor = getWaAvatarColor(c.phone);
            const initials = (c.name || c.phone || '?').substring(0, 2).toUpperCase();
            const previewIcon = c.is_audio ? '🎙️ ' : '';

            return `
                <div class="wa-chat-item ${isActive ? 'active' : ''}" onclick="selectWhatsAppChat('${escapeHtml(c.phone)}')">
                    <div class="wa-avatar" style="background-color: ${avatarColor};">
                        ${escapeHtml(initials)}
                    </div>
                    <div class="wa-chat-meta">
                        <div class="wa-chat-top">
                            <span class="wa-chat-name" title="${escapeHtml(c.name)}">${escapeHtml(c.name)}</span>
                            <span class="wa-chat-time">${escapeHtml(c.timestamp.substring(11, 16) || c.timestamp)}</span>
                        </div>
                        <div class="wa-chat-bottom">
                            <span class="wa-chat-preview" title="${escapeHtml(c.lastMessage)}">${previewIcon}${escapeHtml(c.lastMessage)}</span>
                            <span class="wa-unread-badge" style="${c.messages.length > 0 ? '' : 'display:none;'}">${c.messages.length}</span>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    // Update active chat header details
    const activeHeaderName = document.getElementById('waActiveContactName');
    const activeHeaderPhone = document.getElementById('waActiveContactPhone');
    const activeHeaderAvatar = document.getElementById('waActiveAvatar');
    const activeChatActions = document.getElementById('waActiveChatActions');

    if (waActiveChatPartner) {
        const activeConv = conversations.find(c => c.phone === waActiveChatPartner);
        const contactName = activeConv ? activeConv.name : waActiveChatPartner;
        if (activeHeaderName) activeHeaderName.textContent = contactName;
        if (activeHeaderPhone) activeHeaderPhone.textContent = `+${waActiveChatPartner.replace(/^\+/, '')} · Online`;
        if (activeHeaderAvatar) {
            activeHeaderAvatar.style.backgroundColor = getWaAvatarColor(waActiveChatPartner);
            activeHeaderAvatar.textContent = (contactName || '?').substring(0, 2).toUpperCase();
        }
        if (activeChatActions) activeChatActions.style.display = 'flex';
    } else {
        if (activeHeaderName) activeHeaderName.textContent = 'Select a Conversation';
        if (activeHeaderPhone) activeHeaderPhone.textContent = 'Choose a chat from the sidebar or click ➕';
        if (activeHeaderAvatar) {
            activeHeaderAvatar.style.backgroundColor = '#53bdeb';
            activeHeaderAvatar.textContent = '👤';
        }
        if (activeChatActions) activeChatActions.style.display = 'none';
    }

    // Render Active Conversation Messages Stream
    if (!waActiveChatPartner) {
        msgStream.innerHTML = `
            <div style="margin: auto; text-align: center; color: #8696a0; max-width: 360px;">
                <div style="font-size: 3rem; margin-bottom: 12px; opacity: 0.85;">💬</div>
                <div style="font-size: 1.2rem; font-weight: 600; color: #e9edef; margin-bottom: 6px;">WhatsApp Web Console</div>
                <p style="font-size: 12.5px; line-height: 1.5;">
                    Select an active contact on the sidebar to listen to voice notes, send instant replies, or delete messages.
                </p>
                <button type="button" class="hud-btn primary small" onclick="promptNewConversation()" style="margin-top: 10px;">➕ Start New Chat</button>
            </div>
        `;
        return;
    }

    const partnerMsgs = (messages || []).filter(m => {
        const cleanSender = (m.sender || '').replace(/@c\.us|@g\.us/g, '').trim();
        const cleanRecipient = (m.recipient || '').replace(/@c\.us|@g\.us/g, '').trim();
        return cleanSender === waActiveChatPartner || cleanRecipient === waActiveChatPartner;
    });

    // Sort chronologically (oldest to newest for chat stream)
    partnerMsgs.sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));

    if (partnerMsgs.length === 0) {
        msgStream.innerHTML = `
            <div class="wa-date-divider">New Conversation</div>
            <div style="margin: auto; text-align: center; color: #8696a0;">
                <div style="font-size: 2.2rem; margin-bottom: 8px;">👋</div>
                <div style="color: #e9edef; font-weight: 600;">No messages yet with +${escapeHtml(waActiveChatPartner)}</div>
                <p style="font-size: 12px; margin-top: 4px;">Type a message in the box below to start chatting!</p>
            </div>
        `;
    } else {
        msgStream.innerHTML = `
            <div class="wa-date-divider">Chat History</div>
            ${partnerMsgs.map(m => {
                const isInbound = m.direction === 'inbound';
                const timeStr = (m.created_at || '').substring(11, 16) || m.created_at || '';
                const isOutbound = !isInbound;
                const isSending = m.status === 'sending';
                const isSent = m.status === 'sent' || m.status === 'received';
                const ticks = isSending ? '🕒' : (isSent ? '✓✓' : '✓');
                const isVoice = Boolean(m.is_audio);
                const safeMediaUrl = m.media_url || '';
                const safeBody = (m.body || '').replace(/\[.*?\]/g, '').trim();

                let bodyHtml = '';
                if (isVoice) {
                    bodyHtml = `
                        <div class="wa-voice-bubble">
                            <button type="button" class="wa-play-btn" id="waPlayBtn_${m.id}" onclick="togglePlayVoiceMessage('${m.id}', '${escapeHtml(safeMediaUrl)}', '${escapeHtml(safeBody)}')">
                                ▶
                            </button>
                            <div class="wa-voice-track">
                                <div class="wa-prog-bar-bg" onclick="togglePlayVoiceMessage('${m.id}', '${escapeHtml(safeMediaUrl)}', '${escapeHtml(safeBody)}')">
                                    <div class="wa-prog-bar-fill" id="waAudioProg_${m.id}"></div>
                                </div>
                                <div class="wa-voice-meta">
                                    <span id="waAudioTime_${m.id}">0:00</span>
                                    <span>🎙️ Voice Note</span>
                                </div>
                            </div>
                        </div>
                    `;
                } else {
                    bodyHtml = `<div>${escapeHtml(m.body || '(no text)')}</div>`;
                }

                return `
                    <div class="wa-bubble-wrap ${isInbound ? 'inbound' : 'outbound'}">
                        <div class="wa-bubble ${isInbound ? 'inbound' : 'outbound'}">
                            ${isInbound && m.sender_name ? `<div class="wa-bubble-sender">${escapeHtml(m.sender_name)}</div>` : ''}
                            ${bodyHtml}
                            <div class="wa-bubble-footer">
                                ${m.is_ai_response ? `<span class="wa-ai-badge" title="AI Auto-Reply [Intent: ${escapeHtml(m.ai_intent || 'auto')}]">🤖 AI Auto-Reply</span>` : ''}
                                <span>${escapeHtml(timeStr)}</span>
                                ${isOutbound ? `<span class="wa-ticks">${ticks}</span>` : ''}
                                <button type="button" class="wa-msg-del-btn" onclick="deleteWhatsAppMsg('${m.id}')" title="Delete message">🗑️</button>
                            </div>
                        </div>
                    </div>
                `;
            }).join('')}
        `;
    }

    if (shouldScrollToBottom) {
        setTimeout(() => {
            msgStream.scrollTop = msgStream.scrollHeight;
        }, 50);
    }
}

async function loadWhatsAppMessagesOnly(isConfigured) {
    try {
        if (typeof isConfigured === 'undefined') {
            const badge = document.getElementById('whatsappModeBadge');
            isConfigured = badge ? !badge.textContent.includes('Simulation') : true;
        }

        const msgRes = await fetch('/api/v1/whatsapp/messages?limit=150');
        if (!msgRes.ok) return [];
        const msgData = await msgRes.json();
        const messages = msgData.messages || [];
        const countBadge = document.getElementById('waMessageCountBadge');
        const tbody = document.getElementById('waMessagesTableBody');

        waAllMessagesCache = messages;

        if (countBadge) countBadge.textContent = `${messages.length} messages`;
        updateNavBadge('tabWhatsAppCount', messages.length);

        // Update WhatsApp Web Replica UI
        renderWhatsAppWebUI(messages, false);

        // Update Classic Audit Table UI
        if (tbody) {
            if (messages.length === 0) {
                if (isConfigured) {
                    tbody.innerHTML = `
                        <tr>
                            <td colspan="6" class="text-center" style="padding: 56px 20px; text-align: center;">
                                <div style="font-size: 2.8rem; margin-bottom: 12px;">💬</div>
                                <div style="font-size: 1.15rem; font-weight: 700; color: #f8fafc; margin-bottom: 6px;">No WhatsApp messages yet</div>
                                <p style="font-size: 0.88rem; color: #94a3b8; max-width: 440px; margin: 0 auto;">Messages received through your WhatsApp Business connection will appear here.</p>
                            </td>
                        </tr>
                    `;
                } else {
                    tbody.innerHTML = `
                        <tr>
                            <td colspan="6" class="text-center" style="padding: 56px 20px; text-align: center;">
                                <div style="font-size: 2.8rem; margin-bottom: 12px;">📱</div>
                                <div style="font-size: 1.15rem; font-weight: 700; color: #f8fafc; margin-bottom: 6px;">Connect WhatsApp Business to start receiving messages.</div>
                                <p style="font-size: 0.88rem; color: #94a3b8; max-width: 440px; margin: 0 auto 18px;">Configure your Meta Business Phone Number ID and Access Token in environment variables or test outbound dispatch using the simulation form on the left.</p>
                                <button type="button" class="hud-btn primary small" onclick="openWhatsAppConnectGuide()">Connect WhatsApp</button>
                            </td>
                        </tr>
                    `;
                }
            } else {
                tbody.innerHTML = messages.map(m => {
                    const isInbound = m.direction === 'inbound';
                    const dirBadge = isInbound
                        ? '<span class="status-pill blue">📥 INBOUND</span>'
                        : '<span class="status-pill green">📤 OUTBOUND</span>';

                    const st = (m.status || '').toLowerCase();
                    let statusPillClass = 'paused';
                    let statusIcon = '●';
                    if (st === 'sent' || st === 'received') {
                        statusPillClass = 'active';
                        statusIcon = '✓';
                    } else if (st === 'mock_sent') {
                        statusPillClass = 'simulation';
                        statusIcon = '🧪';
                    } else if (st === 'failed') {
                        statusPillClass = 'failed';
                        statusIcon = '✕';
                    }

                    return `
                        <tr>
                            <td>${dirBadge}</td>
                            <td>
                                <div style="font-weight: 600; font-family: 'JetBrains Mono', monospace; font-size: 12px;">${isInbound ? escapeHtml(m.sender) : escapeHtml(m.recipient)}</div>
                                <div style="font-size: 11px; color: var(--text-dim, #888);">${isInbound ? 'To: ' + escapeHtml(m.recipient) : 'From: ' + escapeHtml(m.sender)}</div>
                            </td>
                            <td>
                                <div style="max-width: 320px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 13px;" title="${escapeHtml(m.body || '')}">
                                    ${escapeHtml(m.body || '(no text body)')}
                                </div>
                                ${m.error_message ? `<div style="font-size: 11px; color: #ef4444;">${escapeHtml(m.error_message)}</div>` : ''}
                            </td>
                            <td><span class="status-pill ${statusPillClass}" style="font-size: 10px; padding: 2px 7px;">${statusIcon} ${escapeHtml((m.status || '').toUpperCase())}</span></td>
                            <td style="font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-dim, #888);">${escapeHtml(m.whatsapp_message_id || '—')}</td>
                            <td style="font-size: 11px; color: var(--text-dim, #888);">${escapeHtml(m.created_at || '—')}</td>
                        </tr>
                    `;
                }).join('');
            }
        }
        return messages;
    } catch (err) {
        console.error('Failed to load WhatsApp messages:', err);
        return [];
    }
}

async function loadWhatsAppDashboard() {
    try {
        // 1. Load config
        let isConfigured = false;
        const confRes = await fetch('/api/v1/whatsapp/config');
        if (confRes.ok) {
            const conf = await confRes.json();
            isConfigured = Boolean(conf.is_configured);
            const activeProvider = conf.active_provider || (isConfigured ? 'meta' : 'simulator');
            const urlInput = document.getElementById('waWebhookUrlInput');
            const greenUrlInput = document.getElementById('waGreenWebhookUrlInput');
            const tokenInput = document.getElementById('waVerifyTokenInput');
            const phoneIdInput = document.getElementById('waPhoneNumberIdInput');
            const idLabel = document.getElementById('waIdentifierLabel');
            const modeBadge = document.getElementById('whatsappModeBadge');
            const providerBadge = document.getElementById('waActiveProviderBadge');
            const connStatus = document.getElementById('waConnectionStatus');
            const banner = document.getElementById('whatsappModeBanner');
            const bannerTitle = document.getElementById('whatsappBannerTitle');
            const bannerDesc = document.getElementById('whatsappBannerDesc');

            if (urlInput) urlInput.value = conf.meta_webhook_url || conf.webhook_url || '/api/v1/webhooks/whatsapp';
            if (greenUrlInput) greenUrlInput.value = conf.green_api_webhook_url || '/api/v1/webhooks/whatsapp/green-api';
            if (tokenInput) tokenInput.value = conf.verify_token;
            updateWhatsAppHeaderAiBadge(conf.ai_auto_reply_enabled);

            if (activeProvider === 'green_api') {
                if (idLabel) idLabel.textContent = 'Green-API Instance ID';
                if (phoneIdInput) phoneIdInput.value = conf.green_api_id_instance || 'Not configured';
                if (providerBadge) {
                    providerBadge.className = 'status-pill green';
                    providerBadge.textContent = 'Green-API Active';
                }
                if (modeBadge) {
                    modeBadge.className = 'status-pill green';
                    modeBadge.textContent = '● Green-API Online';
                }
                if (connStatus) {
                    connStatus.innerHTML = '<span class="status-pill green" style="font-size:0.75rem;">● Connected (Green-API Instance)</span>';
                }
            } else if (activeProvider === 'meta') {
                if (idLabel) idLabel.textContent = 'Meta Business Phone Number ID';
                if (phoneIdInput) phoneIdInput.value = conf.phone_number_id || 'Not configured';
                if (providerBadge) {
                    providerBadge.className = 'status-pill green';
                    providerBadge.textContent = 'Meta Cloud API';
                }
                if (modeBadge) {
                    modeBadge.className = 'status-pill green';
                    modeBadge.textContent = '● Meta Connected';
                }
                if (connStatus) {
                    connStatus.innerHTML = '<span class="status-pill green" style="font-size:0.75rem;">● Connected (Meta Cloud API)</span>';
                }
            } else {
                if (idLabel) idLabel.textContent = 'Configured Identifier (Phone ID / Instance ID)';
                if (phoneIdInput) phoneIdInput.value = 'Not configured (Simulation)';
                if (providerBadge) {
                    providerBadge.className = 'status-pill blue';
                    providerBadge.textContent = 'Simulation Mode';
                }
                if (modeBadge) {
                    modeBadge.className = 'status-pill blue';
                    modeBadge.textContent = '🧪 Simulation';
                }
                if (connStatus) {
                    connStatus.innerHTML = '<span class="status-pill blue" style="font-size:0.75rem;">🧪 Simulation (Local Sandbox)</span>';
                }
            }

            const bannerAction = document.getElementById('whatsappBannerAction');
            if (banner && bannerTitle && bannerDesc) {
                if (activeProvider === 'green_api') {
                    banner.style.background = 'rgba(16, 185, 129, 0.08)';
                    banner.style.border = '1px solid rgba(16, 185, 129, 0.25)';
                    bannerTitle.style.color = '#10b981';
                    bannerTitle.textContent = 'Production Green-API WhatsApp Gateway Active';
                    bannerDesc.textContent = 'Connected via Green-API instance. Inbound webhook notifications and outbound dispatches are live in production.';
                    if (bannerAction) {
                        bannerAction.innerHTML = '<button type="button" class="hud-btn danger small" onclick="disconnectWhatsApp()">Disconnect</button>';
                    }
                } else if (activeProvider === 'meta') {
                    banner.style.background = 'rgba(16, 185, 129, 0.08)';
                    banner.style.border = '1px solid rgba(16, 185, 129, 0.25)';
                    bannerTitle.style.color = '#10b981';
                    bannerTitle.textContent = 'Production WhatsApp Business Cloud API Connected';
                    bannerDesc.textContent = 'Verified webhook ingress and live Meta Cloud API delivery active. Outbound notifications will be delivered to live user devices.';
                    if (bannerAction) {
                        bannerAction.innerHTML = '<button type="button" class="hud-btn danger small" onclick="disconnectWhatsApp()">Disconnect</button>';
                    }
                } else {
                    banner.style.background = 'rgba(0, 240, 255, 0.06)';
                    banner.style.border = '1px solid rgba(0, 240, 255, 0.2)';
                    bannerTitle.style.color = '#00f0ff';
                    bannerTitle.textContent = 'Simulation Mode Active';
                    bannerDesc.textContent = 'Operating in local sandbox mode. Outbound dispatches are simulated and persisted to local logs. Connect Green-API or Meta Cloud API for live messaging.';
                    if (bannerAction) {
                        bannerAction.innerHTML = '<button type="button" class="hud-btn primary small" onclick="openWhatsAppConnectGuide()">Connect WhatsApp</button>';
                    }
                }
            }
        }

        // 2. Load and render messages
        await loadWhatsAppMessagesOnly(isConfigured);

        // 3. Trigger quiet background sync for live updates
        syncWhatsAppMessagesNow(true).catch(e => console.warn('Quiet WhatsApp sync failed:', e));
    } catch (err) {
        console.error('Failed to load WhatsApp dashboard:', err);
    }
}

function toggleWaMsgType(type) {
    const templateFields = document.getElementById('waTemplateFields');
    const bodyGroup = document.getElementById('waMessageBodyGroup');
    const bodyInput = document.getElementById('waMessageBody');
    if (type === 'template') {
        if (templateFields) templateFields.style.display = 'block';
        if (bodyGroup) bodyGroup.style.display = 'none';
        if (bodyInput) bodyInput.required = false;
    } else {
        if (templateFields) templateFields.style.display = 'none';
        if (bodyGroup) bodyGroup.style.display = 'block';
        if (bodyInput) bodyInput.required = true;
    }
}

async function handleSendWhatsAppMessage(e) {
    if (e) e.preventDefault();
    const recipient = document.getElementById('waRecipientPhone').value.trim();
    const msgTypeRadio = document.querySelector('input[name="waMsgType"]:checked');
    const msgType = msgTypeRadio ? msgTypeRadio.value : 'text';
    const message = document.getElementById('waMessageBody').value.trim();
    const templateName = document.getElementById('waTemplateName')?.value.trim();
    const templateLang = document.getElementById('waTemplateLang')?.value.trim() || 'en_US';
    const sendBtn = document.getElementById('waSendBtn');
    const outputDiv = document.getElementById('waSendOutput');
    const outputJson = document.getElementById('waSendOutputJson');

    if (!recipient) return;
    if (msgType === 'text' && !message) return;

    if (sendBtn) {
        sendBtn.disabled = true;
        sendBtn.textContent = 'Transmitting Message...';
    }

    try {
        const payload = {
            to: recipient,
            message: message || ''
        };
        if (msgType === 'template') {
            payload.template_name = templateName || 'hello_world';
            payload.template_language = templateLang;
        }

        const res = await fetch('/api/whatsapp/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();

        if (outputDiv) {
            outputDiv.style.display = 'block';
            const isSimulated = data.mode === 'simulator' || data.status === 'mock_sent';
            const statusBadge = isSimulated
                ? '<span class="status-pill blue" style="font-weight: 700; font-size: 11px;">🧪 SIMULATOR (SANDBOX DISPATCH)</span>'
                : (res.ok && data.success ? '<span class="status-pill green" style="font-weight: 700; font-size: 11px;">✅ DELIVERED (LIVE META CLOUD API)</span>' : '<span class="status-pill red" style="font-weight: 700; font-size: 11px;">❌ DELIVERY FAILED</span>');
            
            outputDiv.innerHTML = `
                <div style="background: rgba(0, 0, 0, 0.35); border: 1px solid var(--border-color); border-radius: 8px; padding: 14px; margin-top: 10px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 6px;">
                        <strong style="color: var(--cyan-glow); font-size: 13px;">Immediate Delivery Status:</strong>
                        ${statusBadge}
                    </div>
                    <div style="font-size: 12px; color: var(--text-secondary); line-height: 1.6;">
                        <div>Recipient Phone: <strong style="color: #fff; font-family: var(--font-mono);">${escapeHtml(data.recipient || recipient)}</strong></div>
                        <div>Message ID: <span style="font-family: var(--font-mono); font-size: 11.5px; color: #38bdf8;">${escapeHtml(data.whatsapp_message_id || 'N/A')}</span></div>
                        <div>Mode: <span style="color: #e2e8f0; font-weight: 600;">${isSimulated ? 'Local Sandbox / Simulator (Trace Logged)' : 'Live Meta Graph API v19.0'}</span></div>
                        <div style="margin-top: 6px; font-weight: 600; color: ${res.ok && data.success ? '#10b981' : '#ef4444'};">${escapeHtml(data.message || data.error || 'Dispatched successfully')}</div>
                    </div>
                </div>
                <details style="margin-top: 8px;">
                    <summary style="font-size: 11px; color: var(--text-dim, #888); cursor: pointer;">View Raw Payload Response</summary>
                    <pre class="curl-snippet" style="max-height: 120px; margin-top: 4px;">${escapeHtml(JSON.stringify(data, null, 2))}</pre>
                </details>
            `;
        }

        if (res.ok && data.success) {
            showToast(`WhatsApp message dispatched to ${recipient}`, 'success');
            document.getElementById('waMessageBody').value = '';
            loadWhatsAppDashboard();
        } else {
            showToast(`Failed to send WhatsApp message: ${data.error || data.message || 'Server error'}`, 'error');
        }
    } catch (err) {
        showToast(`Network error sending WhatsApp: ${err.message}`, 'error');
    } finally {
        if (sendBtn) {
            sendBtn.disabled = false;
            sendBtn.textContent = 'Send WhatsApp Message';
        }
    }
}

function copyWhatsAppWebhookUrl() {
    const input = document.getElementById('waWebhookUrlInput');
    if (!input) return;
    navigator.clipboard.writeText(input.value).then(() => {
        showToast('WhatsApp webhook callback URL copied to clipboard!', 'success');
    }).catch(() => {
        input.select();
        document.execCommand('copy');
        showToast('Webhook URL copied!', 'success');
    });
}

function toggleWhatsAppVerifyTokenVisibility() {
    const input = document.getElementById('waVerifyTokenInput');
    const btn = document.getElementById('waToggleTokenBtn');
    if (!input) return;
    if (input.type === 'password') {
        input.type = 'text';
        if (btn) btn.textContent = 'Hide';
    } else {
        input.type = 'password';
        if (btn) btn.textContent = 'Show';
    }
}

function toggleWaConfigTokenVisibility() {
    const input = document.getElementById('waConfigAccessToken');
    if (!input) return;
    input.type = input.type === 'password' ? 'text' : 'password';
}

function toggleGreenTokenVisibility() {
    const input = document.getElementById('waConfigGreenToken');
    if (!input) return;
    input.type = input.type === 'password' ? 'text' : 'password';
}

function copyGreenApiWebhookUrl() {
    const input = document.getElementById('waGreenWebhookUrlInput');
    if (!input) return;
    const fullUrl = input.value.startsWith('http') ? input.value : `${window.location.origin}${input.value}`;
    navigator.clipboard.writeText(fullUrl).then(() => {
        showToast('Green-API webhook URL copied to clipboard!', 'success');
    }).catch(() => {
        input.select();
        document.execCommand('copy');
        showToast('Green-API webhook URL copied.', 'info');
    });
}

function copyModalGreenWebhookUrl() {
    const input = document.getElementById('waModalGreenWebhookUrl');
    if (!input) return;
    const fullUrl = input.value.startsWith('http') ? input.value : `${window.location.origin}${input.value}`;
    navigator.clipboard.writeText(fullUrl).then(() => {
        showToast('Green-API webhook URL copied to clipboard!', 'success');
    }).catch(() => {
        input.select();
        document.execCommand('copy');
        showToast('Green-API webhook URL copied.', 'info');
    });
}

function selectWaConfigProvider(provider) {
    const hiddenInput = document.getElementById('waSelectedProvider');
    if (hiddenInput) hiddenInput.value = provider;

    const btnGreen = document.getElementById('waTabBtnGreenApi');
    const btnMeta = document.getElementById('waTabBtnMeta');
    const secGreen = document.getElementById('waGreenApiConfigSection');
    const secMeta = document.getElementById('waMetaConfigSection');
    const testBtn = document.getElementById('btnTestWaConnection');

    if (provider === 'green_api') {
        if (btnGreen) { btnGreen.className = 'hud-btn primary small'; }
        if (btnMeta) { btnMeta.className = 'hud-btn outline small'; }
        if (secGreen) secGreen.style.display = 'block';
        if (secMeta) secMeta.style.display = 'none';
        if (testBtn) testBtn.textContent = '⚡ Test Green-API Connection';
    } else {
        if (btnGreen) { btnGreen.className = 'hud-btn outline small'; }
        if (btnMeta) { btnMeta.className = 'hud-btn primary small'; }
        if (secGreen) secGreen.style.display = 'none';
        if (secMeta) secMeta.style.display = 'block';
        if (testBtn) testBtn.textContent = '⚡ Test Meta API Connection';
    }

    const output = document.getElementById('waConnectionTestOutput');
    if (output) output.style.display = 'none';
}

function copyWhatsAppVerifyToken() {
    const input = document.getElementById('waVerifyTokenInput');
    if (!input) return;
    navigator.clipboard.writeText(input.value).then(() => {
        showToast('WhatsApp verify token copied to clipboard safely.', 'success');
    }).catch(() => {
        input.select();
        document.execCommand('copy');
        showToast('Verify token copied.', 'info');
    });
}

async function openWhatsAppConnectGuide() {
    const modal = document.getElementById('whatsappConnectModal');
    if (modal) modal.style.display = 'flex';

    // Populate existing values if available
    try {
        const res = await fetch('/api/v1/whatsapp/config');
        if (res.ok) {
            const data = await res.json();
            const phoneInput = document.getElementById('waConfigPhoneId');
            const wabaInput = document.getElementById('waConfigWabaId');
            const tokenInput = document.getElementById('waConfigVerifyToken');
            const greenIdInput = document.getElementById('waConfigGreenId');
            const greenHostInput = document.getElementById('waConfigGreenHost');
            const modalGreenUrl = document.getElementById('waModalGreenWebhookUrl');

            if (phoneInput && data.phone_number_id && !data.phone_number_id.includes('...')) {
                phoneInput.value = data.phone_number_id;
            }
            if (wabaInput && data.business_account_id && data.business_account_id !== 'Not Configured') {
                wabaInput.value = data.business_account_id;
            }
            if (tokenInput && data.verify_token) {
                tokenInput.value = data.verify_token;
            }
            if (greenIdInput && data.green_api_id_instance && !data.green_api_id_instance.includes('...')) {
                greenIdInput.value = data.green_api_id_instance;
            }
            if (greenHostInput && data.green_api_host) {
                greenHostInput.value = data.green_api_host;
            }
            if (modalGreenUrl && data.green_api_webhook_url) {
                modalGreenUrl.value = data.green_api_webhook_url;
            }

            // Select provider tab according to active or configured provider
            const activeProv = data.active_provider === 'meta' ? 'meta' : 'green_api';
            selectWaConfigProvider(activeProv);
        }
    } catch (e) {
        console.warn('Could not prefill WhatsApp config:', e);
    }
}

function closeWhatsAppConnectModal() {
    const modal = document.getElementById('whatsappConnectModal');
    if (modal) modal.style.display = 'none';
    const output = document.getElementById('waConnectionTestOutput');
    if (output) output.style.display = 'none';
}

async function handleSaveWhatsAppConfig(e) {
    if (e) e.preventDefault();
    const btn = document.getElementById('btnSaveWaConfig');
    const provider = document.getElementById('waSelectedProvider')?.value || 'green_api';
    const phoneId = (document.getElementById('waConfigPhoneId')?.value || '').trim();
    const token = (document.getElementById('waConfigAccessToken')?.value || '').trim();
    const wabaId = (document.getElementById('waConfigWabaId')?.value || '').trim();
    const secret = (document.getElementById('waConfigAppSecret')?.value || '').trim();
    const verifyToken = (document.getElementById('waConfigVerifyToken')?.value || '').trim();

    const greenId = (document.getElementById('waConfigGreenId')?.value || '').trim();
    const greenToken = (document.getElementById('waConfigGreenToken')?.value || '').trim();
    const greenHost = (document.getElementById('waConfigGreenHost')?.value || '').trim();

    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Saving...';
    }

    try {
        const payload = {
            whatsapp_provider: provider,
            green_api_id_instance: greenId,
            green_api_token_instance: greenToken,
            green_api_host: greenHost || 'https://api.greenapi.com',
            phone_number_id: phoneId,
            access_token: token,
            business_account_id: wabaId,
            app_secret: secret,
            verify_token: verifyToken
        };

        const res = await fetch('/api/v1/whatsapp/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok) {
            showToast('WhatsApp gateway credentials saved and active!', 'success');
            loadWhatsAppDashboard();
            closeWhatsAppConnectModal();
        } else {
            showToast(data.error || 'Failed to save WhatsApp config', 'error');
        }
    } catch (err) {
        showToast('Network error saving config: ' + err.message, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Save & Activate';
        }
    }
}

async function handleTestWhatsAppConnection() {
    const btn = document.getElementById('btnTestWaConnection');
    const output = document.getElementById('waConnectionTestOutput');
    const provider = document.getElementById('waSelectedProvider')?.value || 'green_api';

    if (btn) {
        btn.disabled = true;
        btn.textContent = provider === 'green_api' ? 'Testing Green-API...' : 'Testing Meta Graph API...';
    }
    if (output) {
        output.style.display = 'block';
        output.style.background = 'rgba(0, 240, 255, 0.08)';
        output.style.borderColor = 'rgba(0, 240, 255, 0.2)';
        output.style.color = '#00f0ff';
        output.innerHTML = provider === 'green_api'
            ? 'Probing Green-API getStateInstance endpoint...'
            : 'Connecting to Meta Graph API v19.0 endpoint...';
    }

    try {
        const res = await fetch('/api/v1/whatsapp/test-connection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            output.style.background = 'rgba(16, 185, 129, 0.1)';
            output.style.borderColor = 'rgba(16, 185, 129, 0.3)';
            output.style.color = '#10b981';

            if (provider === 'green_api') {
                output.innerHTML = `<strong>✅ Green-API Connected &amp; Authorized!</strong><br>
                    Instance ID: <code>${escapeHtml(data.id_instance || 'Configured')}</code><br>
                    State: <span class="status-pill green">${escapeHtml(data.status || 'authorized')}</span><br>
                    ${escapeHtml(data.message || 'WhatsApp session is active.')}`;
            } else {
                output.innerHTML = `<strong>✅ Meta Connection Established!</strong><br>
                    Verified Account: ${escapeHtml(data.verified_name || 'Meta Verified')}<br>
                    Display Phone: ${escapeHtml(data.display_phone_number || data.phone_number_id)}<br>
                    Quality Rating: <span class="status-pill green">${escapeHtml(data.quality_rating || 'GREEN')}</span>`;
            }
            showToast('WhatsApp connection probe passed!', 'success');
        } else {
            output.style.background = 'rgba(239, 68, 68, 0.1)';
            output.style.borderColor = 'rgba(239, 68, 68, 0.3)';
            output.style.color = '#ef4444';
            output.innerHTML = `<strong>⚠️ Connection Probe Failed:</strong><br>${escapeHtml(data.message || data.error || 'Check credentials')}`;
            showToast('WhatsApp connection probe returned error', 'error');
        }
    } catch (err) {
        if (output) {
            output.style.background = 'rgba(239, 68, 68, 0.1)';
            output.style.borderColor = 'rgba(239, 68, 68, 0.3)';
            output.style.color = '#ef4444';
            output.innerHTML = `<strong>Network Error:</strong> ${escapeHtml(err.message)}`;
        }
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = provider === 'green_api' ? '⚡ Test Green-API Connection' : '⚡ Test Meta API Connection';
        }
    }
}

function disconnectWhatsApp() {
    if (!confirm('Are you sure you want to disconnect WhatsApp Gateway? The system will revert to local sandbox simulation mode.')) {
        return;
    }
    fetch('/api/v1/whatsapp/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            phone_number_id: '',
            access_token: '',
            business_account_id: '',
            app_secret: '',
            green_api_id_instance: '',
            green_api_token_instance: '',
            whatsapp_provider: 'auto'
        })
    }).then(res => res.json()).then(data => {
        showToast('WhatsApp gateway disconnected. Reverted to simulation sandbox.', 'info');
        loadWhatsAppDashboard();
    }).catch(err => {
        showToast('Failed to disconnect: ' + err.message, 'error');
    });
}

// ==========================================
// SYSTEM READINESS PROBE TELEMETRY
// ==========================================

async function checkSystemReadiness(notify = false) {
    const readyDot = document.getElementById('readyDot');
    const readyStatusText = document.getElementById('readyStatusText');
    try {
        const res = await fetch('/api/v1/ready');
        const data = await res.json();
        if (res.ok && data.status === 'ready') {
            if (readyDot) {
                readyDot.className = 'status-dot green';
            }
            if (readyStatusText) {
                readyStatusText.textContent = 'System Operational';
            }
            if (notify) {
                showToast(`Readiness Probe 200 OK — DB: Online, Engine: Online, Storage: Online`, 'success');
            }
        } else {
            if (readyDot) {
                readyDot.className = 'status-dot red';
            }
            if (readyStatusText) {
                readyStatusText.textContent = 'SYSTEM DEGRADED';
            }
            if (notify) {
                showToast(`Readiness Probe Degraded (${res.status}): Subsystems: ${JSON.stringify(data.subsystems)}`, 'error');
            }
        }
    } catch (e) {
        if (readyDot) readyDot.className = 'status-dot red';
        if (readyStatusText) readyStatusText.textContent = 'PROBE OFFLINE';
        if (notify) showToast(`Readiness probe network failed: ${e.message}`, 'error');
    }
}




// ==========================================================================
// ENTERPRISE SIDEBAR & NAVIGATION CONTROLLER
// ==========================================================================

const TAB_TITLES = {
    dashboard: 'Executive Overview',
    rules: 'Workflow Studio',
    leads: 'CRM Leads',
    incidents: 'Incidents',
    webhooks: 'Inbound Webhooks',
    whatsapp: 'WhatsApp Cloud API',
    nlp: 'AI Engine Sandbox',
    blueprints: 'Templates',
    simulator: 'Metrics Simulator',
    logs: 'Forensics & Audits',
    apikeys: 'API Keys',
    apidocs: 'API Docs',
    team: 'Team & RBAC',
    billing: 'Plans & Billing',
    settings: 'Settings'
};

function initEnterpriseSidebar() {
    const isCollapsed = localStorage.getItem('opsflow_sidebar_collapsed') === 'true';
    const sidebar = document.getElementById('enterpriseSidebar');
    if (sidebar && isCollapsed) {
        sidebar.classList.add('collapsed');
        updateSidebarToggleLabel(true);
    }

    // Keyboard shortcut Ctrl+[ or Cmd+[ to toggle sidebar
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === '[') {
            e.preventDefault();
            toggleSidebarCollapse();
        }
    });
}

function toggleSidebarCollapse() {
    const sidebar = document.getElementById('enterpriseSidebar');
    if (!sidebar) return;
    const isCollapsed = sidebar.classList.toggle('collapsed');
    localStorage.setItem('opsflow_sidebar_collapsed', isCollapsed);
    updateSidebarToggleLabel(isCollapsed);
}

function updateSidebarToggleLabel(isCollapsed) {
    const btn = document.getElementById('sidebarToggleBtn');
    if (!btn) return;
    const icon = btn.querySelector('.toggle-icon');
    const label = btn.querySelector('.toggle-label');
    if (icon) icon.textContent = isCollapsed ? '▶' : '◀';
    if (label) label.textContent = isCollapsed ? 'Expand' : 'Collapse Menu';
}

function updateBreadcrumb(tabId) {
    const breadcrumb = document.getElementById('activeBreadcrumbText');
    if (breadcrumb && TAB_TITLES[tabId]) {
        breadcrumb.textContent = TAB_TITLES[tabId];
    }
}

// ==========================================================================
// GLOBAL ENTERPRISE COMMAND PALETTE (CTRL+K / CMD+K)
// ==========================================================================

const COMMAND_PALETTE_ITEMS = [
    // Navigation
    { id: 'nav-dashboard', category: 'Navigation', icon: '📊', title: 'Executive Overview', shortcut: 'G D', action: () => switchTab('dashboard') },
    { id: 'nav-rules', category: 'Navigation', icon: '⚡', title: 'Workflow Studio', shortcut: 'G W', action: () => switchTab('rules') },
    { id: 'nav-leads', category: 'Navigation', icon: '🎯', title: 'CRM Leads', shortcut: 'G L', action: () => switchTab('leads') },
    { id: 'nav-incidents', category: 'Navigation', icon: '🚨', title: 'Incident Response', shortcut: 'G I', action: () => switchTab('incidents') },
    { id: 'nav-webhooks', category: 'Navigation', icon: '🔌', title: 'Inbound Webhooks', shortcut: 'G H', action: () => switchTab('webhooks') },
    { id: 'nav-whatsapp', category: 'Navigation', icon: '💬', title: 'WhatsApp Cloud API', shortcut: 'G C', action: () => switchTab('whatsapp') },
    { id: 'nav-nlp', category: 'Navigation', icon: '🧠', title: 'AI Engine Sandbox', shortcut: 'G A', action: () => switchTab('nlp') },
    { id: 'nav-blueprints', category: 'Navigation', icon: '📦', title: 'Templates & Blueprints', shortcut: 'G T', action: () => switchTab('blueprints') },
    { id: 'nav-simulator', category: 'Navigation', icon: '🧪', title: 'Metrics Simulator', shortcut: 'G M', action: () => switchTab('simulator') },
    { id: 'nav-logs', category: 'Navigation', icon: '📜', title: 'Forensics & Execution Logs', shortcut: 'G F', action: () => switchTab('logs') },
    { id: 'nav-apikeys', category: 'Navigation', icon: '🔑', title: 'API Keys Management', shortcut: 'G K', action: () => switchTab('apikeys') },
    { id: 'nav-apidocs', category: 'Navigation', icon: '📖', title: 'REST API Documentation', shortcut: 'G R', action: () => switchTab('apidocs') },
    { id: 'nav-team', category: 'Navigation', icon: '👥', title: 'Team & RBAC Management', shortcut: 'G U', action: () => switchTab('team') },
    { id: 'nav-billing', category: 'Navigation', icon: '💳', title: 'Plans, Quotas & Billing', shortcut: 'G B', action: () => switchTab('billing') },
    { id: 'nav-settings', category: 'Navigation', icon: '⚙️', title: 'Workspace Settings', shortcut: 'G S', action: () => switchTab('settings') },

    // Quick Actions
    { id: 'act-new-rule', category: 'Quick Actions', icon: '➕', title: 'Create New Workflow Rule', shortcut: 'N W', action: () => { switchTab('rules'); openRuleModal(); } },
    { id: 'act-new-webhook', category: 'Quick Actions', icon: '🔌', title: 'Register Inbound Webhook', shortcut: 'N H', action: () => { switchTab('webhooks'); openWebhookModal(); } },
    { id: 'act-new-apikey', category: 'Quick Actions', icon: '🔑', title: 'Generate Scoped API Key', shortcut: 'N K', action: () => { switchTab('apikeys'); openApiKeyModal(); } },
    { id: 'act-export-csv', category: 'Quick Actions', icon: '📥', title: 'Export Compliance Audit Trail (CSV)', shortcut: 'E C', action: () => { window.location.href = '/api/v1/audit-trail/export?format=csv'; } },
    { id: 'act-export-json', category: 'Quick Actions', icon: '📥', title: 'Export Compliance Audit Trail (JSON)', shortcut: 'E J', action: () => { window.location.href = '/api/v1/audit-trail/export?format=json'; } },
    { id: 'act-readiness', category: 'Quick Actions', icon: '🩺', title: 'Run System Health & Readiness Probe', shortcut: 'S H', action: () => checkSystemReadiness(true) },
    { id: 'act-toggle-engine', category: 'Quick Actions', icon: '⏸', title: 'Toggle Automation Engine State', shortcut: 'T E', action: () => toggleEngineState() },
    { id: 'act-onboarding', category: 'Quick Actions', icon: '🚀', title: 'Launch Customer Onboarding Wizard', shortcut: 'W Z', action: () => openOnboardingWizard() },
    { id: 'act-switch-persona', category: 'Quick Actions', icon: '🎭', title: 'Switch RBAC Persona', shortcut: 'P S', action: () => openPersonaModal() }
];

let selectedCommandIndex = 0;
let filteredCommandItems = [...COMMAND_PALETTE_ITEMS];

function initCommandPalette() {
    document.addEventListener('keydown', (e) => {
        // Ctrl+K or Cmd+K
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            const modal = document.getElementById('commandPaletteModal');
            if (modal && modal.style.display !== 'none') {
                closeCommandPalette();
            } else {
                openCommandPalette();
            }
        }
        // Escape to close
        if (e.key === 'Escape') {
            const modal = document.getElementById('commandPaletteModal');
            if (modal && modal.style.display !== 'none') {
                closeCommandPalette();
            }
        }
    });
}

function openCommandPalette() {
    const modal = document.getElementById('commandPaletteModal');
    const input = document.getElementById('commandPaletteInput');
    if (!modal || !input) return;
    modal.style.display = 'flex';
    input.value = '';
    selectedCommandIndex = 0;
    filterCommandPalette('');
    setTimeout(() => input.focus(), 50);
}

function closeCommandPalette() {
    const modal = document.getElementById('commandPaletteModal');
    if (modal) modal.style.display = 'none';
}

function handleCommandPaletteOverlayClick(event) {
    if (event.target.id === 'commandPaletteModal') {
        closeCommandPalette();
    }
}

function filterCommandPalette(query) {
    const q = (query || '').toLowerCase().trim();
    if (!q) {
        filteredCommandItems = [...COMMAND_PALETTE_ITEMS];
    } else {
        const matchingCommands = COMMAND_PALETTE_ITEMS.filter(item => 
            item.title.toLowerCase().includes(q) || 
            item.category.toLowerCase().includes(q) ||
            (item.shortcut && item.shortcut.toLowerCase().includes(q))
        );

        // Dynamic Entity Search 1: Workflows (by title, status, trigger)
        const matchingWorkflows = (state.rules || []).filter(r => 
            (r.name && r.name.toLowerCase().includes(q)) ||
            (r.id && r.id.toLowerCase().includes(q)) ||
            (r.category && r.category.toLowerCase().includes(q)) ||
            (r.status && r.status.toLowerCase().includes(q)) ||
            (r.trigger && r.trigger.event_name && r.trigger.event_name.toLowerCase().includes(q))
        ).slice(0, 5).map(r => ({
            id: `wf-${r.id}`,
            category: 'Workflows',
            icon: '⚡',
            title: `${r.name || r.id} (${(r.status || 'Active').toUpperCase()})`,
            shortcut: r.trigger ? r.trigger.event_name || 'Event' : 'Workflow',
            action: () => {
                switchTab('rules');
                openRuleDetailsDrawer(r.id);
            }
        }));

        // Dynamic Entity Search 2: CRM Leads (by lead name, status, score)
        const matchingLeads = (state.leads || []).filter(l => 
            (l.name && l.name.toLowerCase().includes(q)) ||
            (l.email && l.email.toLowerCase().includes(q)) ||
            (l.company && l.company.toLowerCase().includes(q)) ||
            (l.status && l.status.toLowerCase().includes(q)) ||
            (String(l.score || '').includes(q))
        ).slice(0, 5).map(l => ({
            id: `lead-${l.id}`,
            category: 'CRM Leads',
            icon: '🎯',
            title: `${l.name || l.email} — ${l.company || 'Lead'} (Score: ${l.score || 0})`,
            shortcut: (l.status || 'new').toUpperCase(),
            action: () => {
                switchTab('leads');
            }
        }));

        // Dynamic Entity Search 3: Forensics & Audit Logs (by execution ID, event)
        const matchingLogs = (state.logs || []).filter(log => 
            (log.id && String(log.id).toLowerCase().includes(q)) ||
            (log.rule_name && log.rule_name.toLowerCase().includes(q)) ||
            (log.event_name && log.event_name.toLowerCase().includes(q)) ||
            (log.status && log.status.toLowerCase().includes(q))
        ).slice(0, 5).map(log => ({
            id: `log-${log.id}`,
            category: 'Forensics & Audits',
            icon: '📜',
            title: `Execution #${log.id}: ${log.rule_name || log.event_name} [${(log.status || 'OK').toUpperCase()}]`,
            shortcut: log.timestamp ? log.timestamp.split(' ')[1] : 'Log',
            action: () => {
                switchTab('logs');
                inspectExecutionDetails(log.id);
            }
        }));

        filteredCommandItems = [
            ...matchingWorkflows,
            ...matchingLeads,
            ...matchingLogs,
            ...matchingCommands
        ];
    }
    selectedCommandIndex = 0;
    renderCommandPaletteResults();
}

function renderCommandPaletteResults() {
    const container = document.getElementById('commandPaletteResults');
    if (!container) return;

    if (filteredCommandItems.length === 0) {
        container.innerHTML = '<div class="palette-empty">No matching commands or destinations found.</div>';
        return;
    }

    const categories = {};
    filteredCommandItems.forEach((item, index) => {
        if (!categories[item.category]) categories[item.category] = [];
        categories[item.category].push({ item, globalIndex: index });
    });

    let html = '';
    for (const [catName, entries] of Object.entries(categories)) {
        html += `<div class="palette-group-title">${catName}</div>`;
        entries.forEach(({ item, globalIndex }) => {
            const isSelected = globalIndex === selectedCommandIndex;
            html += `
                <div class="palette-item ${isSelected ? 'selected' : ''}" 
                     onclick="executeCommandItem(${globalIndex})" 
                     onmouseenter="selectCommandIndex(${globalIndex})"
                     id="palette-item-${globalIndex}">
                    <span class="palette-item-icon">${item.icon}</span>
                    <span class="palette-item-title">${item.title}</span>
                    ${item.shortcut ? `<kbd class="palette-item-kbd">${item.shortcut}</kbd>` : ''}
                </div>
            `;
        });
    }

    container.innerHTML = html;

    const selectedEl = document.getElementById(`palette-item-${selectedCommandIndex}`);
    if (selectedEl) {
        selectedEl.scrollIntoView({ block: 'nearest' });
    }
}

function selectCommandIndex(index) {
    selectedCommandIndex = index;
    const items = document.querySelectorAll('.palette-item');
    items.forEach((el, idx) => {
        if (idx === index) el.classList.add('selected');
        else el.classList.remove('selected');
    });
}

function handleCommandPaletteKeydown(e) {
    if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (filteredCommandItems.length > 0) {
            selectedCommandIndex = (selectedCommandIndex + 1) % filteredCommandItems.length;
            renderCommandPaletteResults();
        }
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (filteredCommandItems.length > 0) {
            selectedCommandIndex = (selectedCommandIndex - 1 + filteredCommandItems.length) % filteredCommandItems.length;
            renderCommandPaletteResults();
        }
    } else if (e.key === 'Enter') {
        e.preventDefault();
        if (filteredCommandItems.length > 0 && filteredCommandItems[selectedCommandIndex]) {
            executeCommandItem(selectedCommandIndex);
        }
    }
}

function executeCommandItem(index) {
    const entry = filteredCommandItems[index];
    if (entry && typeof entry.action === 'function') {
        closeCommandPalette();
        entry.action();
    }
}


// ==========================================================================
// ENTERPRISE USER ACCOUNT DROPDOWN CONTROLLER
// ==========================================================================

function toggleAccountMenu(event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const menu = document.getElementById('accountDropdownMenu');
    if (!menu) return;
    const isShown = menu.style.display === 'block';
    menu.style.display = isShown ? 'none' : 'block';
}

function closeAccountMenu() {
    const menu = document.getElementById('accountDropdownMenu');
    if (menu) menu.style.display = 'none';
}

document.addEventListener('click', (e) => {
    const wrapper = document.getElementById('accountMenuWrapper');
    if (wrapper && !wrapper.contains(e.target)) {
        closeAccountMenu();
    }
    if (!e.target.closest('.action-overflow-wrapper')) {
        document.querySelectorAll('.action-overflow-menu').forEach(m => m.style.display = 'none');
    }
});

// ==========================================================================
// THEME CONTROLLER (DARK / LIGHT MODE PERSISTENCE)
// ==========================================================================

function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    applyTheme(savedTheme);
}

function toggleTheme() {
    const isDark = document.documentElement.classList.contains('dark');
    const newTheme = isDark ? 'light' : 'dark';
    applyTheme(newTheme);
    localStorage.setItem('theme', newTheme);
    showToast(`Switched to ${newTheme === 'dark' ? 'Dark' : 'Light'} theme`, 'info');
}

function applyTheme(theme) {
    const icon = document.getElementById('themeToggleIcon');
    if (theme === 'light') {
        document.documentElement.classList.remove('dark');
        document.documentElement.classList.add('light');
        if (icon) icon.textContent = '☀️';
    } else {
        document.documentElement.classList.remove('light');
        document.documentElement.classList.add('dark');
        if (icon) icon.textContent = '🌙';
    }
}

// ==========================================================================
// PRACTICAL CHECKOUT & PLAN UPGRADE MODAL CONTROLLER
// ==========================================================================

let pendingCheckoutTier = null;

const PLAN_QUOTA_SUMMARIES = {
    free: {
        name: 'Free Community Tier',
        price: '$0 / month',
        summary: '3 Workflow Rules, 1,000 Monthly Events, 1 Team Seat, Community Support.'
    },
    starter: {
        name: 'Starter Plan',
        price: '$29 / month',
        summary: '10 Workflow Rules, 5,000 Monthly Events, 2 Team Seats, 2 API Keys & Webhooks.'
    },
    pro: {
        name: 'Professional Plan',
        price: '$99 / month',
        summary: '50 Workflow Rules, 200,000 Monthly Events, 10 Team Seats, Google Gemini AI Integration.'
    },
    enterprise: {
        name: 'Enterprise Plan',
        price: '$499 / month',
        summary: '250 Workflow Rules, 1,000,000 Monthly Events, 100 Team Seats, Multimodal AI & Dedicated SLA.'
    }
};

const PLAN_PKR_PRICING = {
    free: { month: 'PKR 0 / month', year: 'PKR 0 / year' },
    starter: { month: 'PKR 7,500 / month', year: 'PKR 75,000 / year' },
    pro: { month: 'PKR 25,000 / month', year: 'PKR 250,000 / year' },
    enterprise: { month: 'PKR 125,000 / month', year: 'PKR 1,250,000 / year' }
};

let currentPaymentMethod = 'card'; // 'card' or 'jazzcash'

function switchPaymentMethod(method) {
    currentPaymentMethod = method;
    const cardFields = document.getElementById('checkoutCardFields');
    const jcFields = document.getElementById('checkoutJazzCashFields');
    const tabCard = document.getElementById('tabPayCard');
    const tabJc = document.getElementById('tabPayJazzCash');
    const btn = document.getElementById('btnSubmitCheckout');

    const tier = (pendingCheckoutTier || 'starter').toLowerCase();
    const interval = currentBillingInterval || 'month';
    const pkrInfo = PLAN_PKR_PRICING[tier] || PLAN_PKR_PRICING['starter'];

    if (method === 'jazzcash') {
        if (cardFields) cardFields.style.display = 'none';
        if (jcFields) jcFields.style.display = 'block';
        if (tabCard) {
            tabCard.className = 'hud-btn small outline';
        }
        if (tabJc) {
            tabJc.className = 'hud-btn small primary';
            tabJc.style.borderColor = '#ef4444';
            tabJc.style.background = '#dc2626';
            tabJc.style.color = '#ffffff';
        }
        if (btn) btn.textContent = `Verify JazzCash TID & Activate Plan`;
    } else {
        if (cardFields) cardFields.style.display = 'block';
        if (jcFields) jcFields.style.display = 'none';
        if (tabCard) {
            tabCard.className = 'hud-btn small primary';
        }
        if (tabJc) {
            tabJc.className = 'hud-btn small outline';
            tabJc.style.borderColor = '';
            tabJc.style.background = '';
            tabJc.style.color = '';
        }
        if (btn) btn.textContent = 'Confirm & Activate Plan';
    }
}

function openCheckoutConfirmationModal(tier) {
    pendingCheckoutTier = tier.toLowerCase();
    closeUpgradePlanModal();

    const planInfo = PLAN_QUOTA_SUMMARIES[pendingCheckoutTier] || PLAN_QUOTA_SUMMARIES['starter'];
    const pkrInfo = PLAN_PKR_PRICING[pendingCheckoutTier] || PLAN_PKR_PRICING['starter'];
    const interval = currentBillingInterval || 'month';

    const nameEl = document.getElementById('checkoutSelectedPlanName');
    const priceEl = document.getElementById('checkoutSelectedPrice');
    const pkrEl = document.getElementById('checkoutSelectedPricePkr');
    const noteEl = document.getElementById('checkoutJazzCashAmountNote');
    const quotaEl = document.getElementById('checkoutSelectedQuotaSummary');
    const tidInput = document.getElementById('checkoutJazzCashTid');
    const errBox = document.getElementById('checkoutErrorMessage');
    if (errBox) errBox.style.display = 'none';
    if (tidInput) tidInput.value = '';

    if (nameEl) nameEl.textContent = planInfo.name;
    if (priceEl) priceEl.textContent = planInfo.price;
    if (pkrEl) pkrEl.textContent = pkrInfo[interval] || pkrInfo.month;
    if (noteEl) noteEl.textContent = pkrInfo[interval] || pkrInfo.month;
    if (quotaEl) quotaEl.textContent = planInfo.summary;

    // Fetch dynamic JazzCash merchant receiving details
    fetch('/api/v1/billing/jazzcash/config')
        .then(r => r.json())
        .then(conf => {
            const titleEl = document.getElementById('checkoutJazzCashAccountTitle');
            const numEl = document.getElementById('checkoutJazzCashAccountNumber');
            if (titleEl && conf.account_title) titleEl.textContent = conf.account_title;
            if (numEl && conf.account_number) numEl.textContent = conf.account_number;
        })
        .catch(() => {});

    switchPaymentMethod('card');

    const modal = document.getElementById('checkoutConfirmationModal');
    if (modal) modal.style.display = 'flex';
}

function closeCheckoutConfirmationModal() {
    const modal = document.getElementById('checkoutConfirmationModal');
    if (modal) modal.style.display = 'none';
    pendingCheckoutTier = null;
}

async function handlePracticalCheckoutSubmit(e) {
    if (e) e.preventDefault();
    if (!pendingCheckoutTier) return;

    const btn = document.getElementById('btnSubmitCheckout');
    const errBox = document.getElementById('checkoutErrorMessage');
    if (errBox) errBox.style.display = 'none';

    if (currentPaymentMethod === 'jazzcash') {
        const tid = (document.getElementById('checkoutJazzCashTid')?.value || '').trim();
        const phone = (document.getElementById('checkoutJazzCashPhone')?.value || '').trim();
        const cnic = (document.getElementById('checkoutJazzCashCnic')?.value || '').trim();
        const channelRadio = document.querySelector('input[name="jcChannel"]:checked');
        const channel = channelRadio ? channelRadio.value : 'TID';

        // Check if user submitted Transaction ID (Default & Recommended Pakistani flow)
        if (channel === 'TID' || tid) {
            if (!tid) {
                if (errBox) {
                    errBox.textContent = 'Please enter your 10 to 12 digit JazzCash Transaction ID (TID) / Reference Number.';
                    errBox.style.display = 'block';
                }
                return;
            }

            if (btn) {
                btn.disabled = true;
                btn.textContent = 'Verifying JazzCash TID...';
            }

            try {
                const res = await fetch('/api/billing/change-plan', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        plan_tier: pendingCheckoutTier,
                        billing_interval: currentBillingInterval || 'month',
                        payment_method: 'jazzcash',
                        transaction_id: tid
                    })
                });

                const data = await res.json();
                if (res.ok && data.success) {
                    closeCheckoutConfirmationModal();
                    showToast(data.message || `JazzCash TID #${tid} verified! Workspace upgraded to ${pendingCheckoutTier.toUpperCase()}`, 'success');

                    if (data.organization && state.currentOrg) {
                        state.currentOrg.plan_tier = data.organization.plan_tier;
                        state.currentOrg.max_rules = data.organization.max_rules;
                        state.currentOrg.max_monthly_events = data.organization.max_monthly_events;
                    }
                    loadBillingStatus();
                    loadBillingDashboard();
                    pollTelemetry(true);
                } else {
                    if (errBox) {
                        errBox.textContent = data.message || data.error || 'Failed to verify JazzCash TID.';
                        errBox.style.display = 'block';
                    }
                }
            } catch (err) {
                if (errBox) {
                    errBox.textContent = 'JazzCash TID verification error: ' + err.message;
                    errBox.style.display = 'block';
                }
            } finally {
                if (btn) {
                    btn.disabled = false;
                    switchPaymentMethod('jazzcash');
                }
            }
            return;
        }

        // Direct MWALLET flow
        if (!phone) {
            if (errBox) {
                errBox.textContent = 'Please enter your 11-digit JazzCash mobile number (e.g. 03001234567) or enter your payment TID.';
                errBox.style.display = 'block';
            }
            return;
        }

        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Dispatching MPIN Prompt to Phone...';
        }

        try {
            const res = await fetch('/api/v1/billing/jazzcash/mwallet-pay', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    plan_tier: pendingCheckoutTier,
                    billing_interval: currentBillingInterval || 'month',
                    mobile_number: phone,
                    cnic_last6: cnic
                })
            });
            const data = await res.json();
            if (res.ok && data.success) {
                closeCheckoutConfirmationModal();
                showToast(data.message || `JazzCash payment approved! Workspace upgraded to ${pendingCheckoutTier.toUpperCase()}`, 'success');

                if (data.organization && state.currentOrg) {
                    state.currentOrg.plan_tier = data.organization.plan_tier;
                    state.currentOrg.max_rules = data.organization.max_rules;
                    state.currentOrg.max_monthly_events = data.organization.max_monthly_events;
                }
                loadBillingStatus();
                loadBillingDashboard();
                pollTelemetry(true);
            } else {
                if (errBox) {
                    errBox.textContent = data.message || data.error || 'JazzCash transaction could not be processed.';
                    errBox.style.display = 'block';
                }
            }
        } catch (err) {
            if (errBox) {
                errBox.textContent = 'JazzCash processing error: ' + err.message;
                errBox.style.display = 'block';
            }
        } finally {
            if (btn) {
                btn.disabled = false;
                switchPaymentMethod('jazzcash');
            }
        }
    } else {
        // Stripe Card flow
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Processing Payment...';
        }

        try {
            const res = await fetch('/api/v1/billing/upgrade', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    plan_tier: pendingCheckoutTier,
                    interval: currentBillingInterval || 'month'
                })
            });

            const data = await res.json();
            if (res.ok) {
                closeCheckoutConfirmationModal();
                showToast(`Workspace upgraded to ${pendingCheckoutTier.toUpperCase()} plan successfully!`, 'success');
                
                if (data.organization && state.currentOrg) {
                    state.currentOrg.plan_tier = data.organization.plan_tier;
                    state.currentOrg.max_rules = data.organization.max_rules;
                    state.currentOrg.max_monthly_events = data.organization.max_monthly_events;
                }
                loadBillingStatus();
                loadBillingDashboard();
                pollTelemetry(true);
            } else {
                if (errBox) {
                    errBox.textContent = data.error || 'Failed to upgrade plan. Please try again.';
                    errBox.style.display = 'block';
                }
            }
        } catch (err) {
            if (errBox) {
                errBox.textContent = 'Network error: ' + err.message;
                errBox.style.display = 'block';
            }
        } finally {
            if (btn) {
                btn.disabled = false;
                switchPaymentMethod('card');
            }
        }
    }
}

// ==========================================
// ENTERPRISE MULTI-TENANT SETTINGS & AI AUTO-RESPONDER
// ==========================================

function updateWhatsAppHeaderAiBadge(enabled) {
    const toggle = document.getElementById('waHeaderAiToggle');
    const dot = document.getElementById('waHeaderAiDot');
    const text = document.getElementById('waHeaderAiStatusText');
    if (!toggle || !text) return;

    if (enabled) {
        toggle.classList.remove('disabled');
        text.textContent = 'ON';
        text.style.color = '#34d399';
    } else {
        toggle.classList.add('disabled');
        text.textContent = 'OFF';
        text.style.color = '#94a3b8';
    }
}

async function toggleWhatsAppAiAutoResponder() {
    try {
        const confRes = await fetch('/api/v1/whatsapp/auto-responder');
        if (!confRes.ok) return;
        const conf = await confRes.json();
        const nextState = !conf.enabled;

        const saveRes = await fetch('/api/v1/whatsapp/auto-responder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: nextState })
        });
        if (saveRes.ok) {
            updateWhatsAppHeaderAiBadge(nextState);
            const masterState = document.getElementById('settingsAiMasterState');
            const masterBadge = document.getElementById('settingsAiMasterBadge');
            if (masterState) masterState.textContent = nextState ? 'ON' : 'OFF';
            if (masterBadge) {
                if (nextState) masterBadge.classList.remove('disabled');
                else masterBadge.classList.add('disabled');
            }
            showToast(`AI Auto-Responder ${nextState ? 'Activated' : 'Paused'} for current workspace`, nextState ? 'success' : 'info');
        }
    } catch (err) {
        console.error('Failed to toggle AI Auto-Responder:', err);
    }
}

async function loadTenantSettings() {
    try {
        const org = state.currentOrg;
        const orgId = org ? org.id : 'org-enterprise-default';
        const orgName = org ? org.name : 'Acme Enterprise Global';
        const plan = (org && org.plan_tier) ? org.plan_tier.toUpperCase() : 'ENTERPRISE';

        const idEl = document.getElementById('settingsOrgId');
        const nameEl = document.getElementById('settingsOrgName');
        const planEl = document.getElementById('settingsOrgPlan');
        const webhookEl = document.getElementById('settingsTenantWebhookUrl');
        const selectEl = document.getElementById('settingsWorkspaceSelect');
        const mapSelect = document.getElementById('mapSelectOrgId');

        if (idEl) idEl.textContent = orgId;
        if (nameEl) nameEl.textContent = orgName;
        if (planEl) planEl.textContent = `${plan} (Active)`;
        if (webhookEl) webhookEl.value = `${window.location.origin}/api/v1/webhooks/whatsapp?org_id=${orgId}`;

        if (selectEl && state.organizations && state.organizations.length > 0) {
            selectEl.innerHTML = state.organizations.map(o => `<option value="${escapeHtml(o.id)}" ${o.id === orgId ? 'selected' : ''}>${escapeHtml(o.name)}</option>`).join('');
        }
        if (mapSelect && state.organizations && state.organizations.length > 0) {
            mapSelect.innerHTML = state.organizations.map(o => `<option value="${escapeHtml(o.id)}" ${o.id === orgId ? 'selected' : ''}>${escapeHtml(o.name)}</option>`).join('');
        }
    } catch (err) {
        console.error('Failed to load tenant settings:', err);
    }
}

async function loadAutoResponderSettings() {
    try {
        const res = await fetch('/api/v1/whatsapp/auto-responder');
        if (!res.ok) return;
        const data = await res.json();

        const masterState = document.getElementById('settingsAiMasterState');
        const masterBadge = document.getElementById('settingsAiMasterBadge');
        const modeSelect = document.getElementById('arConfigMode');
        const cooldownInput = document.getElementById('arConfigCooldown');
        const thresholdInput = document.getElementById('arConfigThreshold');
        const leadCaptureCheck = document.getElementById('arConfigLeadCapture');
        const promptArea = document.getElementById('arConfigSystemPrompt');

        if (masterState) masterState.textContent = data.enabled ? 'ON' : 'OFF';
        if (masterBadge) {
            if (data.enabled) masterBadge.classList.remove('disabled');
            else masterBadge.classList.add('disabled');
        }
        if (modeSelect && data.mode) modeSelect.value = data.mode;
        if (cooldownInput && typeof data.cooldown_minutes !== 'undefined') cooldownInput.value = data.cooldown_minutes;
        if (thresholdInput && typeof data.confidence_threshold !== 'undefined') thresholdInput.value = data.confidence_threshold;
        if (leadCaptureCheck) leadCaptureCheck.checked = Boolean(data.auto_lead_capture);
        if (promptArea) promptArea.value = data.system_prompt || '';

        updateWhatsAppHeaderAiBadge(data.enabled);
    } catch (err) {
        console.error('Failed to load Auto-Responder settings:', err);
    }
}

async function toggleSettingsAutoResponder() {
    await toggleWhatsAppAiAutoResponder();
    await loadAutoResponderSettings();
}

async function handleSaveAutoResponderSettings(e) {
    if (e) e.preventDefault();
    const btn = document.getElementById('btnSaveAutoResponder');
    if (btn) btn.disabled = true;

    try {
        const mode = document.getElementById('arConfigMode')?.value || 'smart_concierge';
        const cooldown = parseInt(document.getElementById('arConfigCooldown')?.value, 10) || 5;
        const threshold = parseInt(document.getElementById('arConfigThreshold')?.value, 10) || 60;
        const autoLead = document.getElementById('arConfigLeadCapture')?.checked ?? true;
        const prompt = document.getElementById('arConfigSystemPrompt')?.value || '';

        const res = await fetch('/api/v1/whatsapp/auto-responder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mode: mode,
                cooldown_minutes: cooldown,
                confidence_threshold: threshold,
                auto_lead_capture: autoLead,
                system_prompt: prompt
            })
        });

        const data = await res.json();
        if (res.ok && data.success) {
            showToast('AI Auto-Responder settings saved successfully!', 'success');
        } else {
            showToast(data.error || 'Failed to save settings', 'error');
        }
    } catch (err) {
        showToast(`Save failed: ${err.message}`, 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function runArSandboxSimulation() {
    const name = document.getElementById('arSandboxName')?.value || 'Valued Customer';
    const phone = document.getElementById('arSandboxPhone')?.value || '+923001234567';
    const msg = document.getElementById('arSandboxMessage')?.value || '';
    const status = document.getElementById('arSandboxStatus');
    const outBox = document.getElementById('arSandboxOutput');

    if (!msg.trim()) {
        showToast('Please enter an inquiry message to simulate', 'error');
        return;
    }

    if (status) status.textContent = 'Generating AI draft...';
    try {
        const res = await fetch('/api/v1/whatsapp/auto-responder/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: msg,
                sender_name: name,
                sender_phone: phone
            })
        });
        const data = await res.json();
        if (res.ok && data.preview) {
            const prev = data.preview;
            const intentPill = document.getElementById('arSandboxIntentPill');
            const scorePill = document.getElementById('arSandboxScorePill');
            const routePill = document.getElementById('arSandboxRoutePill');
            const confPill = document.getElementById('arSandboxConfidencePill');
            const replyPre = document.getElementById('arSandboxReplyText');

            if (intentPill) intentPill.textContent = `Intent: ${prev.intent}`;
            if (scorePill) scorePill.textContent = `Lead Score: ${prev.lead_score}/100`;
            if (routePill) routePill.textContent = `Route: ${prev.route_department}`;
            if (confPill) confPill.textContent = `Confidence: ${prev.confidence}%`;
            if (replyPre) replyPre.textContent = prev.reply_body;

            if (outBox) outBox.style.display = 'block';
            if (status) status.textContent = '✓ Response synthesized';
        } else {
            showToast(data.error || 'Simulation failed', 'error');
            if (status) status.textContent = 'Error';
        }
    } catch (err) {
        showToast(`Simulation error: ${err.message}`, 'error');
        if (status) status.textContent = 'Error';
    }
}

async function loadWhatsAppInstanceMappings() {
    const tbody = document.getElementById('settingsInstanceMappingsTbody');
    if (!tbody) return;

    try {
        const res = await fetch('/api/v1/whatsapp/instances');
        if (!res.ok) return;
        const data = await res.json();
        const mappings = data.mappings || {};
        const entries = Object.entries(mappings);

        if (entries.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" class="empty-cell">No instance mappings registered yet. Incoming messages route to default workspace.</td></tr>`;
            return;
        }

        tbody.innerHTML = entries.map(([instId, orgId]) => `
            <tr>
                <td><code>${escapeHtml(instId)}</code></td>
                <td><span class="glass-pill cyan">${escapeHtml(orgId)}</span></td>
                <td><span class="status-pill green" style="font-size:10px;">Active Route</span></td>
                <td>
                    <button type="button" class="hud-btn danger small" onclick="deleteWhatsAppInstanceMapping('${escapeHtml(instId)}')">
                        Unmap
                    </button>
                </td>
            </tr>
        `).join('');
    } catch (err) {
        console.error('Failed to load instance mappings:', err);
    }
}

async function handleMapInstanceForm(e) {
    if (e) e.preventDefault();
    const instId = document.getElementById('mapInputInstanceId')?.value?.trim();
    const targetOrg = document.getElementById('mapSelectOrgId')?.value?.trim();
    const prov = document.getElementById('mapSelectProvider')?.value || 'green_api';

    if (!instId || !targetOrg) {
        showToast('Instance ID and Target Workspace are required', 'error');
        return;
    }

    try {
        const res = await fetch('/api/v1/whatsapp/instances/map', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                instance_id: instId,
                organization_id: targetOrg,
                provider: prov
            })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast(`Mapped Instance '${instId}' to '${targetOrg}'`, 'success');
            const inp = document.getElementById('mapInputInstanceId');
            if (inp) inp.value = '';
            loadWhatsAppInstanceMappings();
        } else {
            showToast(data.error || 'Mapping failed', 'error');
        }
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

async function deleteWhatsAppInstanceMapping(instId) {
    if (!confirm(`Are you sure you want to remove routing for instance '${instId}'?`)) return;
    try {
        const res = await fetch(`/api/v1/whatsapp/instances/map/${encodeURIComponent(instId)}`, {
            method: 'DELETE'
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast(`Instance '${instId}' unmapped successfully`, 'info');
            loadWhatsAppInstanceMappings();
        } else {
            showToast(data.error || 'Failed to unmap', 'error');
        }
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

function copySettingsTenantWebhookUrl() {
    const input = document.getElementById('settingsTenantWebhookUrl');
    if (!input) return;
    navigator.clipboard.writeText(input.value).then(() => {
        showToast('Tenant Webhook URL copied to clipboard!', 'success');
    }).catch(() => {
        input.select();
        document.execCommand('copy');
        showToast('Copied to clipboard!', 'success');
    });
}

async function loadAllSettings() {
    await Promise.allSettled([
        loadTenantSettings(),
        loadAutoResponderSettings(),
        loadWhatsAppInstanceMappings()
    ]);
}



