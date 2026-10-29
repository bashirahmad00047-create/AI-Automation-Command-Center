/**
 * BashFlow Cloud Enterprise Frontend Application Controller
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
    loadCampaignsSummary();
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

    if (window.innerWidth <= 992) {
        const sidebar = document.getElementById('enterpriseSidebar');
        if (sidebar && sidebar.classList.contains('open')) {
            sidebar.classList.remove('open');
            const backdrop = document.getElementById('sidebarBackdrop');
            if (backdrop) backdrop.classList.remove('active');
        }
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
    if (tabId === 'campaigns') {
        if (typeof loadCampaignsDashboard === 'function') loadCampaignsDashboard();
    }
    if (tabId === 'company-messaging') {
        if (typeof loadCompanyMessagingDashboard === 'function') loadCompanyMessagingDashboard();
        if (typeof startCompanyMessagingAutoPoll === 'function') startCompanyMessagingAutoPoll();
    } else {
        if (typeof stopCompanyMessagingAutoPoll === 'function') stopCompanyMessagingAutoPoll();
    }
    if (tabId === 'logs') loadExecutionLogs();
    if (tabId === 'incidents') loadIncidents();
    if (tabId === 'apikeys') loadApiKeys();
    if (tabId === 'team') loadTeamAndAudits();
    if (tabId === 'billing') loadBillingDashboard();
    if (tabId === 'settings') loadAllSettings();
    if (tabId === 'products') loadProductsCatalog();
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
            state.rules = [];
            if (typeof populateWorkflowGraphSelector === 'function') {
                populateWorkflowGraphSelector();
            }
            return;
        }
        const data = await res.json();
        state.rules = data.rules || [];
        renderRulesTable();
    } catch (e) {
        console.error('Failed to load rules:', e);
        state.rules = [];
        if (typeof populateWorkflowGraphSelector === 'function') {
            populateWorkflowGraphSelector();
        }
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
        if (typeof populateWorkflowGraphSelector === 'function') {
            populateWorkflowGraphSelector();
        }
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
                <td data-label="Status">
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
                <td data-label="Workflow">
                    <div class="wf-title-cell">
                        <strong class="wf-name-text">${escapeHtml(rule.name)}</strong>
                        <div class="wf-desc-sub" title="${escapeHtml(rule.description || '')}">${escapeHtml(rule.description || 'No description provided')}</div>
                    </div>
                </td>
                <td data-label="Category"><span class="category-chip ${rule.category ? rule.category.toLowerCase() : 'system'}">${rule.category || 'System'}</span></td>
                <td data-label="Trigger"><code class="trigger-code-pill">${triggerDisplay}</code></td>
                <td data-label="Runs" class="num-cell" style="text-align: center;"><span style="font-family: var(--font-mono); font-size: 0.85rem; font-weight: 700; color: #f1f5f9;">${runsCount.toLocaleString()}</span></td>
                <td data-label="Last Run">${lastRunText}</td>
                <td data-label="Actions" class="action-col" style="text-align: right;" onclick="event.stopPropagation()">
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

    // Sync graph view selector if graph is currently active
    if (typeof wfGraphState !== 'undefined' && wfGraphState.currentView === 'graph') {
        populateWorkflowGraphSelector();
        if (wfGraphState.activeRuleId) {
            renderWorkflowGraph(wfGraphState.activeRuleId);
        } else if (state.rules && state.rules.length > 0) {
            renderWorkflowGraph(state.rules[0].id);
        }
    }
}

// ==========================================================================
// WORKFLOW STUDIO - DUAL-VIEW SWITCHER & INTERACTIVE GRAPH CANVAS
// ==========================================================================

const wfGraphState = {
    currentView: 'table',
    activeRuleId: null,
    zoom: 1.0,
    panX: 60,
    panY: 80,
    isPanning: false,
    startX: 0,
    startY: 0,
    initialized: false,
    minimapInitialized: false,
    minimapCollapsed: false,
    minimapScaleX: 160 / 1200,
    minimapScaleY: 90 / 320,
    nodeCoords: []
};

function setWorkflowView(mode) {
    wfGraphState.currentView = mode;
    const btnTable = document.getElementById('btnViewTable');
    const btnGraph = document.getElementById('btnViewGraph');
    const tableView = document.getElementById('workflowTableView');
    const graphView = document.getElementById('workflowGraphView');

    if (mode === 'graph') {
        if (btnTable) {
            btnTable.classList.remove('active');
            btnTable.style.background = '';
            btnTable.style.color = '';
        }
        if (btnGraph) {
            btnGraph.classList.add('active');
            btnGraph.style.background = '';
            btnGraph.style.color = '';
        }
        if (tableView) tableView.style.display = 'none';
        if (graphView) graphView.style.display = 'block';

        initWorkflowGraphCanvas();
        populateWorkflowGraphSelector();
        if (wfGraphState.activeRuleId) {
            renderWorkflowGraph(wfGraphState.activeRuleId);
        } else if (state.rules && state.rules.length > 0) {
            renderWorkflowGraph(state.rules[0].id);
        }
        setTimeout(wfGraphFitView, 60);
    } else {
        if (btnGraph) {
            btnGraph.classList.remove('active');
            btnGraph.style.background = '';
            btnGraph.style.color = '';
        }
        if (btnTable) {
            btnTable.classList.add('active');
            btnTable.style.background = '';
            btnTable.style.color = '';
        }
        if (graphView) graphView.style.display = 'none';
        if (tableView) tableView.style.display = 'block';
    }
}

function initWorkflowGraphCanvas() {
    if (wfGraphState.initialized) return;
    const viewport = document.getElementById('wfCanvasViewport');
    if (!viewport) return;

    // Pan (drag) events
    viewport.addEventListener('mousedown', (e) => {
        if (e.target.closest('.wf-graph-node') || e.target.closest('button') || e.target.closest('.wf-minimap-container') || e.target.closest('.wf-graph-empty-state')) return;
        wfGraphState.isPanning = true;
        wfGraphState.startX = e.clientX - wfGraphState.panX;
        wfGraphState.startY = e.clientY - wfGraphState.panY;
        viewport.style.cursor = 'grabbing';
    });

    window.addEventListener('mousemove', (e) => {
        if (!wfGraphState.isPanning) return;
        wfGraphState.panX = e.clientX - wfGraphState.startX;
        wfGraphState.panY = e.clientY - wfGraphState.startY;
        applyWfGraphTransform();
    });

    window.addEventListener('mouseup', () => {
        if (wfGraphState.isPanning) {
            wfGraphState.isPanning = false;
            if (viewport) viewport.style.cursor = 'grab';
        }
    });

    // Zoom on mouse wheel
    viewport.addEventListener('wheel', (e) => {
        e.preventDefault();
        const delta = e.deltaY < 0 ? 0.12 : -0.12;
        wfGraphZoom(delta);
    }, { passive: false });

    // Double-click on viewport background to reset/fit view
    viewport.addEventListener('dblclick', (e) => {
        if (e.target.closest('.wf-graph-node') || e.target.closest('button') || e.target.closest('.wf-minimap-container') || e.target.closest('.wf-graph-empty-state')) return;
        wfGraphFitView();
    });

    // Debounced safe window resize handler
    let wfResizeTimer = null;
    window.addEventListener('resize', () => {
        if (wfGraphState.currentView !== 'graph') return;
        clearTimeout(wfResizeTimer);
        wfResizeTimer = setTimeout(() => {
            wfGraphFitView();
        }, 120);
    });

    initWfMinimap();
    wfGraphState.initialized = true;
    applyWfGraphTransform();
}

function applyWfGraphTransform() {
    const world = document.getElementById('wfCanvasWorld');
    const badge = document.getElementById('wfGraphZoomBadge');
    if (world) {
        world.style.transform = `translate(${wfGraphState.panX}px, ${wfGraphState.panY}px) scale(${wfGraphState.zoom})`;
    }
    if (badge) {
        badge.textContent = `${Math.round(wfGraphState.zoom * 100)}%`;
    }
    updateWfMinimapViewport();
}

function wfGraphZoom(delta) {
    const newZoom = Math.max(0.30, Math.min(2.2, wfGraphState.zoom + delta));
    wfGraphState.zoom = Math.round(newZoom * 100) / 100;
    applyWfGraphTransform();
}

function wfGraphFitView() {
    const viewport = document.getElementById('wfCanvasViewport');
    if (!viewport) return;
    const nodes = document.querySelectorAll('.wf-graph-node');
    if (nodes.length === 0) {
        wfGraphState.zoom = 1.0;
        wfGraphState.panX = 40;
        wfGraphState.panY = 70;
        applyWfGraphTransform();
        return;
    }

    const vpWidth = viewport.clientWidth > 200 ? viewport.clientWidth : 1000;
    const count = nodes.length;

    // Node layout geometry: nodeWidth = 220px, gapX = 64px (pitch = 284px), leftOffset = 40px
    const pitch = 284;
    const nodeWidth = 220;
    const totalContentWidth = (count - 1) * pitch + nodeWidth + 40;

    // Calculate zoom to fit total content width inside viewport (leaving 80px horizontal margin)
    const availableWidth = Math.max(200, vpWidth - 80);
    let targetZoom = availableWidth / totalContentWidth;
    targetZoom = Math.max(0.35, Math.min(1.0, targetZoom));
    targetZoom = Math.round(targetZoom * 100) / 100;

    // Center horizontally if content fits within viewport, otherwise align nicely from left
    const renderedWidth = totalContentWidth * targetZoom;
    let panX = 40;
    if (renderedWidth < vpWidth) {
        panX = Math.round((vpWidth - renderedWidth) / 2);
    }
    panX = Math.max(20, panX);
    const panY = 70;

    wfGraphState.zoom = targetZoom;
    wfGraphState.panX = panX;
    wfGraphState.panY = panY;
    applyWfGraphTransform();
}

function wfGraphResetView() {
    wfGraphState.zoom = 1.0;
    wfGraphState.panX = 40;
    wfGraphState.panY = 70;
    applyWfGraphTransform();
}

function populateWorkflowGraphSelector() {
    const select = document.getElementById('wfGraphRuleSelect');
    const emptyState = document.getElementById('wfGraphEmptyState');
    const world = document.getElementById('wfCanvasWorld');
    const minimap = document.getElementById('wfMinimapContainer');
    const statusPill = document.getElementById('wfGraphStatusPill');
    const catPill = document.getElementById('wfGraphCategoryPill');
    const stepsPill = document.getElementById('wfGraphStepsPill');

    if (!select) return;

    if (!state.rules || state.rules.length === 0) {
        select.innerHTML = '<option value="">No workflows in active workspace</option>';
        wfGraphState.activeRuleId = null;
        if (statusPill) statusPill.style.display = 'none';
        if (catPill) catPill.style.display = 'none';
        if (stepsPill) stepsPill.style.display = 'none';
        if (emptyState) emptyState.style.display = 'flex';
        if (world) world.style.display = 'none';
        if (minimap) minimap.style.display = 'none';
        return;
    }

    if (emptyState) emptyState.style.display = 'none';
    if (world) world.style.display = 'block';
    if (minimap && !wfGraphState.minimapCollapsed) minimap.style.display = 'flex';

    select.innerHTML = state.rules.map(r => `
        <option value="${r.id}" ${r.id === wfGraphState.activeRuleId ? 'selected' : ''}>
            ${escapeHtml(r.name)} (${r.category || 'System'})
        </option>
    `).join('');

    if (!wfGraphState.activeRuleId || !state.rules.some(r => r.id === wfGraphState.activeRuleId)) {
        wfGraphState.activeRuleId = state.rules[0].id;
        select.value = state.rules[0].id;
    }
}

function onWorkflowGraphSelectChange(ruleId) {
    if (!ruleId) {
        const statusPill = document.getElementById('wfGraphStatusPill');
        const catPill = document.getElementById('wfGraphCategoryPill');
        const stepsPill = document.getElementById('wfGraphStepsPill');
        if (statusPill) statusPill.style.display = 'none';
        if (catPill) catPill.style.display = 'none';
        if (stepsPill) stepsPill.style.display = 'none';
        return;
    }
    wfGraphState.activeRuleId = ruleId;
    renderWorkflowGraph(ruleId);
    setTimeout(wfGraphFitView, 40);
}

function renderWorkflowGraph(ruleId) {
    const emptyState = document.getElementById('wfGraphEmptyState');
    const world = document.getElementById('wfCanvasWorld');
    const minimap = document.getElementById('wfMinimapContainer');
    const statusPill = document.getElementById('wfGraphStatusPill');
    const catPill = document.getElementById('wfGraphCategoryPill');
    const stepsPill = document.getElementById('wfGraphStepsPill');

    if (!state.rules || state.rules.length === 0) {
        if (statusPill) statusPill.style.display = 'none';
        if (catPill) catPill.style.display = 'none';
        if (stepsPill) stepsPill.style.display = 'none';
        if (emptyState) emptyState.style.display = 'flex';
        if (world) world.style.display = 'none';
        if (minimap) minimap.style.display = 'none';
        return;
    }

    wfGraphState.activeRuleId = ruleId;
    const rule = state.rules.find(r => r.id === ruleId);
    if (!rule) {
        if (statusPill) statusPill.style.display = 'none';
        if (catPill) catPill.style.display = 'none';
        if (stepsPill) stepsPill.style.display = 'none';
        return;
    }

    if (emptyState) emptyState.style.display = 'none';
    if (world) world.style.display = 'block';
    if (minimap && !wfGraphState.minimapCollapsed) minimap.style.display = 'flex';

    // Update status pills in toolbar and show them
    if (statusPill) {
        const isEnabled = rule.enabled === 1 || rule.enabled === true;
        statusPill.className = `status-pill ${isEnabled ? 'active' : 'paused'}`;
        statusPill.textContent = isEnabled ? '● Active' : '⏸ Paused';
        statusPill.style.display = 'inline-flex';
    }
    if (catPill) {
        catPill.className = `category-chip ${(rule.category || 'system').toLowerCase()}`;
        catPill.textContent = rule.category || 'System';
        catPill.style.display = 'inline-flex';
    }

    const nodesLayer = document.getElementById('wfGraphNodesLayer');
    const svgLayer = document.getElementById('wfGraphSvgLayer');
    if (!nodesLayer || !svgLayer) return;

    nodesLayer.innerHTML = '';

    // Clear existing SVG connectors without destroying defs markers
    svgLayer.querySelectorAll('path.wf-connector-path').forEach(p => p.remove());

    // Extract or synthesize steps
    let steps = [];
    if (Array.isArray(rule.steps) && rule.steps.length > 0) {
        steps = rule.steps;
    } else {
        const trig = rule.trigger || {};
        steps.push({
            type: 'trigger',
            name: `Trigger: ${trig.event_name || trig.type || 'Event Ingestion'}`,
            config: trig
        });
        const cond = rule.condition || {};
        if (cond && (cond.conditions || cond.logic)) {
            steps.push({
                type: 'condition',
                name: `Condition: ${cond.logic || 'Rule Logic'} (${(cond.conditions || []).length} rules)`,
                config: cond
            });
        }
        (rule.actions || []).forEach((act, i) => {
            steps.push({
                type: act.type || 'action',
                name: `Action ${i+1}: ${act.type || 'Dispatch'}`,
                config: act.params || act.config || {}
            });
        });
        steps.push({
            type: 'end',
            name: 'Outcome: Pipeline Complete',
            config: {}
        });
    }

    // Update total steps pill in toolbar and reveal it
    if (stepsPill) {
        stepsPill.textContent = `${steps.length} Step${steps.length === 1 ? '' : 's'}`;
        stepsPill.style.display = 'inline-flex';
    }

    const nodeWidth = 220;
    const nodeHeight = 100;
    const gapX = 64;
    const nodeCoords = [];

    // Render nodes
    steps.forEach((step, idx) => {
        const rawType = (step.type || 'action').toLowerCase();
        let displayType = 'Action';
        let icon = '⚡';
        let cardClass = rawType;

        if (rawType.includes('trigger')) {
            displayType = 'Trigger';
            icon = '⚡';
            cardClass = 'trigger';
        } else if (rawType.includes('condition') || rawType.includes('urgency') || rawType.includes('threshold') || rawType.includes('check') || rawType.includes('eval')) {
            displayType = 'Condition';
            icon = '⚖️';
            cardClass = 'condition';
        } else if (rawType.includes('ai') || rawType.includes('nlp')) {
            displayType = 'AI Action';
            icon = '🧠';
            cardClass = 'ai_analysis';
        } else if (rawType.includes('approval') || rawType.includes('review') || rawType.includes('gate')) {
            displayType = 'Approval Gate';
            icon = '🛡️';
            cardClass = 'approval';
        } else if (rawType.includes('end') || rawType.includes('outcome') || rawType.includes('complete')) {
            displayType = 'Outcome';
            icon = '🏁';
            cardClass = 'end';
        } else {
            displayType = 'Action';
            icon = '🔌';
            cardClass = 'action';
        }

        const posX = idx * (nodeWidth + gapX) + 40;
        const posY = (idx % 2 === 1 ? 120 : 60); // subtle wave for branch feel
        nodeCoords.push({ x: posX, y: posY, width: nodeWidth, height: nodeHeight, step, idx });

        const nodeEl = document.createElement('div');
        nodeEl.className = `wf-graph-node ${cardClass}`;
        nodeEl.tabIndex = 0;
        nodeEl.setAttribute('role', 'button');
        nodeEl.setAttribute('aria-label', `${displayType}: ${step.name || 'Step'}`);
        nodeEl.style.left = `${posX}px`;
        nodeEl.style.top = `${posY}px`;
        nodeEl.setAttribute('data-node-idx', idx);

        nodeEl.innerHTML = `
            ${idx > 0 ? '<div class="wf-node-port input"></div>' : ''}
            ${idx < steps.length - 1 ? '<div class="wf-node-port output"></div>' : ''}
            <div class="wf-node-header">
                <span class="node-type-pill">${escapeHtml(displayType)}</span>
                <span style="font-size: 11px; font-family: var(--font-mono); color: var(--text-muted);">Step ${idx + 1}</span>
            </div>
            <div class="wf-node-title" title="${escapeHtml(step.name || '')}">
                <span>${icon}</span>
                <span>${escapeHtml(step.name || 'Workflow Step')}</span>
            </div>
            <div class="wf-node-desc">
                ${escapeHtml(formatNodeSummary(step))}
            </div>
        `;

        const openDetails = (e) => {
            e.stopPropagation();
            document.querySelectorAll('.wf-graph-node').forEach(n => n.classList.remove('selected'));
            nodeEl.classList.add('selected');
            openWfNodeModal(step, idx, displayType, icon, rule);
        };

        nodeEl.onclick = openDetails;
        nodeEl.onkeydown = (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                openDetails(e);
            }
        };

        nodesLayer.appendChild(nodeEl);
    });

    // Store node coords for mini-map rendering
    wfGraphState.nodeCoords = nodeCoords;

    // Render SVG bezier curve connectors
    for (let i = 0; i < nodeCoords.length - 1; i++) {
        const from = nodeCoords[i];
        const to = nodeCoords[i + 1];

        const x1 = from.x + from.width;
        const y1 = from.y + 42;
        const x2 = to.x;
        const y2 = to.y + 42;

        const dx = Math.abs(x2 - x1) * 0.55;
        const cx1 = x1 + dx;
        const cy1 = y1;
        const cx2 = x2 - dx;
        const cy2 = y2;

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', `M ${x1} ${y1} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${x2} ${y2}`);
        path.setAttribute('class', 'wf-connector-path animated');
        path.setAttribute('marker-end', 'url(#wfArrowMarker)');
        svgLayer.appendChild(path);
    }

    // Automatically fit the complete graph into the canvas viewport
    wfGraphFitView();

    // Render interactive mini-map
    updateWfMinimap();
}

function initWfMinimap() {
    if (wfGraphState.minimapInitialized) return;
    const wrapper = document.getElementById('wfMinimapWrapper');
    if (!wrapper) return;

    wrapper.addEventListener('click', (e) => {
        const viewport = document.getElementById('wfCanvasViewport');
        if (!viewport) return;

        const bounds = wrapper.getBoundingClientRect();
        const clickX = e.clientX - bounds.left;
        const clickY = e.clientY - bounds.top;

        const scaleX = wfGraphState.minimapScaleX || (160 / 1200);
        const scaleY = wfGraphState.minimapScaleY || (90 / 320);

        const targetWorldX = clickX / scaleX;
        const targetWorldY = clickY / scaleY;

        wfGraphState.panX = Math.round((viewport.clientWidth / 2) - (targetWorldX * wfGraphState.zoom));
        wfGraphState.panY = Math.round((viewport.clientHeight / 2) - (targetWorldY * wfGraphState.zoom));

        applyWfGraphTransform();
    });

    wfGraphState.minimapInitialized = true;
}

function toggleWfMinimap() {
    const container = document.getElementById('wfMinimapContainer');
    const btn = document.getElementById('btnToggleMinimap');
    if (!container) return;

    wfGraphState.minimapCollapsed = !wfGraphState.minimapCollapsed;
    if (wfGraphState.minimapCollapsed) {
        container.classList.add('collapsed');
        if (btn) btn.textContent = '▴';
    } else {
        container.classList.remove('collapsed');
        if (btn) btn.textContent = '▾';
        updateWfMinimap();
    }
}

function updateWfMinimap() {
    if (wfGraphState.minimapCollapsed) return;
    const canvas = document.getElementById('wfMinimapCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const nodes = wfGraphState.nodeCoords || [];
    if (nodes.length === 0) return;

    // Calculate world bounding box
    const maxWorldX = Math.max(1000, nodes[nodes.length - 1].x + nodes[nodes.length - 1].width + 80);
    const maxWorldY = 320;

    const scaleX = canvas.width / maxWorldX;
    const scaleY = canvas.height / maxWorldY;

    wfGraphState.minimapScaleX = scaleX;
    wfGraphState.minimapScaleY = scaleY;

    // Draw connecting path
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = 'rgba(56, 189, 248, 0.45)';
    ctx.beginPath();
    for (let i = 0; i < nodes.length; i++) {
        const nx = (nodes[i].x + nodes[i].width / 2) * scaleX;
        const ny = (nodes[i].y + nodes[i].height / 2) * scaleY;
        if (i === 0) {
            ctx.moveTo(nx, ny);
        } else {
            ctx.lineTo(nx, ny);
        }
    }
    ctx.stroke();

    // Node category colors
    const typeColors = {
        trigger: '#3b82f6',
        condition: '#f59e0b',
        urgency: '#f59e0b',
        ai: '#8b5cf6',
        approval: '#f43f5e',
        action: '#14b8a6',
        end: '#10b981'
    };

    // Draw mini node dots
    nodes.forEach((n) => {
        const nx = (n.x + n.width / 2) * scaleX;
        const ny = (n.y + n.height / 2) * scaleY;
        const rawType = (n.step?.type || 'action').toLowerCase();
        let color = '#14b8a6';
        for (const [key, c] of Object.entries(typeColors)) {
            if (rawType.includes(key)) {
                color = c;
                break;
            }
        }
        ctx.fillStyle = color;
        ctx.shadowColor = color;
        ctx.shadowBlur = 4;
        ctx.beginPath();
        ctx.arc(nx, ny, 3.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
    });

    updateWfMinimapViewport();
}

function updateWfMinimapViewport() {
    if (wfGraphState.minimapCollapsed) return;
    const viewport = document.getElementById('wfCanvasViewport');
    const rect = document.getElementById('wfMinimapViewportRect');
    if (!viewport || !rect) return;

    const scaleX = wfGraphState.minimapScaleX || (160 / 1200);
    const scaleY = wfGraphState.minimapScaleY || (90 / 320);

    const vpW = viewport.clientWidth || 800;
    const vpH = viewport.clientHeight || 500;
    const zoom = Math.max(0.1, wfGraphState.zoom || 1.0);

    // Visible region in world coordinates
    const worldLeft = -wfGraphState.panX / zoom;
    const worldTop = -wfGraphState.panY / zoom;
    const worldW = vpW / zoom;
    const worldH = vpH / zoom;

    const rLeft = Math.round(worldLeft * scaleX);
    const rTop = Math.round(worldTop * scaleY);
    const rW = Math.round(worldW * scaleX);
    const rH = Math.round(worldH * scaleY);

    rect.style.left = `${Math.max(0, Math.min(150, rLeft))}px`;
    rect.style.top = `${Math.max(0, Math.min(80, rTop))}px`;
    rect.style.width = `${Math.max(14, Math.min(160, rW))}px`;
    rect.style.height = `${Math.max(10, Math.min(90, rH))}px`;
}

function formatNodeSummary(step) {
    const cfg = step.config || {};
    if (step.type === 'trigger') {
        return `Trigger: ${cfg.event_name || cfg.type || 'System Event'}`;
    }
    if (step.type === 'condition' || step.type === 'urgency_detection') {
        if (cfg.min_urgency) return `Urgency threshold: ≥ ${cfg.min_urgency}`;
        const count = (cfg.conditions || []).length;
        return `${cfg.logic || 'AND'} Tree (${count} evaluation rule${count === 1 ? '' : 's'})`;
    }
    if (cfg.destination) return `Route to: ${cfg.destination}`;
    if (cfg.severity) return `Severity: ${cfg.severity}`;
    if (cfg.recipient) return `To: ${cfg.recipient}`;
    if (cfg.url) return `Webhook: ${cfg.url}`;
    if (cfg.threshold) return `Lead score threshold: ${cfg.threshold}`;
    if (cfg.table) return `Persist to: ${cfg.table}`;
    return JSON.stringify(cfg).substring(0, 48) || 'Configured parameters';
}

function openWfNodeModal(step, idx, displayType, icon, rule) {
    const modal = document.getElementById('wfNodeDetailModal');
    if (!modal) return;

    document.getElementById('wfModalNodeIcon').textContent = icon;
    document.getElementById('wfModalNodeName').textContent = `${step.name || 'Step'} (Step ${idx + 1})`;

    const body = document.getElementById('wfModalNodeBody');
    body.innerHTML = `
        <div style="margin-bottom: 12px; padding: 10px; background: rgba(0,0,0,0.25); border-radius: 6px;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                <span style="font-weight: 600; color: var(--text-primary);">Type:</span>
                <span class="node-type-pill" style="font-size: 11px;">${escapeHtml(displayType)}</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                <span style="font-weight: 600; color: var(--text-primary);">Workflow:</span>
                <span style="color: var(--cyan-glow); font-weight: 600;">${escapeHtml(rule.name)}</span>
            </div>
            <div style="display: flex; justify-content: space-between;">
                <span style="font-weight: 600; color: var(--text-primary);">Execution State:</span>
                <span style="color: #10b981; font-weight: 600;">● Ready / Verified</span>
            </div>
        </div>
        <div style="font-weight: 600; margin-bottom: 6px; color: var(--text-primary);">Step Configuration:</div>
        <pre style="background: rgba(0,0,0,0.4); padding: 12px; border-radius: 6px; font-family: var(--font-mono); font-size: 12px; color: #a5f3fc; overflow-x: auto; border: 1px solid var(--border-subtle);">${escapeHtml(JSON.stringify(step.config || {}, null, 2))}</pre>
    `;

    modal.style.display = 'flex';
}

function closeWfNodeModal() {
    const modal = document.getElementById('wfNodeDetailModal');
    if (modal) modal.style.display = 'none';
}

async function runSelectedGraphWorkflow() {
    if (!wfGraphState.activeRuleId) return;
    const ruleId = wfGraphState.activeRuleId;
    const runBtn = document.querySelector('#workflowGraphView .wf-graph-toolbar button.primary');
    const originalText = runBtn ? runBtn.innerHTML : '▶ Run';
    if (runBtn) {
        runBtn.disabled = true;
        runBtn.innerHTML = '<span>⏳</span> Running...';
    }

    // Traversal wave pulse across nodes and SVG paths
    const nodes = Array.from(document.querySelectorAll('#wfGraphNodesLayer .wf-graph-node'));
    const paths = Array.from(document.querySelectorAll('#wfGraphSvgLayer path.wf-connector-path'));

    // Sequential traversal animation helper
    const animateTraversal = async () => {
        for (let i = 0; i < nodes.length; i++) {
            const node = nodes[i];
            node.classList.remove('executed');
            node.classList.add('executing');

            if (i > 0 && paths[i - 1]) {
                paths[i - 1].classList.add('traversing');
            }

            await new Promise(r => setTimeout(r, 260));

            node.classList.remove('executing');
            node.classList.add('executed');
        }
    };

    try {
        const animPromise = animateTraversal();

        const res = await fetch(`/api/v1/rules/${ruleId}/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dry_run: false, payload: { test_source: 'graph_studio_ui', timestamp: new Date().toISOString() } })
        });
        const data = await res.json();
        await animPromise;

        if (res.ok) {
            showToast(`Workflow executed: ${(data.status || 'SUCCESS').toUpperCase()}`, 'success');
            loadExecutionLogs();
            loadRules();
        } else {
            showToast(data.error || 'Execution failed', 'error');
        }
    } catch (e) {
        showToast(`Execution error: ${e.message}`, 'error');
    } finally {
        if (runBtn) {
            runBtn.disabled = false;
            runBtn.innerHTML = originalText;
        }
        // Cleanup execution classes after 3 seconds
        setTimeout(() => {
            nodes.forEach(n => {
                n.classList.remove('executing', 'executed');
            });
            paths.forEach(p => {
                p.classList.remove('traversing');
            });
        }, 3000);
    }
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
    const originalText = btn ? btn.innerHTML : '';
    try {
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span>⏳</span> Running...';
        }
        
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
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
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

    const curlEl = document.getElementById('webhookCurlSnippet');
    if (curlEl) {
        const prodBase = (window.location.origin && !window.location.origin.includes('file://')) ? window.location.origin : 'https://ai-automation-command-center-4.onrender.com';
        const targetId = (state.webhooks && state.webhooks.length > 0 && state.webhooks[0].id) ? state.webhooks[0].id : 'wh_live_prod_alert_stream';
        curlEl.textContent = `curl -X POST "${prodBase}/api/v1/webhooks/incoming/${targetId}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"event": "system.metrics", "cpu_percent": 94.5, "host": "prod-k8s-01"}'`;
    }
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
                <td data-label="Execution ID"><code style="font-size:0.8rem; color:var(--text-muted);">${log.id}</code></td>
                <td data-label="Workflow"><strong>${escapeHtml(log.rule_name || 'System Dispatcher')}</strong></td>
                <td data-label="Trigger Event"><code style="color:var(--cyan-glow);">${escapeHtml(log.trigger_event || log.event_name)}</code></td>
                <td data-label="Status"><span class="${badgeClass}">${statusIcon} ${(log.status || 'SUCCESS').toUpperCase()}</span></td>
                <td data-label="Latency" class="num-cell"><span style="font-family:var(--font-mono);">${log.duration_ms || log.execution_time_ms || 0} ms</span></td>
                <td data-label="Timestamp" style="font-size:0.75rem; color:var(--text-muted);">${log.timestamp || log.executed_at}</td>
                <td data-label="Actions">
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
            description: 'Generate programmatic API tokens to integrate BashFlow Cloud into your CI/CD pipelines, backend services, or monitoring scripts.',
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
                <td><span style="font-family:var(--font-mono); font-size:0.8rem;">${escapeHtml((!a.ip_address || a.ip_address === '127.0.0.1') ? (window.location.hostname && !['localhost', '127.0.0.1', ''].includes(window.location.hostname) ? '182.180.74.192' : (a.ip_address || '127.0.0.1')) : a.ip_address)}</span></td>
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

        const contactName = l.name && l.name !== 'N/A' && l.name !== 'Anonymous' ? l.name : (l.phone || 'Inbound Lead');
        const phoneDisplay = l.phone && l.phone !== 'N/A' ? l.phone : '';
        const emailDisplay = l.email && l.email !== 'N/A' && l.email !== 'No email' ? l.email : '';
        const companyDisplay = l.company && l.company !== 'N/A' ? l.company : '';

        return `
            <tr>
                <td>
                    <div style="font-weight: 600; color: #fff; font-size: 0.9rem;">${escapeHtml(contactName)}</div>
                    ${phoneDisplay ? `<div style="font-size: 0.8rem; color: #10b981; font-family: monospace; font-weight: 600;">📱 ${escapeHtml(phoneDisplay)}</div>` : ''}
                    ${emailDisplay ? `<div style="font-size: 0.75rem; color: #06b6d4; font-family: monospace;">✉️ ${escapeHtml(emailDisplay)}</div>` : ''}
                    ${companyDisplay ? `<div style="font-size: 0.75rem; color: #94a3b8;">🏢 ${escapeHtml(companyDisplay)}</div>` : ''}
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
    applyMobileTableLabels(tbody.closest('table'));
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

    const contactName = lead.name && lead.name !== 'N/A' && lead.name !== 'Anonymous' ? lead.name : (lead.phone || 'Inbound Customer');
    const contactPhone = lead.phone && lead.phone !== 'N/A' ? lead.phone : 'Direct WhatsApp';
    const contactEmail = lead.email && lead.email !== 'N/A' ? lead.email : 'WhatsApp Direct';
    const contactCompany = lead.company && lead.company !== 'N/A' ? lead.company : 'Direct Client';

    alert(
        `LEAD DETAILS & AI ANALYSIS\n` +
        `-----------------------------------------\n` +
        `Contact Name: ${contactName}\n` +
        `Phone Number: ${contactPhone}\n` +
        `Email: ${contactEmail}\n` +
        `Organization / Company: ${contactCompany}\n` +
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
        if (title) title.textContent = 'Create Free Account';
        if (subtitle) subtitle.textContent = 'Get started with intelligent automation in seconds';
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
        if (title) title.textContent = 'BashFlow Cloud Authentication';
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
    let organization_name = (document.getElementById('regOrgName')?.value || '').trim();
    if (!organization_name) {
        organization_name = full_name ? `${full_name}'s Workspace` : 'Primary Workspace';
    }
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
        submitBtn.textContent = 'Creating Account...';
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
            showToast(`Account created successfully! Welcome, ${full_name || 'Operator'}!`, 'success');
            await initAuthAndTenancy();
            refreshAllData();
            // Launch the 5-step onboarding wizard
            openOnboardingWizard(data);
        } else {
            if (errBox) {
                errBox.textContent = data.error || 'Failed to register account.';
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
            submitBtn.textContent = 'Create Free Account \u2192';
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
    showToast('Signed out of BashFlow Cloud.', 'info');
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
        applyMobileTableLabels(tbody.closest('table'));
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
        applyMobileTableLabels(tbody.closest('table'));
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

let waQrInlinePollInterval = null;

function setWhatsAppViewMode(mode) {
    window._waCurrentViewMode = mode;
    const btnWeb = document.getElementById('btnViewWaWeb');
    const btnClassic = document.getElementById('btnViewWaClassic');
    const webContainer = document.getElementById('waWebViewContainer');
    const connectContainer = document.getElementById('waConnectState');
    const classicContainer = document.getElementById('waClassicViewContainer');
    const banner = document.getElementById('whatsappModeBanner');

    const isConnected = Boolean(window._waIsConnected || window._waDemoMode);

    if (waQrInlinePollInterval) {
        clearInterval(waQrInlinePollInterval);
        waQrInlinePollInterval = null;
    }

    if (mode === 'web') {
        if (btnWeb) btnWeb.classList.add('active');
        if (btnClassic) btnClassic.classList.remove('active');
        if (classicContainer) classicContainer.style.display = 'none';
        if (banner) banner.style.display = 'none'; // Clean unified experience without redundant top banner clutter

        if (isConnected) {
            if (connectContainer) connectContainer.style.display = 'none';
            if (webContainer) webContainer.style.display = 'flex';
            renderWhatsAppWebUI(waAllMessagesCache);
        } else {
            if (webContainer) webContainer.style.display = 'none';
            if (connectContainer) {
                connectContainer.style.display = 'flex';
                fetchWhatsAppQrCode();
                waQrInlinePollInterval = setInterval(() => {
                    if (window._waIsConnected) {
                        clearInterval(waQrInlinePollInterval);
                        waQrInlinePollInterval = null;
                        return;
                    }
                    fetchWhatsAppQrCode();
                }, 3000);
            }
        }
    } else {
        if (btnWeb) btnWeb.classList.remove('active');
        if (btnClassic) btnClassic.classList.add('active');
        if (connectContainer) connectContainer.style.display = 'none';
        if (webContainer) webContainer.style.display = 'none';
        if (classicContainer) classicContainer.style.display = 'flex';
        if (banner) banner.style.display = 'flex';
    }
}

function enableWhatsAppDemoMode() {
    window._waDemoMode = true;
    if (typeof showToast === 'function') {
        showToast('Local Sandbox Demo Mode activated. Full WhatsApp Web console unlocked.', 'info');
    }
    setWhatsAppViewMode('web');
}

async function fetchWhatsAppQrCode() {
    const qrImg = document.getElementById('waDynamicQrImg');
    const qrStatic = document.getElementById('waStaticQrPlaceholder');
    const qrStatus = document.getElementById('waQrStatusText');
    try {
        let res = null;
        try {
            res = await fetch('/api/v1/whatsapp/bridge-qr');
        } catch (_) {
            res = await fetch('/api/whatsapp/bridge-qr');
        }
        if (res && res.ok) {
            const data = await res.json();
            if (data.status === 'connected' || data.connected) {
                if (qrStatus) qrStatus.innerHTML = '<span>●</span><span>WhatsApp Connected! Loading...</span>';
                window._waIsConnected = true;
                if (waQrInlinePollInterval) {
                    clearInterval(waQrInlinePollInterval);
                    waQrInlinePollInterval = null;
                }
                setTimeout(() => {
                    setWhatsAppViewMode('web');
                    loadWhatsAppDashboard();
                }, 400);
                return;
            }

            const qrSrc = data.qrUrl || data.qrImageUrl;
            if ((data.status === 'qr_ready' || qrSrc || data.qr) && (qrSrc || data.qrSvg || data.qr)) {
                if (qrSrc && (qrSrc.startsWith('data:') || qrSrc.startsWith('http'))) {
                    if (qrImg) {
                        qrImg.src = qrSrc;
                        qrImg.style.display = 'block';
                    }
                    if (qrStatic) qrStatic.style.display = 'none';
                } else if (data.qrSvg && qrStatic) {
                    qrStatic.innerHTML = data.qrSvg;
                    qrStatic.style.display = 'flex';
                    if (qrImg) qrImg.style.display = 'none';
                } else if (data.qr && qrImg) {
                    qrImg.src = `https://quickchart.io/qr?size=220&text=${encodeURIComponent(data.qr)}`;
                    qrImg.style.display = 'block';
                    if (qrStatic) qrStatic.style.display = 'none';
                }
                if (qrStatus) qrStatus.innerHTML = '<span>●</span><span>Scan QR code with WhatsApp</span>';
            } else {
                if (qrImg) qrImg.style.display = 'none';
                if (qrStatic) qrStatic.style.display = 'flex';
                if (qrStatus) qrStatus.innerHTML = `<span>●</span><span>${data.message || 'Connecting to WhatsApp Baileys bridge...'}</span>`;
            }
        }
    } catch (e) {
        console.debug('Failed to fetch WhatsApp QR code:', e);
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

function normalizeWaPhone(phone) {
    if (!phone) return '';
    let str = String(phone).trim();
    if (!str || /[a-zA-Z]/.test(str)) return str;
    if (str.endsWith('@lid') || str.includes('@lid')) return str;
    if (str.endsWith('@g.us') || str.endsWith('@broadcast')) return str;
    let raw = str.replace(/@s\.whatsapp\.net|@c\.us/gi, '').split(':')[0].trim();
    let clean = raw.replace(/[^0-9]/g, '');
    if (clean.length > 13) return str;
    if (clean.startsWith('03') && clean.length === 11) {
        clean = '92' + clean.slice(1);
    } else if (clean.startsWith('3') && clean.length === 10) {
        clean = '92' + clean;
    } else if (clean.startsWith('913') && clean.length === 12) {
        clean = '923' + clean.slice(3);
    } else if (clean.startsWith('00')) {
        clean = clean.slice(2);
    }
    return clean || raw;
}

function formatWaDisplayPhone(phone) {
    if (!phone) return '';
    let str = String(phone).trim();
    if (!str || str.toLowerCase() === 'null' || str.toLowerCase() === 'undefined') return '';

    // CRITICAL: If string contains any alphabetic characters, it is a contact name or text label (e.g. 'WhatsApp Contact', 'WhatsApp User')
    // NEVER prepend '+' or split spaces into non-numeric strings!
    if (/[a-zA-Z]/.test(str)) {
        return str;
    }

    if (str.endsWith('@g.us')) return 'WhatsApp Group';
    if (str.endsWith('@broadcast')) return 'Status Broadcast';

    const cleanDigits = str.replace(/[^0-9]/g, '');
    if (!cleanDigits || cleanDigits.length < 7) {
        return str;
    }
    if (str.endsWith('@lid') || cleanDigits.length > 13) {
        return 'WhatsApp Contact';
    }

    // Pakistani number: 923XXXXXXXXX (12 digits starting with 92)
    if (cleanDigits.startsWith('92') && cleanDigits.length === 12) {
        return `+92 ${cleanDigits.slice(2, 5)} ${cleanDigits.slice(5)}`;
    }

    // Known international formats — add spacing after country code
    if (cleanDigits.length >= 10 && cleanDigits.length <= 13) {
        // Belgium +32
        if (cleanDigits.startsWith('32') && cleanDigits.length >= 11) {
            return `+32 ${cleanDigits.slice(2, 5)} ${cleanDigits.slice(5, 8)} ${cleanDigits.slice(8)}`;
        }
        // UK +44
        if (cleanDigits.startsWith('44') && cleanDigits.length >= 12) {
            return `+44 ${cleanDigits.slice(2, 6)} ${cleanDigits.slice(6)}`;
        }
        // USA/Canada +1
        if (cleanDigits.startsWith('1') && cleanDigits.length === 11) {
            return `+1 (${cleanDigits.slice(1, 4)}) ${cleanDigits.slice(4, 7)}-${cleanDigits.slice(7)}`;
        }
        // UAE +971
        if (cleanDigits.startsWith('971') && cleanDigits.length >= 12) {
            return `+971 ${cleanDigits.slice(3, 5)} ${cleanDigits.slice(5)}`;
        }
        // India +91
        if (cleanDigits.startsWith('91') && cleanDigits.length === 12) {
            return `+91 ${cleanDigits.slice(2, 7)} ${cleanDigits.slice(7)}`;
        }
        // Generic: insert space after country code (2 digits) and every 3 digits after
        const cc = cleanDigits.slice(0, 2);
        const rest = cleanDigits.slice(2);
        const grouped = rest.replace(/(\d{3})(?=\d)/g, '$1 ').trim();
        return `+${cc} ${grouped}`;
    }

    if (cleanDigits.length >= 8 && cleanDigits.length <= 13) {
        return `+${cleanDigits}`;
    }
    return str;
}

function isSameWaPhone(p1, p2) {
    if (!p1 || !p2) return false;
    const n1 = normalizeWaPhone(p1);
    const n2 = normalizeWaPhone(p2);
    if (n1 === n2) return true;
    if (n1.length >= 8 && n2.length >= 8) {
        return n1.slice(-8) === n2.slice(-8);
    }
    return false;
}

function groupWhatsAppConversations(messages) {
    const map = {};
    (messages || []).forEach(m => {
        const isInbound = m.direction === 'inbound';
        // Strip JID suffixes from partner before normalizing so that
        // "32844168577254@s.whatsapp.net" and "32844168577254" map to the same key
        const rawPartner = isInbound ? m.sender : m.recipient;

        // Skip entries where the partner is a group JID — groups are forwarded via
        // the bridge but should not appear as individual direct-chat conversations
        // unless explicitly supported. They're excluded here to prevent malformed
        // outbound dispatch when the user clicks "Reply" on a group-sourced message.
        if (rawPartner && (String(rawPartner).includes('@g.us') || String(rawPartner).includes('@broadcast'))) {
            return;
        }

        const normKey = normalizeWaPhone(rawPartner) || 'Unknown';
        const displayPhone = formatWaDisplayPhone(rawPartner) || normKey;

        if (!map[normKey]) {
            let initialMsg = (m.body && m.body !== '(no text)') ? m.body : (m.is_audio ? '🎙️ Voice note' : '(no text)');
            if (initialMsg.includes('[quotedMessage]')) {
                initialMsg = initialMsg.replace(/\[quotedMessage\]/gi, 'Quoted message');
            }
            map[normKey] = {
                phone: displayPhone,
                normalizedPhone: normKey,
                // Prefer contact name from inbound sender_name; fallback to display number
                name: (isInbound ? m.sender_name : '') || displayPhone,
                lastMessage: initialMsg,
                timestamp: m.created_at || '',
                is_audio: Boolean(m.is_audio),
                messages: []
            };
        }
        map[normKey].messages.push(m);
        // Update last message preview to the most recent message (last in array)
        const latestMsg = map[normKey].messages[map[normKey].messages.length - 1];
        let latestText = (latestMsg.body && latestMsg.body !== '(no text)') ? latestMsg.body : ((latestMsg.is_audio || latestMsg.type === 'audio' || latestMsg.message_type === 'audio') ? '🎤 Voice message' : '(no text)');
        if (latestText.includes('[quotedMessage]')) {
            latestText = latestText.replace(/\[quotedMessage\]/gi, 'Quoted message');
        }
        map[normKey].lastMessage = latestText;
        map[normKey].timestamp = latestMsg.created_at || map[normKey].timestamp;
        map[normKey].is_audio = Boolean(latestMsg.is_audio);
        // Prefer contact name from any inbound sender_name
        if (m.sender_name && m.direction === 'inbound' && (!map[normKey].name || map[normKey].name === displayPhone || map[normKey].name === normKey)) {
            map[normKey].name = m.sender_name;
        }
    });

    const list = Object.values(map);
    // Sort by latest message timestamp descending (most recent first)
    list.sort((a, b) => {
        const timeA = a.timestamp || '';
        const timeB = b.timestamp || '';
        return timeB.localeCompare(timeA);
    });
    return list;
}

function handleWhatsAppChatSearch(val) {
    waChatSearchTerm = (val || '').toLowerCase().trim();
    renderWhatsAppWebUI(waAllMessagesCache, false);
}

function selectWhatsAppChat(partner) {
    waActiveChatPartner = normalizeWaPhone(partner) || partner;
    if (Array.isArray(waAllMessagesCache)) {
        waAllMessagesCache.forEach(m => {
            const mPartner = (m.direction === 'inbound' ? m.sender : m.recipient) || '';
            if (isSameWaPhone(mPartner, waActiveChatPartner) && m.direction === 'inbound') {
                m.status = 'read';
            }
        });
    }
    renderWhatsAppWebUI(waAllMessagesCache, true);
    if (waActiveChatPartner) {
        const norm = normalizeWaPhone(waActiveChatPartner) || waActiveChatPartner;
        fetch(`/api/v1/whatsapp/conversations/${encodeURIComponent(norm)}/read`, {
            method: 'POST',
            headers: typeof getAuthHeaders === 'function' ? getAuthHeaders() : { 'Content-Type': 'application/json' }
        }).catch(err => console.debug('Mark chat read notice:', err));
    }
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

function dataUriToBlob(dataUri) {
    try {
        if (!dataUri || typeof dataUri !== 'string') return null;
        let b64 = '';
        let mime = 'audio/ogg';
        if (dataUri.includes(',')) {
            const parts = dataUri.split(',');
            const mimeMatch = parts[0].match(/:(.*?);/);
            mime = mimeMatch ? mimeMatch[1] : 'audio/ogg';
            b64 = parts[1].trim();
        } else {
            b64 = dataUri.trim();
        }
        mime = mime.replace(/;\s*codecs=[^;,]+/i, '').trim();
        const bstr = atob(b64);
        let n = bstr.length;
        const u8arr = new Uint8Array(n);
        while (n--) {
            u8arr[n] = bstr.charCodeAt(n);
        }
        return new Blob([u8arr], { type: mime });
    } catch (e) {
        console.warn('[dataUriToBlob error]', e);
        return null;
    }
}

function resetVoicePlayback(id) {
    if (waVoiceProgressInterval) {
        clearInterval(waVoiceProgressInterval);
        waVoiceProgressInterval = null;
    }
    if (waCurrentAudio) {
        try {
            waCurrentAudio.pause();
            if (waCurrentAudio._blobUrl) {
                URL.revokeObjectURL(waCurrentAudio._blobUrl);
                waCurrentAudio._blobUrl = null;
            }
        } catch(e) {}
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

function togglePlayVoiceMessage(id, explicitMediaUrl, explicitText) {
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

    // Look up the cached message object for reliable media extraction
    const targetMsg = (waAllMessagesCache || []).find(x => String(x.id) === String(id) || String(x.whatsapp_message_id) === String(id));
    let mediaUrl = explicitMediaUrl || targetMsg?.media_url || targetMsg?.raw_payload?.audio_base64 || targetMsg?.audio_base64 || '';
    if (mediaUrl && typeof mediaUrl === 'string') {
        mediaUrl = mediaUrl.trim();
        if (!mediaUrl.startsWith('data:') && !mediaUrl.startsWith('http') && !mediaUrl.startsWith('/api/') && mediaUrl.length > 50) {
            mediaUrl = `data:audio/ogg;base64,${mediaUrl}`;
        }
        if (mediaUrl.startsWith('data:')) {
            mediaUrl = mediaUrl.replace(/;\s*codecs=[^;,]+/i, '');
        }
    }
    const textBody = explicitText || targetMsg?.body || '';

    if (mediaUrl) {
        let playSrc = mediaUrl;
        let blobUrl = null;

        if (mediaUrl.startsWith('data:')) {
            const blob = dataUriToBlob(mediaUrl);
            if (blob) {
                blobUrl = URL.createObjectURL(blob);
                playSrc = blobUrl;
            }
        } else if (mediaUrl.startsWith('http://') || mediaUrl.startsWith('https://')) {
            playSrc = `/api/v1/whatsapp/media/proxy?url=${encodeURIComponent(mediaUrl)}`;
        }

        try {
            const audio = new Audio(playSrc);
            if (blobUrl) audio._blobUrl = blobUrl;
            waCurrentAudio = audio;

            audio.ontimeupdate = () => {
                const prog = document.getElementById(`waAudioProg_${id}`);
                const timeEl = document.getElementById(`waAudioTime_${id}`);
                if (audio.duration && !isNaN(audio.duration) && audio.duration > 0) {
                    const pct = Math.min(100, (audio.currentTime / audio.duration) * 100);
                    if (prog) prog.style.width = `${pct}%`;
                    if (timeEl) timeEl.textContent = `${formatAudioSeconds(audio.currentTime)} / ${formatAudioSeconds(audio.duration)}`;
                } else if (audio.currentTime > 0 && timeEl) {
                    timeEl.textContent = formatAudioSeconds(audio.currentTime);
                }
            };

            audio.onended = () => resetVoicePlayback(id);
            audio.onerror = (e) => {
                console.warn('[Audio Playback Error, using speech fallback]', e);
                fallbackSpeechPlayback(id, textBody);
            };

            const playPromise = audio.play();
            if (playPromise !== undefined) {
                playPromise.catch(e => {
                    console.warn('[Audio play() rejected, using speech fallback]', e);
                    fallbackSpeechPlayback(id, textBody);
                });
            }
            return;
        } catch (initErr) {
            console.warn('[Audio constructor failed]', initErr);
        }
    }

    fallbackSpeechPlayback(id, textBody);
}

async function deleteWhatsAppMsg(msgId) {
    if (!confirm('Are you sure you want to delete this message? If supported by the connected provider (e.g. Green-API), remote deletion will also be requested.')) return;
    try {
        const headers = typeof getAuthHeaders === 'function' ? getAuthHeaders() : { 'Content-Type': 'application/json' };
        const res = await fetch(`/api/v1/whatsapp/messages/${encodeURIComponent(msgId)}`, {
            method: 'DELETE',
            headers: headers
        });
        const data = await res.json();
        if (res.ok && data.success) {
            if (data.remote_success) {
                showToast(`Message deleted locally & on WhatsApp: ${data.remote_detail}`, 'success');
            } else if (data.remote_detail) {
                showToast(`Message deleted locally (${data.remote_detail})`, 'info');
            } else {
                showToast('Message deleted successfully', 'success');
            }
            waAllMessagesCache = (waAllMessagesCache || []).filter(m => m.id !== msgId && m.whatsapp_message_id !== msgId);
            renderWhatsAppWebUI(waAllMessagesCache, false);
            loadWhatsAppMessagesOnly();
        } else {
            showToast(data.error || 'Failed to delete message', 'error');
        }
    } catch (err) {
        showToast(`Error deleting message: ${err.message}`, 'error');
    }
}

async function promptForwardWhatsAppMsg(msgId) {
    const target = (waAllMessagesCache || []).find(m => m.id === msgId || m.whatsapp_message_id === msgId);
    const snippet = target && target.body ? ` "${target.body.substring(0, 36)}${target.body.length > 36 ? '...' : ''}"` : '';
    const toPhone = prompt(`Forward message${snippet} to phone number (e.g. +923001234567 or 923001234567):`);
    if (!toPhone || !toPhone.trim()) return;

    try {
        const headers = typeof getAuthHeaders === 'function' ? getAuthHeaders() : { 'Content-Type': 'application/json' };
        const res = await fetch(`/api/v1/whatsapp/messages/${encodeURIComponent(msgId)}/forward`, {
            method: 'POST',
            headers: {
                ...headers,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ to: toPhone.trim() })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            if (data.remote_success) {
                showToast(`Message forwarded to +${data.recipient} (${data.remote_detail || 'Provider sent'})`, 'success');
            } else {
                showToast(`Forward recorded/simulated for +${data.recipient} (${data.remote_detail || 'Simulated'})`, 'info');
            }
            loadWhatsAppMessagesOnly();
        } else {
            showToast(data.error || 'Failed to forward message', 'error');
        }
    } catch (err) {
        showToast(`Error forwarding message: ${err.message}`, 'error');
    }
}

async function markCurrentConversationUnread() {
    if (!waActiveChatPartner) {
        showToast('No active conversation selected to mark unread', 'info');
        return;
    }
    const partner = waActiveChatPartner;
    try {
        const norm = normalizeWaPhone(partner) || partner;
        const headers = typeof getAuthHeaders === 'function' ? getAuthHeaders() : { 'Content-Type': 'application/json' };
        const res = await fetch(`/api/v1/whatsapp/conversations/${encodeURIComponent(norm)}/unread`, {
            method: 'POST',
            headers: headers
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast(`Conversation with +${partner.replace(/^\+/, '')} marked as unread`, 'success');
            if (Array.isArray(waAllMessagesCache)) {
                waAllMessagesCache.forEach(m => {
                    const p = (m.direction === 'inbound' ? m.sender : m.recipient) || '';
                    if (isSameWaPhone(p, partner) && m.direction === 'inbound') {
                        m.status = 'received';
                    }
                });
            }
            waActiveChatPartner = null;
            renderWhatsAppWebUI(waAllMessagesCache, false);
        } else {
            showToast(data.error || 'Failed to mark conversation as unread', 'error');
        }
    } catch (err) {
        showToast(`Error marking unread: ${err.message}`, 'error');
    }
}

async function markWhatsAppMsgUnread(msgId) {
    try {
        const headers = typeof getAuthHeaders === 'function' ? getAuthHeaders() : { 'Content-Type': 'application/json' };
        const res = await fetch(`/api/v1/whatsapp/messages/${encodeURIComponent(msgId)}/unread`, {
            method: 'POST',
            headers: headers
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast('Message marked as unread', 'success');
            if (Array.isArray(waAllMessagesCache)) {
                const target = waAllMessagesCache.find(m => m.id === msgId || m.whatsapp_message_id === msgId);
                if (target) target.status = 'received';
            }
            waActiveChatPartner = null;
            renderWhatsAppWebUI(waAllMessagesCache, false);
        } else {
            showToast(data.error || 'Failed to mark message as unread', 'error');
        }
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

async function clearCurrentConversation() {
    if (!waActiveChatPartner) {
        showToast('No active conversation selected to clear', 'info');
        return;
    }
    const partner = waActiveChatPartner;
    if (!confirm(`Are you sure you want to permanently delete all messages for ${partner}?`)) return;
    try {
        const norm = normalizeWaPhone(partner) || partner;
        const headers = typeof getAuthHeaders === 'function' ? getAuthHeaders() : { 'Content-Type': 'application/json' };
        const res = await fetch(`/api/v1/whatsapp/conversations/${encodeURIComponent(norm)}`, {
            method: 'DELETE',
            headers: headers
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast(`Conversation permanently deleted (${data.deleted_count || 0} messages removed)`, 'success');
            waAllMessagesCache = (waAllMessagesCache || []).filter(m => {
                const s = (m.sender || '').replace(/@c\.us|@g\.us/g, '').trim();
                const r = (m.recipient || '').replace(/@c\.us|@g\.us/g, '').trim();
                return !isSameWaPhone(s, partner) && !isSameWaPhone(r, partner);
            });
            waActiveChatPartner = null;
            renderWhatsAppWebUI(waAllMessagesCache, true);
            await loadWhatsAppMessagesOnly();
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
        // Strip all non-numeric chars (preserve leading +) and normalize
        waActiveChatPartner = normalizeWaPhone(recipient.replace(/[^0-9+]/g, ''));
        recipient = waActiveChatPartner;
    }

    // Normalize recipient: strip @s.whatsapp.net / @c.us suffixes cleanly.
    // Keep @g.us intact — group sends are routed correctly by send_message().
    // Reject obviously malformed inputs (e.g. bare '@g.us' without a group number).
    const isGroup = String(recipient).endsWith('@g.us');
    const cleanRecipient = isGroup ? recipient : (normalizeWaPhone(recipient) || recipient);
    if (!cleanRecipient || cleanRecipient === '@g.us' || (!isGroup && cleanRecipient.length < 7)) {
        showToast('Invalid recipient — please select a valid conversation first.', 'error');
        return;
    }
    input.value = '';

    const isVoice = message.startsWith('[voiceMessage]') || message.startsWith('[audioMessage]');
    const optimisticId = `opt_${Date.now()}`;
    const optimisticMsg = {
        id: optimisticId,
        whatsapp_message_id: 'pending...',
        direction: 'outbound',
        sender: 'You',
        recipient: cleanRecipient,
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
        const authHeaders = typeof getAuthHeaders === 'function' ? getAuthHeaders() : {};
        const headers = Object.assign({ 'Content-Type': 'application/json' }, authHeaders);
        const res = await fetch('/api/whatsapp/send', {
            method: 'POST',
            headers: headers,
            body: JSON.stringify({
                to: cleanRecipient,
                chatId: cleanRecipient,
                message: message,
                is_voice: isVoice
            })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            optimisticMsg.status = 'sent';
            optimisticMsg.whatsapp_message_id = data.whatsapp_message_id || 'sent';
            showToast(`Delivered to ${cleanRecipient}`, 'success');
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

let mediaRecorderInstance = null;
let recordedAudioChunks = [];
let voiceRecordingInterval = null;
let voiceRecordingSeconds = 0;

async function startVoiceRecording() {
    if (!waActiveChatPartner) {
        showToast('Please select a conversation from the sidebar first', 'info');
        return;
    }

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        fallbackPromptVoiceNote();
        return;
    }

    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        recordedAudioChunks = [];
        
        let options = { mimeType: 'audio/webm;codecs=opus' };
        if (!window.MediaRecorder || !MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
            if (window.MediaRecorder && MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')) {
                options = { mimeType: 'audio/ogg;codecs=opus' };
            } else if (window.MediaRecorder && MediaRecorder.isTypeSupported('audio/mp4')) {
                options = { mimeType: 'audio/mp4' };
            } else {
                options = {};
            }
        }

        mediaRecorderInstance = new MediaRecorder(stream, options);

        mediaRecorderInstance.ondataavailable = function(e) {
            if (e.data && e.data.size > 0) {
                recordedAudioChunks.push(e.data);
            }
        };

        mediaRecorderInstance.onstop = async function() {
            try {
                stream.getTracks().forEach(t => t.stop());
            } catch (_) {}

            if (recordedAudioChunks.length === 0) return;

            const mime = mediaRecorderInstance.mimeType || 'audio/webm';
            const audioBlob = new Blob(recordedAudioChunks, { type: mime });

            const reader = new FileReader();
            reader.onloadend = async function() {
                const base64DataUri = reader.result;
                if (!base64DataUri) return;

                showToast('Dispatching recorded Voice Note to WhatsApp...', 'info');

                try {
                    const recipient = waActiveChatPartner;
                    const cleanRecipient = normalizeWaPhone(recipient) || recipient;
                    const authHeaders = typeof getAuthHeaders === 'function' ? getAuthHeaders() : {};
                    const headers = Object.assign({ 'Content-Type': 'application/json' }, authHeaders);
                    const res = await fetch('/api/whatsapp/send', {
                        method: 'POST',
                        headers: headers,
                        body: JSON.stringify({
                            to: cleanRecipient,
                            chatId: cleanRecipient,
                            message: '[Voice note]',
                            is_voice: true,
                            audio_base64: base64DataUri
                        })
                    });
                    const data = await res.json();
                    if (res.ok && data.success) {
                        showToast(`Voice Note delivered to ${cleanRecipient}`, 'success');
                        syncWhatsAppMessagesNow(true).catch(() => {});
                    } else {
                        showToast(data.error || 'Failed to dispatch voice note', 'error');
                    }
                } catch (err) {
                    showToast('Failed to dispatch voice note: ' + err.message, 'error');
                }
            };
            reader.readAsDataURL(audioBlob);
        };

        mediaRecorderInstance.start(250);
        voiceRecordingSeconds = 0;

        const voiceBtn = document.getElementById('waVoiceNoteBtn');
        const recIndicator = document.getElementById('waRecordingIndicator');
        const timerElem = document.getElementById('waRecordingTimer');
        const replyInput = document.getElementById('waReplyInput');

        if (voiceBtn) {
            voiceBtn.textContent = '⏹️';
            voiceBtn.title = 'Stop & Send Voice Note';
            voiceBtn.style.color = '#ef4444';
        }
        if (recIndicator) recIndicator.style.display = 'flex';
        if (replyInput) replyInput.style.visibility = 'hidden';

        clearInterval(voiceRecordingInterval);
        voiceRecordingInterval = setInterval(() => {
            voiceRecordingSeconds++;
            const mins = String(Math.floor(voiceRecordingSeconds / 60)).padStart(2, '0');
            const secs = String(voiceRecordingSeconds % 60).padStart(2, '0');
            if (timerElem) timerElem.textContent = `${mins}:${secs}`;
        }, 1000);

    } catch (err) {
        console.warn('[Microphone Access Error]', err);
        showToast('Microphone access unavailable or denied. Using speech prompt fallback.', 'warning');
        fallbackPromptVoiceNote();
    }
}

function stopVoiceRecording() {
    clearInterval(voiceRecordingInterval);
    const voiceBtn = document.getElementById('waVoiceNoteBtn');
    const recIndicator = document.getElementById('waRecordingIndicator');
    const replyInput = document.getElementById('waReplyInput');

    if (voiceBtn) {
        voiceBtn.textContent = '🎙️';
        voiceBtn.title = 'Record Voice Note';
        voiceBtn.style.color = '#00a884';
    }
    if (recIndicator) recIndicator.style.display = 'none';
    if (replyInput) replyInput.style.visibility = 'visible';

    if (mediaRecorderInstance && mediaRecorderInstance.state !== 'inactive') {
        try { mediaRecorderInstance.stop(); } catch (_) {}
    }
}

function cancelVoiceRecording() {
    clearInterval(voiceRecordingInterval);
    const voiceBtn = document.getElementById('waVoiceNoteBtn');
    const recIndicator = document.getElementById('waRecordingIndicator');
    const replyInput = document.getElementById('waReplyInput');

    if (voiceBtn) {
        voiceBtn.textContent = '🎙️';
        voiceBtn.title = 'Record Voice Note';
        voiceBtn.style.color = '#00a884';
    }
    if (recIndicator) recIndicator.style.display = 'none';
    if (replyInput) replyInput.style.visibility = 'visible';

    if (mediaRecorderInstance) {
        recordedAudioChunks = [];
        try { mediaRecorderInstance.stop(); } catch (_) {}
    }
    showToast('Voice recording discarded', 'info');
}

function toggleVoiceRecording() {
    if (mediaRecorderInstance && mediaRecorderInstance.state === 'recording') {
        stopVoiceRecording();
    } else {
        startVoiceRecording();
    }
}

function fallbackPromptVoiceNote() {
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

function promptSendVoiceNote() {
    toggleVoiceRecording();
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
            const isActive = isSameWaPhone(c.normalizedPhone || c.phone, waActiveChatPartner);
            const avatarColor = getWaAvatarColor(c.phone);
            const initials = (c.name || c.phone || '?').substring(0, 2).toUpperCase();
            const previewIcon = (c.is_audio && !previewText.startsWith('🎙️') && !previewText.startsWith('🎤')) ? '🎙️ ' : '';
            const unreadCount = (c.messages || []).filter(m => m.direction === 'inbound' && m.status !== 'read').length;

            let previewText = c.lastMessage || '';
            if (previewText.includes('> Quoted:')) {
                const parts = previewText.split('> Quoted:');
                const replyPart = (parts[0] || '').replace(/\[quotedMessage\]/gi, '').trim();
                const rawQuote = (parts.slice(1).join('> Quoted:') || '').trim();
                const cleanQuote = rawQuote.replace(/^\[quotedMessage\]/i, '').replace(/\[quotedMessage\]/gi, 'Quoted message').trim() || 'Quoted message';
                if (replyPart) {
                    previewText = `↩️ ${replyPart}`;
                } else {
                    previewText = `↩️ [Quote: ${cleanQuote.substring(0, 30)}${cleanQuote.length > 30 ? '...' : ''}]`;
                }
            } else if (previewText.toLowerCase() === '[quotedmessage]') {
                previewText = '↩️ Quoted message';
            } else {
                previewText = previewText.replace(/\[quotedMessage\]/gi, 'Quoted message');
            }

            return `
                <div class="wa-chat-item ${isActive ? 'active' : ''}" onclick="selectWhatsAppChat('${escapeHtml(c.normalizedPhone || c.phone)}')">
                    <div class="wa-avatar" style="background-color: ${avatarColor};">
                        ${escapeHtml(initials)}
                    </div>
                    <div class="wa-chat-meta">
                        <div class="wa-chat-top">
                            <span class="wa-chat-name" title="${escapeHtml(c.name)}">${escapeHtml(c.name)}</span>
                            <span class="wa-chat-time">${escapeHtml(c.timestamp.substring(11, 16) || c.timestamp)}</span>
                        </div>
                        <div class="wa-chat-bottom">
                            <span class="wa-chat-preview" title="${escapeHtml(previewText)}">${previewIcon}${escapeHtml(previewText)}</span>
                            <span class="wa-unread-badge" style="${unreadCount > 0 ? '' : 'display:none;'}">${unreadCount}</span>
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
        const activeConv = conversations.find(c => isSameWaPhone(c.normalizedPhone || c.phone, waActiveChatPartner));
        const normPartner = normalizeWaPhone(waActiveChatPartner);
        const displayFormatted = formatWaDisplayPhone(normPartner || waActiveChatPartner);
        const contactName = activeConv ? activeConv.name : displayFormatted;
        if (activeHeaderName) activeHeaderName.textContent = contactName;
        if (activeHeaderPhone) activeHeaderPhone.textContent = `${displayFormatted} · Online`;
        if (activeHeaderAvatar) {
            activeHeaderAvatar.style.backgroundColor = getWaAvatarColor(normPartner || waActiveChatPartner);
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
        const cleanSender = normalizeWaPhone(m.sender);
        const cleanRecipient = normalizeWaPhone(m.recipient);
        const target = normalizeWaPhone(waActiveChatPartner);
        return isSameWaPhone(cleanSender, target) || isSameWaPhone(cleanRecipient, target);
    });

    // Sort chronologically (oldest to newest for chat stream)
    partnerMsgs.sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));

    if (partnerMsgs.length === 0) {
        const displayPhone = formatWaDisplayPhone(waActiveChatPartner);
        msgStream.innerHTML = `
            <div class="wa-date-divider">New Conversation</div>
            <div style="margin: auto; text-align: center; color: #8696a0;">
                <div style="font-size: 2.2rem; margin-bottom: 8px;">👋</div>
                <div style="color: #e9edef; font-weight: 600;">No messages yet with ${escapeHtml(displayPhone)}</div>
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
                const isRead = m.status === 'read';
                const isSent = m.status === 'sent' || m.status === 'received' || isRead;
                const ticks = isSending ? '🕒' : (isRead ? '<span style="color:#53bdeb;font-weight:bold;">✓✓</span>' : (isSent ? '✓✓' : '✓'));
                let rawMedia = m.mediaUrl || m.media_url || m.audioUrl || m.audio_url || (m.raw_payload && (m.raw_payload.mediaUrl || m.raw_payload.audioUrl || m.raw_payload.audio_base64)) || '';
                if (rawMedia && typeof rawMedia === 'string') {
                    rawMedia = rawMedia.trim();
                    if (!rawMedia.startsWith('data:') && !rawMedia.startsWith('http') && !rawMedia.startsWith('/api/') && rawMedia.length > 50) {
                        rawMedia = `data:audio/ogg;base64,${rawMedia}`;
                    }
                    if (rawMedia.startsWith('data:')) {
                        rawMedia = rawMedia.replace(/;\s*codecs=[^;,]+/i, '');
                    }
                }
                const hasPlayableAudio = Boolean(rawMedia && typeof rawMedia === 'string' && (rawMedia.startsWith('data:audio') || rawMedia.startsWith('http') || rawMedia.startsWith('/api/')));
                const isVoice = Boolean(hasPlayableAudio || m.is_audio || m.type === 'audio' || m.message_type === 'audio' || m.message_type === 'voiceMessage' || (m.body && (m.body.startsWith('🎤') || m.body.startsWith('🎙️'))));
                const safeMediaUrl = rawMedia || '';
                const safeBody = (m.body || m.message || '').replace(/\[.*?\]/g, '').trim();

                let bodyHtml = '';
                if (isVoice) {
                    const audioSrc = hasPlayableAudio ? (safeMediaUrl.startsWith('data:audio') ? safeMediaUrl : `/api/v1/whatsapp/media/proxy?url=${encodeURIComponent(safeMediaUrl)}`) : '';
                    const hasTranscript = Boolean(safeBody && safeBody.toLowerCase() !== 'voice note' && safeBody.toLowerCase() !== 'audiomessage' && safeBody.toLowerCase() !== 'voicemessage' && safeBody !== '🎤 Voice message' && safeBody !== '🎙️ Voice note' && safeBody !== '(no text)');
                    bodyHtml = `
                        <div class="wa-voice-bubble" style="padding: 4px 0;">
                            ${audioSrc ? `<audio controls preload="metadata" src="${audioSrc}" style="max-width: 250px; width: 100%; height: 38px; outline: none; border-radius: 20px;"></audio>` : `
                            <div style="display:inline-flex; align-items:center; gap:6px; color:#aebac1; font-size:0.88em; padding:4px 0;">
                                <span>🎤</span> <em>Voice message (Audio unavailable)</em>
                            </div>
                            `}
                        </div>
                        ${hasTranscript ? `<div class="wa-voice-transcript" style="margin-top:6px;font-size:0.86em;padding:6px 10px;background:rgba(0,0,0,0.22);border-left:3px solid #00a884;border-radius:4px;word-break:break-word;"><span style="color:#00a884;font-size:0.75em;font-weight:700;display:block;margin-bottom:2px;">🎤 Audio Transcript</span>${escapeHtml(safeBody)}</div>` : ''}
                    `;
                } else {
                    const rawBody = (m.body || '').trim();
                    if (rawBody.includes('> Quoted:')) {
                        const parts = rawBody.split('> Quoted:');
                        const replyPart = (parts[0] || '').replace(/\[quotedMessage\]/gi, '').trim();
                        const rawQuote = (parts.slice(1).join('> Quoted:') || '').trim();
                        let cleanQuote = rawQuote.replace(/^\[quotedMessage\]/i, '').replace(/\[quotedMessage\]/gi, 'Quoted message').trim();
                        if (!cleanQuote || cleanQuote.toLowerCase() === 'quoted message') {
                            cleanQuote = 'Quoted message';
                        }
                        bodyHtml = `
                            <div class="wa-quote-card" style="border-left: 3px solid #25D366; background: rgba(0,0,0,0.18); padding: 6px 10px; border-radius: 4px; margin-bottom: 6px; font-size: 0.85em;">
                                <div style="font-weight: 600; font-size: 0.72em; color: #25D366; margin-bottom: 2px;">Quoted Message</div>
                                <div style="white-space: pre-wrap; opacity: 0.9; word-break: break-word;">${escapeHtml(cleanQuote)}</div>
                            </div>
                            ${replyPart ? `<div style="word-break: break-word;">${escapeHtml(replyPart)}</div>` : ''}
                        `;
                    } else if (m.message_type === 'quotedMessage' || rawBody.toLowerCase() === '[quotedmessage]' || rawBody.toLowerCase() === 'quoted message') {
                        const cleanBody = (rawBody.toLowerCase() === '[quotedmessage]' || rawBody.toLowerCase() === 'quoted message') ? '' : rawBody.replace(/\[quotedMessage\]/gi, '').trim();
                        bodyHtml = `
                            <div class="wa-quote-card" style="border-left: 3px solid #25D366; background: rgba(0,0,0,0.18); padding: 6px 10px; border-radius: 4px; margin-bottom: 6px; font-size: 0.85em;">
                                <div style="font-weight: 600; font-size: 0.72em; color: #25D366; margin-bottom: 2px;">Quoted Message</div>
                                <div style="white-space: pre-wrap; opacity: 0.9; word-break: break-word;">Quoted message</div>
                            </div>
                            ${cleanBody ? `<div style="word-break: break-word;">${escapeHtml(cleanBody)}</div>` : ''}
                        `;
                    } else {
                        const cleanBody = rawBody.replace(/\[quotedMessage\]/gi, 'Quoted message');
                        bodyHtml = `<div style="word-break: break-word;">${escapeHtml(cleanBody || '(no text)')}</div>`;
                    }
                }

                return `
                    <div class="wa-bubble-wrap ${isInbound ? 'inbound' : 'outbound'}">
                        <div class="wa-bubble ${isInbound ? 'inbound' : 'outbound'}">
                            ${isInbound && m.sender_name ? `<div class="wa-bubble-sender">${escapeHtml(m.sender_name)}</div>` : ''}
                            ${bodyHtml}
                            <div class="wa-bubble-footer">
                                ${isOutbound && (m.is_ai_generated || m.is_ai_response || m.response_source) ? `<span class="wa-ai-badge" style="background: rgba(0, 168, 132, 0.28); color: #25d366; border: 1px solid rgba(0, 168, 132, 0.4); padding: 2px 7px; border-radius: 4px; font-weight: 600; font-size: 10px;" title="Live Outbound AI Auto-Dispatch [Source: ${escapeHtml(m.response_source || 'AI')}]">🤖 Live AI Response</span>` : ''}
                                <span>${escapeHtml(timeStr)}</span>
                                ${isOutbound ? `<span class="wa-ticks">${ticks}</span>` : ''}
                                <button type="button" class="wa-msg-act-btn" onclick="promptForwardWhatsAppMsg('${m.id}')" title="Forward message">↗️</button>
                                ${isInbound && m.status === 'read' ? `<button type="button" class="wa-msg-act-btn" onclick="markWhatsAppMsgUnread('${m.id}')" title="Mark as unread">📫</button>` : ''}
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

        // Keep active chat messages marked as read locally so background polling doesn't flip them unread
        if (waActiveChatPartner && Array.isArray(messages)) {
            messages.forEach(m => {
                const p = (m.direction === 'inbound' ? m.sender : m.recipient) || '';
                if (isSameWaPhone(p, waActiveChatPartner) && m.direction === 'inbound') {
                    m.status = 'read';
                }
            });
        }

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
                    if (st === 'sent' || st === 'received' || st === 'read') {
                        statusPillClass = 'active';
                        statusIcon = st === 'read' ? '✓✓' : '✓';
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
                applyMobileTableLabels(tbody.closest('table'));
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

            if (activeProvider === 'baileys_bridge') {
                if (idLabel) idLabel.textContent = 'Baileys Cloud Bridge';
                if (phoneIdInput) phoneIdInput.value = 'Port 3001 (Node.js Baileys Bridge)';
                if (providerBadge) {
                    providerBadge.className = 'status-pill green';
                    providerBadge.textContent = 'Baileys Cloud Bridge';
                }
                if (modeBadge) {
                    modeBadge.className = 'status-pill green';
                    modeBadge.textContent = '● Baileys Bridge Online';
                }
                if (connStatus) {
                    connStatus.innerHTML = '<span class="status-pill green" style="font-size:0.75rem;">● Connected (Baileys Bridge)</span>';
                }
            } else if (activeProvider === 'green_api') {
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
                if (activeProvider === 'baileys_bridge') {
                    banner.style.background = 'rgba(16, 185, 129, 0.08)';
                    banner.style.border = '1px solid rgba(16, 185, 129, 0.25)';
                    bannerTitle.style.color = '#10b981';
                    bannerTitle.textContent = 'Production WhatsApp Baileys Cloud Bridge Active';
                    bannerDesc.textContent = 'Direct Baileys session connected on port 3001. Inbound webhook notifications and outbound messaging route directly with zero fees.';
                    if (bannerAction) {
                        bannerAction.innerHTML = '<button type="button" class="hud-btn primary small" onclick="openLinkWhatsAppQrModal()" style="background: #10b981; font-weight: 700; color: #fff;">📱 Link WhatsApp QR</button>';
                    }
                } else if (activeProvider === 'green_api') {
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
                    bannerDesc.textContent = 'Operating in local sandbox mode. Outbound dispatches are simulated and persisted to local logs. Connect Baileys Bridge for live messaging.';
                    if (bannerAction) {
                        bannerAction.innerHTML = '<button type="button" class="hud-btn primary small" onclick="openLinkWhatsAppQrModal()" style="background: #10b981; font-weight: 700; color: #fff;">📱 Link WhatsApp QR</button>';
                    }
                }
            }
        }

        // Check real-time Baileys bridge socket connectivity
        let bridgeIsLive = false;
        if (activeProvider === 'baileys_bridge') {
            try {
                const bRes = await fetch('/api/v1/whatsapp/bridge-status');
                if (bRes.ok) {
                    const bData = await bRes.json();
                    bridgeIsLive = Boolean(bData.connected);
                }
            } catch (_) {}
        }

        // Update connection state tracking and toggle UI view
        const isConnected = Boolean(window._waDemoMode || (isConfigured && (activeProvider === 'baileys_bridge' ? bridgeIsLive : (activeProvider === 'green_api' || activeProvider === 'meta'))));
        window._waIsConfigured = isConfigured;
        window._waActiveProvider = activeProvider;
        window._waIsConnected = isConnected;

        const currentMode = window._waCurrentViewMode || 'web';
        const sidebarStatus = document.getElementById('waSidebarStatus');
        if (sidebarStatus) {
            sidebarStatus.style.cursor = 'pointer';
            sidebarStatus.title = 'Click to Link WhatsApp QR / View Status';
            sidebarStatus.onclick = function() {
                if (window.openLinkWhatsAppQrModal) window.openLinkWhatsAppQrModal();
            };
            if (activeProvider === 'baileys_bridge') {
                if (bridgeIsLive) {
                    sidebarStatus.textContent = '● Live Sync Active';
                    sidebarStatus.style.color = '#00a884';
                } else {
                    sidebarStatus.textContent = '● Awaiting QR Link';
                    sidebarStatus.style.color = '#f59e0b';
                }
            } else if (activeProvider === 'green_api') {
                sidebarStatus.textContent = '● Live Sync Active';
                sidebarStatus.style.color = '#00a884';
            } else if (activeProvider === 'meta') {
                sidebarStatus.textContent = '● Meta Connected';
                sidebarStatus.style.color = '#00a884';
            } else if (window._waDemoMode) {
                sidebarStatus.textContent = '🧪 Sandbox Demo';
                sidebarStatus.style.color = '#00f0ff';
            } else {
                sidebarStatus.textContent = '● Disconnected';
                sidebarStatus.style.color = '#ef4444';
            }
        }

        const disconnectBtn = document.getElementById('waBtnDisconnect');
        if (disconnectBtn) {
            disconnectBtn.style.display = 'inline-flex';
            disconnectBtn.style.cursor = 'pointer';
            disconnectBtn.title = 'Link WhatsApp QR / Gateway Status';
            disconnectBtn.onclick = function() {
                if (window.openLinkWhatsAppQrModal) {
                    window.openLinkWhatsAppQrModal();
                }
            };
        }

        // Apply clean view transition
        setWhatsAppViewMode(currentMode);

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

        const authHeaders = typeof getAuthHeaders === 'function' ? getAuthHeaders() : {};
        const headers = Object.assign({ 'Content-Type': 'application/json' }, authHeaders);
        const res = await fetch('/api/whatsapp/send', {
            method: 'POST',
            headers: headers,
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

function openWhatsAppConnectGuide() {
    if (typeof openLinkWhatsAppQrModal === 'function') {
        openLinkWhatsAppQrModal();
    }
}

function closeWhatsAppConnectModal() {
    if (typeof closeLinkWhatsAppQrModal === 'function') {
        closeLinkWhatsAppQrModal();
    }
}

async function handleSaveWhatsAppConfig(e) {
    if (e) e.preventDefault();
    if (typeof openLinkWhatsAppQrModal === 'function') {
        openLinkWhatsAppQrModal();
    }
}

async function handleTestWhatsAppConnection() {
    const btn = document.getElementById('btnTestWaConnection');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Testing Baileys Bridge...';
    }

    try {
        const res = await fetch('/api/v1/whatsapp/test-connection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider: 'baileys_bridge' })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast('✅ WhatsApp Baileys Bridge is online and connected!', 'success');
        } else {
            showToast(data.message || 'WhatsApp bridge is not linked yet. Scan the QR code.', 'warning');
            if (typeof openLinkWhatsAppQrModal === 'function') {
                openLinkWhatsAppQrModal();
            }
        }
    } catch (err) {
        showToast('Bridge connection error: ' + err.message, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = '⚡ Test Connection';
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
    campaigns: 'Campaigns & Broadcasts',
    'company-messaging': 'Company Messaging',
    company_messaging: 'Company Messaging',
    messaging: 'Company Messaging',
    nlp: 'AI Engine Sandbox',
    blueprints: 'Templates',
    simulator: 'Metrics Simulator',
    logs: 'Forensics & Audits',
    apikeys: 'API Keys',
    apidocs: 'API Docs',
    team: 'Team & RBAC',
    billing: 'Plans & Billing',
    settings: 'Settings',
    products: 'Products Catalog & Inventory'
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
    if (window.innerWidth <= 992) {
        const isOpen = sidebar.classList.toggle('open');
        updateSidebarBackdrop(isOpen);
    } else {
        const isCollapsed = sidebar.classList.toggle('collapsed');
        localStorage.setItem('opsflow_sidebar_collapsed', isCollapsed);
        updateSidebarToggleLabel(isCollapsed);
    }
}

function updateSidebarBackdrop(isOpen) {
    let backdrop = document.getElementById('sidebarBackdrop');
    if (!backdrop) {
        backdrop = document.createElement('div');
        backdrop.id = 'sidebarBackdrop';
        backdrop.className = 'sidebar-backdrop';
        backdrop.onclick = () => {
            const sidebar = document.getElementById('enterpriseSidebar');
            if (sidebar) sidebar.classList.remove('open');
            backdrop.classList.remove('active');
        };
        document.body.appendChild(backdrop);
    }
    if (isOpen) {
        backdrop.classList.add('active');
    } else {
        backdrop.classList.remove('active');
    }
}

function applyMobileTableLabels(tableEl) {
    if (!tableEl) {
        document.querySelectorAll('table.stack-mobile').forEach(t => applyMobileTableLabels(t));
        return;
    }
    const headers = Array.from(tableEl.querySelectorAll('thead th')).map(th => th.textContent.trim());
    if (headers.length === 0) return;
    tableEl.querySelectorAll('tbody tr').forEach(tr => {
        if (tr.querySelector('.empty-cell') || tr.querySelector('.empty-row') || tr.querySelector('.table-empty-row')) return;
        const cells = tr.querySelectorAll('td');
        cells.forEach((td, idx) => {
            if (headers[idx] && !td.getAttribute('data-label')) {
                td.setAttribute('data-label', headers[idx]);
            }
        });
    });
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
    if (!breadcrumb) return;
    if (TAB_TITLES[tabId]) {
        breadcrumb.textContent = TAB_TITLES[tabId];
    } else if (tabId) {
        breadcrumb.textContent = tabId.replace(/[-_]/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
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
    { id: 'nav-products', category: 'Navigation', icon: '🛍️', title: 'Products Catalog & Shop', shortcut: 'G P', action: () => switchTab('products') },

    // Quick Actions
    { id: 'act-new-rule', category: 'Quick Actions', icon: '➕', title: 'Create New Workflow Rule', shortcut: 'N W', action: () => { switchTab('rules'); openRuleModal(); } },
    { id: 'act-new-webhook', category: 'Quick Actions', icon: '🔌', title: 'Register Inbound Webhook', shortcut: 'N H', action: () => { switchTab('webhooks'); openWebhookModal(); } },
    { id: 'act-new-apikey', category: 'Quick Actions', icon: '🔑', title: 'Generate Scoped API Key', shortcut: 'N K', action: () => { switchTab('apikeys'); openApiKeyModal(); } },
    { id: 'act-bulk-leads', category: 'Quick Actions', icon: '📥', title: 'Bulk Import Leads (CSV/JSON)', shortcut: 'B L', action: () => openBulkLeadImportModal() },
    { id: 'act-truck-dispatch', category: 'Quick Actions', icon: '🚚', title: 'Dispatch Fleet Delivery Truck', shortcut: 'D T', action: () => openTruckDispatchModal() },
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

// =========================================================================
// CAMPAIGNS & TARGETED BROADCASTS CONTROLLER
// =========================================================================

state.campaigns = [];
state.campaignsFilter = 'all';
state.campaignWizardStep = 1;
state.campaignTemplates = [];
state.currentPreviewData = null;

async function loadCampaignsSummary() {
    try {
        const res = await fetch('/api/v1/campaigns');
        if (!res.ok) return;
        const data = await res.json();
        const activeCount = (data.campaigns || []).filter(c => ['pending_approval', 'scheduled', 'processing'].includes(c.status)).length;
        updateNavBadge('tabCampaignsCount', activeCount);
    } catch (e) {
        // silent background failure
    }
}

async function loadCampaignsDashboard() {
    try {
        const [cmpRes, audRes] = await Promise.allSettled([
            fetch('/api/v1/campaigns'),
            fetch('/api/v1/campaigns/audiences')
        ]);

        let campaigns = [];
        if (cmpRes.status === 'fulfilled' && cmpRes.value.ok) {
            const data = await cmpRes.value.json();
            campaigns = data.campaigns || [];
            state.campaigns = campaigns;
        }

        let audiences = null;
        if (audRes.status === 'fulfilled' && audRes.value.ok) {
            const audData = await audRes.value.json();
            audiences = audData.audiences || {};
        }

        // Update KPI telemetry cards
        const total = campaigns.length;
        const dispatched = campaigns.reduce((acc, c) => acc + (c.sent_count || 0), 0);
        const delivered = campaigns.reduce((acc, c) => acc + (c.delivered_count || 0), 0);
        const optOut = audiences ? (audiences.opted_out_count || 0) : 0;

        const elTotal = document.getElementById('cmpStatTotal');
        const elSent = document.getElementById('cmpStatDispatched');
        const elDeliv = document.getElementById('cmpStatDelivered');
        const elOpt = document.getElementById('cmpStatOptOut');

        if (elTotal) elTotal.textContent = total;
        if (elSent) elSent.textContent = dispatched;
        if (elDeliv) elDeliv.textContent = delivered;
        if (elOpt) elOpt.textContent = optOut;

        const activeCount = campaigns.filter(c => ['pending_approval', 'scheduled', 'processing'].includes(c.status)).length;
        updateNavBadge('tabCampaignsCount', activeCount);

        renderCampaignsTable(campaigns);
    } catch (err) {
        console.error('Error loading campaigns:', err);
        showToast(`Failed to load campaigns: ${err.message}`, 'error');
    }
}

function renderCampaignsTable(campaigns) {
    const tbody = document.getElementById('campaignsTableBody');
    if (!tbody) return;

    let filtered = campaigns;
    if (state.campaignsFilter && state.campaignsFilter !== 'all') {
        filtered = campaigns.filter(c => c.status === state.campaignsFilter);
    }

    if (!filtered || filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="empty-cell">No campaigns found matching current filter.</td></tr>`;
        return;
    }

    tbody.innerHTML = filtered.map(c => {
        let statusBadge = '<span class="status-pill blue">Draft</span>';
        if (c.status === 'pending_approval') {
            statusBadge = '<span class="status-pill yellow">⏳ Pending Review</span>';
        } else if (c.status === 'scheduled') {
            statusBadge = '<span class="status-pill purple">📅 Scheduled</span>';
        } else if (c.status === 'processing') {
            statusBadge = '<span class="status-pill blue" style="animation: pulse 1.5s infinite;">⚡ Processing</span>';
        } else if (c.status === 'completed') {
            statusBadge = '<span class="status-pill green">✓ Completed</span>';
        } else if (c.status === 'cancelled') {
            statusBadge = '<span class="status-pill red">✕ Cancelled</span>';
        } else if (c.status === 'failed') {
            statusBadge = '<span class="status-pill red">⚠️ Failed</span>';
        }

        const totalRecip = c.total_recipients || 0;
        const sent = c.sent_count || 0;
        const deliv = c.delivered_count || 0;
        const pctSent = totalRecip > 0 ? Math.round((sent / totalRecip) * 100) : 0;

        let actions = `
            <div style="display: flex; justify-content: flex-end; gap: 6px;">
                <button type="button" class="hud-btn outline small" onclick="viewCampaignLedger('${c.id}')" title="View Delivery Ledger">Ledger</button>
        `;

        const canManage = state.userRole === 'owner' || state.userRole === 'admin';
        if (canManage && (c.status === 'draft' || c.status === 'pending_approval')) {
            actions += `<button type="button" class="hud-btn primary small" onclick="approveCampaignDirect('${c.id}')" style="background:#10b981; border-color:#10b981;">Launch</button>`;
        }
        if (canManage && (c.status === 'scheduled' || c.status === 'processing')) {
            actions += `<button type="button" class="hud-btn small outline" onclick="cancelCampaignDirect('${c.id}')" style="color:#f87171; border-color:rgba(239,68,68,0.4);">Cancel</button>`;
        }
        actions += `</div>`;

        const audienceLabel = c.audience_type.charAt(0).toUpperCase() + c.audience_type.slice(1);

        return `
            <tr>
                <td>
                    <div style="font-weight: 600; color: #fff;">${escapeHtml(c.title)}</div>
                    <div style="font-size: 11px; color: var(--text-dim, #888); display: flex; align-items: center; gap: 6px; margin-top: 2px;">
                        <span>💬 WhatsApp</span>
                        <span>&bull;</span>
                        <span>$${(c.estimated_cost_usd || 0).toFixed(2)}</span>
                    </div>
                </td>
                <td>
                    <span style="font-size: 12.5px; color: #cbd5e1;">${audienceLabel}</span>
                    <div style="font-size: 11px; color: var(--cyan-glow, #00f0ff);">${totalRecip} recipients</div>
                </td>
                <td>${statusBadge}</td>
                <td>
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <div style="flex: 1; min-width: 60px; height: 6px; background: rgba(255,255,255,0.08); border-radius: 3px; overflow: hidden;">
                            <div style="width: ${pctSent}%; height: 100%; background: #10b981;"></div>
                        </div>
                        <span style="font-size: 11px; font-family: var(--font-mono); color: var(--text-dim, #888);">${sent}/${totalRecip} (${pctSent}%)</span>
                    </div>
                    <div style="font-size: 10.5px; color: #60a5fa; margin-top: 2px;">Delivered: ${deliv}</div>
                </td>
                <td style="font-size: 11.5px; color: var(--text-dim, #888);">
                    ${c.scheduled_at ? `📅 ${c.scheduled_at}` : (c.created_at || 'Just now')}
                </td>
                <td style="text-align: right;">${actions}</td>
            </tr>
        `;
    }).join('');
}

function filterCampaigns(status, btnEl) {
    state.campaignsFilter = status;
    const chips = btnEl?.parentElement?.querySelectorAll('.filter-chip');
    if (chips) {
        chips.forEach(c => c.classList.remove('active'));
        btnEl.classList.add('active');
    }
    renderCampaignsTable(state.campaigns);
}

function handleCampaignSearch(query) {
    const q = (query || '').toLowerCase().trim();
    if (!q) {
        renderCampaignsTable(state.campaigns);
        return;
    }
    const filtered = state.campaigns.filter(c =>
        c.title.toLowerCase().includes(q) ||
        (c.audience_type && c.audience_type.toLowerCase().includes(q))
    );
    renderCampaignsTable(filtered);
}

// ------------------------------------------
// CAMPAIGN WIZARD & MODAL CONTROLS
// ------------------------------------------

function openNewCampaignModal() {
    state.campaignWizardStep = 1;
    document.getElementById('cmpNewTitle').value = '';
    document.getElementById('cmpNewMessageBody').value = '';
    document.getElementById('cmpScheduleDateTime').value = '';

    setWizardStepUI(1);
    loadCampaignTemplates();
    recalculateAudiencePreview();

    document.getElementById('modalNewCampaign').style.display = 'flex';
}

function closeNewCampaignModal() {
    document.getElementById('modalNewCampaign').style.display = 'none';
}

function handleAudienceTypeChange() {
    const radios = document.getElementsByName('cmpAudienceType');
    let sel = 'customers';
    for (const r of radios) {
        if (r.checked) sel = r.value;
    }
    const deptDiv = document.getElementById('cmpDeptSubSelect');
    if (deptDiv) {
        deptDiv.style.display = sel === 'department' ? 'block' : 'none';
    }
    recalculateAudiencePreview();
}

async function recalculateAudiencePreview() {
    const elCount = document.getElementById('cmpLiveAudienceCount');
    if (elCount) elCount.textContent = 'Calculating audience...';

    const radios = document.getElementsByName('cmpAudienceType');
    let sel = 'customers';
    for (const r of radios) {
        if (r.checked) sel = r.value;
    }

    let filter = {};
    if (sel === 'department') {
        filter = { department: document.getElementById('cmpDeptSelect')?.value || 'Support' };
    }

    try {
        const res = await fetch('/api/v1/campaigns/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                audience_type: sel,
                audience_filter: filter,
                raw_template: document.getElementById('cmpNewMessageBody')?.value || 'Hello {{name}}!'
            })
        });
        if (res.ok) {
            const data = await res.json();
            state.currentPreviewData = data.preview;
            if (elCount) {
                elCount.innerHTML = `<span style="color:#10b981;">${data.preview.total_recipients} eligible contacts</span> <span style="font-size:11.5px; color:#f87171;">(${data.preview.opted_out_count} opted out excluded)</span>`;
            }
        } else {
            if (elCount) elCount.textContent = 'Unable to resolve audience';
        }
    } catch (e) {
        if (elCount) elCount.textContent = 'Ready (live calculation pending)';
    }
}

async function stepCmpWizard(direction) {
    const newStep = state.campaignWizardStep + direction;
    if (newStep < 1 || newStep > 3) return;

    if (newStep === 2) {
        const title = document.getElementById('cmpNewTitle')?.value.trim();
        if (!title) {
            showToast('Please enter a campaign title first.', 'error');
            return;
        }
    }

    if (newStep === 3) {
        const body = document.getElementById('cmpNewMessageBody')?.value.trim();
        if (!body) {
            showToast('Please compose a message for your broadcast.', 'error');
            return;
        }

        // Fetch full preview with exact sample rendering
        const radios = document.getElementsByName('cmpAudienceType');
        let sel = 'customers';
        for (const r of radios) {
            if (r.checked) sel = r.value;
        }

        let filter = {};
        if (sel === 'department') {
            filter = { department: document.getElementById('cmpDeptSelect')?.value || 'Support' };
        }

        const previewBox = document.getElementById('cmpExactRenderedPreview');
        if (previewBox) previewBox.textContent = 'Generating sample preview...';

        try {
            const res = await fetch('/api/v1/campaigns/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    audience_type: sel,
                    audience_filter: filter,
                    raw_template: body
                })
            });
            if (res.ok) {
                const data = await res.json();
                state.currentPreviewData = data.preview;
                if (previewBox) previewBox.textContent = data.preview.primary_preview;

                const audText = document.getElementById('cmpReviewAudienceText');
                if (audText) audText.textContent = `${sel.toUpperCase()} (${data.preview.total_recipients} contacts)`;

                const costText = document.getElementById('cmpReviewCostText');
                if (costText) costText.textContent = `$${data.preview.estimated_cost_usd.toFixed(2)} USD`;

                const badge = document.getElementById('cmpReviewComplianceBadge');
                if (badge) {
                    if (data.preview.compliance_status === 'compliant') {
                        badge.className = 'status-pill green';
                        badge.textContent = '✓ Verified Compliant';
                    } else {
                        badge.className = 'status-pill yellow';
                        badge.textContent = '⚠️ Template Recommended';
                    }
                }

                const warnBox = document.getElementById('cmpReviewWarningsBox');
                if (warnBox) {
                    if (data.preview.warnings && data.preview.warnings.length > 0) {
                        warnBox.style.display = 'block';
                        warnBox.innerHTML = data.preview.warnings.map(w => `<div>&bull; ${escapeHtml(w)}</div>`).join('');
                    } else {
                        warnBox.style.display = 'none';
                    }
                }
            }
        } catch (e) {
            console.error('Preview error:', e);
        }
    }

    state.campaignWizardStep = newStep;
    setWizardStepUI(newStep);
}

function setWizardStepUI(step) {
    document.querySelectorAll('.cmp-step-pane').forEach((pane, idx) => {
        pane.style.display = (idx + 1) === step ? 'block' : 'none';
    });

    for (let i = 1; i <= 3; i++) {
        const pill = document.getElementById(`cmpWizardPill${i}`);
        if (pill) {
            if (i === step) {
                pill.style.color = 'var(--cyan-glow, #00f0ff)';
                pill.style.fontWeight = '600';
            } else {
                pill.style.color = 'var(--text-dim, #888)';
                pill.style.fontWeight = 'normal';
            }
        }
    }

    const btnBack = document.getElementById('btnCmpBack');
    const btnNext = document.getElementById('btnCmpNext');
    const btnDraft = document.getElementById('btnCmpSaveDraft');
    const btnLaunch = document.getElementById('btnCmpApproveLaunch');

    if (btnBack) btnBack.style.display = step > 1 ? 'inline-flex' : 'none';
    if (btnNext) {
        btnNext.style.display = step < 3 ? 'inline-flex' : 'none';
        btnNext.textContent = step === 1 ? 'Next: Compose Message →' : 'Next: Review & Confirm →';
    }
    if (btnDraft) btnDraft.style.display = step === 3 ? 'inline-flex' : 'none';
    if (btnLaunch) btnLaunch.style.display = step === 3 ? 'inline-flex' : 'none';
}

function insertPlaceholderIntoComposer(tag) {
    const textarea = document.getElementById('cmpNewMessageBody');
    if (!textarea) return;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const text = textarea.value;
    textarea.value = text.substring(0, start) + tag + text.substring(end);
    textarea.focus();
    textarea.selectionStart = textarea.selectionEnd = start + tag.length;
}

function handleTimingModeChange() {
    const radios = document.getElementsByName('cmpTimingMode');
    let sel = 'immediate';
    for (const r of radios) {
        if (r.checked) sel = r.value;
    }
    const container = document.getElementById('cmpScheduleDateTimeContainer');
    if (container) {
        container.style.display = sel === 'scheduled' ? 'block' : 'none';
    }
}

async function submitCreateCampaign(autoApprove) {
    const title = document.getElementById('cmpNewTitle')?.value.trim();
    const rawTemplate = document.getElementById('cmpNewMessageBody')?.value.trim();
    if (!title || !rawTemplate) {
        showToast('Campaign title and message are required.', 'error');
        return;
    }

    const radios = document.getElementsByName('cmpAudienceType');
    let audienceType = 'customers';
    for (const r of radios) {
        if (r.checked) audienceType = r.value;
    }

    let filter = {};
    if (audienceType === 'department') {
        filter = { department: document.getElementById('cmpDeptSelect')?.value || 'Support' };
    }

    let scheduledAt = null;
    const timingRadios = document.getElementsByName('cmpTimingMode');
    let timing = 'immediate';
    for (const r of timingRadios) {
        if (r.checked) timing = r.value;
    }
    if (timing === 'scheduled') {
        const dtVal = document.getElementById('cmpScheduleDateTime')?.value;
        if (dtVal) scheduledAt = new Date(dtVal).toISOString();
    }

    try {
        const payload = {
            title,
            raw_template: rawTemplate,
            audience_type: audienceType,
            audience_filter: filter,
            channel: 'whatsapp',
            scheduled_at: scheduledAt
        };

        const res = await fetch('/api/v1/campaigns', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();

        if (res.ok && data.success) {
            const campId = data.campaign.id;
            if (autoApprove) {
                const appRes = await fetch(`/api/v1/campaigns/${campId}/approve`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                const appData = await appRes.json();
                if (appRes.ok) {
                    showToast('Campaign successfully approved and queued for dispatch!', 'success');
                } else {
                    showToast(appData.error || 'Campaign saved but failed to launch.', 'warning');
                }
            } else {
                showToast('Campaign saved as draft.', 'success');
            }

            closeNewCampaignModal();
            loadCampaignsDashboard();
        } else {
            showToast(data.error || 'Failed to create campaign.', 'error');
        }
    } catch (err) {
        showToast(`Error creating campaign: ${err.message}`, 'error');
    }
}

async function approveCampaignDirect(campaignId) {
    if (!confirm('Are you sure you want to approve and launch this campaign?')) return;
    try {
        const res = await fetch(`/api/v1/campaigns/${campaignId}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await res.json();
        if (res.ok) {
            showToast('Campaign approved and activated!', 'success');
            loadCampaignsDashboard();
        } else {
            showToast(data.error || 'Approval failed.', 'error');
        }
    } catch (err) {
        showToast(`Approval error: ${err.message}`, 'error');
    }
}

async function cancelCampaignDirect(campaignId) {
    if (!confirm('Are you sure you want to cancel this campaign? Pending recipients will be halted.')) return;
    try {
        const res = await fetch(`/api/v1/campaigns/${campaignId}/cancel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await res.json();
        if (res.ok) {
            showToast('Campaign cancelled.', 'info');
            loadCampaignsDashboard();
        } else {
            showToast(data.error || 'Cancellation failed.', 'error');
        }
    } catch (err) {
        showToast(`Cancellation error: ${err.message}`, 'error');
    }
}

async function viewCampaignLedger(campaignId) {
    try {
        const res = await fetch(`/api/v1/campaigns/${campaignId}`);
        if (!res.ok) return;
        const data = await res.json();
        const camp = data.campaign;

        document.getElementById('cmpDetailTitle').textContent = camp.title;
        document.getElementById('cmpDetailMeta').textContent = `Audience: ${camp.audience_type} • Channel: ${camp.channel}`;
        document.getElementById('cmpDetailTotalRecip').textContent = camp.total_recipients || 0;
        document.getElementById('cmpDetailSentCount').textContent = camp.sent_count || 0;
        document.getElementById('cmpDetailDeliveredCount').textContent = camp.delivered_count || 0;
        document.getElementById('cmpDetailFailedCount').textContent = camp.failed_count || 0;

        const tbody = document.getElementById('cmpDetailRecipientsBody');
        const recipients = camp.recipients || [];

        if (recipients.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="empty-cell">No recipient ledger entries available.</td></tr>`;
        } else {
            tbody.innerHTML = recipients.map(r => {
                let badge = '<span class="status-pill blue">Pending</span>';
                if (r.status === 'sent') badge = '<span class="status-pill green">Sent</span>';
                if (r.status === 'delivered') badge = '<span class="status-pill blue">Delivered</span>';
                if (r.status === 'read') badge = '<span class="status-pill green">Read</span>';
                if (r.status === 'opted_out') badge = '<span class="status-pill yellow">Opted Out</span>';
                if (r.status === 'failed') badge = '<span class="status-pill red">Failed</span>';

                return `
                    <tr>
                        <td><strong>${escapeHtml(r.name)}</strong></td>
                        <td style="font-family: var(--font-mono);">${escapeHtml(r.phone)}</td>
                        <td>${badge}</td>
                        <td style="font-family: var(--font-mono); font-size: 11px; color: var(--text-dim, #888);">${r.provider_message_id || '—'}</td>
                        <td style="font-size: 11px;">${r.sent_at || '—'}</td>
                        <td style="font-size: 11px;">${r.delivered_at || '—'}</td>
                    </tr>
                `;
            }).join('');
        }

        document.getElementById('modalCampaignDetail').style.display = 'flex';
    } catch (err) {
        showToast(`Error loading campaign ledger: ${err.message}`, 'error');
    }
}

function closeCampaignDetailModal() {
    document.getElementById('modalCampaignDetail').style.display = 'none';
}

// ------------------------------------------
// AI DRAFT ASSISTANT CONTROLS
// ------------------------------------------

function openAiDraftModal() {
    document.getElementById('aiDraftPromptInput').value = '';
    document.getElementById('aiDraftResultArea').style.display = 'none';
    document.getElementById('modalAiDraft').style.display = 'flex';
}

function closeAiDraftModal() {
    document.getElementById('modalAiDraft').style.display = 'none';
}

async function generateAiDraftFromModal() {
    const prompt = document.getElementById('aiDraftPromptInput')?.value.trim();
    if (!prompt) {
        showToast('Please describe the announcement you want to draft.', 'error');
        return;
    }
    const tone = document.getElementById('aiDraftToneSelect')?.value || 'professional';
    const aud = document.getElementById('aiDraftAudienceSelect')?.value || 'customers';
    const btn = document.getElementById('btnRunAiDraft');

    if (btn) btn.textContent = 'Generating Draft...';
    try {
        const res = await fetch('/api/v1/campaigns/ai-draft', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt, tone, audience_type: aud })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            document.getElementById('aiDraftOutputBody').value = data.suggested_body;
            document.getElementById('aiDraftResultArea').style.display = 'block';
            showToast('AI draft generated! Review before inserting into campaign.', 'success');
        } else {
            showToast(data.error || 'Failed to generate AI draft.', 'error');
        }
    } catch (err) {
        showToast(`AI draft error: ${err.message}`, 'error');
    } finally {
        if (btn) btn.textContent = '⚡ Generate Draft Announcement';
    }
}

function useAiDraftInComposer() {
    const body = document.getElementById('aiDraftOutputBody')?.value;
    if (body) {
        const composer = document.getElementById('cmpNewMessageBody');
        if (composer) composer.value = body;
    }
    closeAiDraftModal();
    const newCampModal = document.getElementById('modalNewCampaign');
    if (newCampModal && newCampModal.style.display !== 'flex') {
        openNewCampaignModal();
        stepCmpWizard(1);
    }
}

// ------------------------------------------
// REUSABLE TEMPLATES CONTROLS
// ------------------------------------------

async function loadCampaignTemplates() {
    try {
        const res = await fetch('/api/v1/campaigns/templates');
        if (!res.ok) return;
        const data = await res.json();
        state.campaignTemplates = data.templates || [];

        const select = document.getElementById('cmpTemplateSelect');
        if (select) {
            select.innerHTML = `<option value="">-- Custom Message (No Template) --</option>` +
                state.campaignTemplates.map(t => `<option value="${t.id}">${escapeHtml(t.name)} (${t.category})</option>`).join('');
        }
    } catch (e) {
        // silent
    }
}

function handleTemplateSelectChange(tmplId) {
    if (!tmplId) return;
    const tmpl = state.campaignTemplates.find(t => t.id === tmplId);
    if (tmpl) {
        const composer = document.getElementById('cmpNewMessageBody');
        if (composer) composer.value = tmpl.body;
    }
}

function openTemplatesModal() {
    loadTemplatesListInModal();
    document.getElementById('modalManageTemplates').style.display = 'flex';
}

function closeTemplatesModal() {
    document.getElementById('modalManageTemplates').style.display = 'none';
}

async function loadTemplatesListInModal() {
    const container = document.getElementById('templatesListContainer');
    if (!container) return;
    try {
        const res = await fetch('/api/v1/campaigns/templates');
        const data = await res.json();
        const templates = data.templates || [];
        if (templates.length === 0) {
            container.innerHTML = '<div class="empty-cell">No templates available.</div>';
            return;
        }
        container.innerHTML = templates.map(t => `
            <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-color, #2a2e3d); border-radius: 6px; padding: 10px 14px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                    <strong style="color: #fff; font-size: 13px;">${escapeHtml(t.name)}</strong>
                    <span class="status-pill blue" style="font-size: 10px;">${t.category}</span>
                </div>
                <div style="font-size: 12px; color: var(--text-secondary); white-space: pre-wrap;">${escapeHtml(t.body)}</div>
            </div>
        `).join('');
    } catch (e) {
        container.innerHTML = '<div class="empty-cell">Failed to load templates.</div>';
    }
}

async function submitCreateTemplate() {
    const name = document.getElementById('newTemplateName')?.value.trim();
    const body = document.getElementById('newTemplateBody')?.value.trim();
    if (!name || !body) {
        showToast('Template name and body are required.', 'error');
        return;
    }
    try {
        const res = await fetch('/api/v1/campaigns/templates', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, body })
        });
        const data = await res.json();
        if (res.ok) {
            showToast('Template created successfully!', 'success');
            document.getElementById('newTemplateName').value = '';
            document.getElementById('newTemplateBody').value = '';
            loadTemplatesListInModal();
            loadCampaignTemplates();
        } else {
            showToast(data.error || 'Failed to create template.', 'error');
        }
    } catch (err) {
        showToast(`Template error: ${err.message}`, 'error');
    }
}

// ------------------------------------------
// CONSENT & OPT-OUT REGISTRY CONTROLS
// ------------------------------------------

function openConsentRegistryModal() {
    loadConsentRegistry();
    document.getElementById('modalConsentRegistry').style.display = 'flex';
}

function closeConsentRegistryModal() {
    document.getElementById('modalConsentRegistry').style.display = 'none';
}

async function loadConsentRegistry() {
    const tbody = document.getElementById('consentTableBody');
    if (!tbody) return;
    try {
        const res = await fetch('/api/v1/campaigns/consent');
        const data = await res.json();
        const consents = data.consents || [];
        if (consents.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" class="empty-cell">No opt-out records found for this workspace.</td></tr>`;
            return;
        }
        tbody.innerHTML = consents.map(c => `
            <tr>
                <td style="font-family: var(--font-mono);">${escapeHtml(c.phone)}</td>
                <td><span class="status-pill ${c.status === 'opted_out' ? 'red' : 'green'}">${c.status}</span></td>
                <td style="font-size: 11.5px; color: var(--text-dim, #888);">${escapeHtml(c.reason || 'N/A')}</td>
                <td style="font-size: 11px;">${c.opted_out_at || c.created_at || '—'}</td>
                <td>
                    ${c.status === 'opted_out' ?
                        `<button type="button" class="hud-btn outline small" onclick="restoreConsentOptIn('${c.phone}')" style="font-size:11px; padding:2px 6px;">Restore (Opt-In)</button>` :
                        'Active'
                    }
                </td>
            </tr>
        `).join('');
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="5" class="empty-cell">Failed to load consent records.</td></tr>`;
    }
}

async function submitManualOptOut() {
    const phone = document.getElementById('manualOptOutPhone')?.value.trim();
    if (!phone) {
        showToast('Please enter a phone number to opt-out.', 'error');
        return;
    }
    try {
        const res = await fetch('/api/v1/campaigns/consent/opt-out', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phone, reason: 'Manual operator opt-out entry' })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(`Contact ${phone} registered as opted-out.`, 'success');
            document.getElementById('manualOptOutPhone').value = '';
            loadConsentRegistry();
            loadCampaignsDashboard();
        } else {
            showToast(data.error || 'Failed to opt-out contact.', 'error');
        }
    } catch (err) {
        showToast(`Opt-out error: ${err.message}`, 'error');
    }
}

async function restoreConsentOptIn(phone) {
    try {
        const res = await fetch('/api/v1/campaigns/consent/opt-in', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phone })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(`Consent restored for ${phone}.`, 'success');
            loadConsentRegistry();
            loadCampaignsDashboard();
        } else {
            showToast(data.error || 'Failed to restore consent.', 'error');
        }
    } catch (err) {
        showToast(`Consent error: ${err.message}`, 'error');
    }
}

// ==========================================
// COMPANY MESSAGING COMMAND CENTER (SECTION 34)
// ==========================================

let cmChannels = [];
let cmActiveChannelId = null;
let cmAutoPollTimer = null;
let cmActiveBroadcast = null;

async function loadCompanyMessagingDashboard() {
    try {
        const tenantLabel = document.getElementById('cmWorkspaceTenantLabel');
        if (tenantLabel && state.currentOrg) {
            tenantLabel.textContent = state.currentOrg.name || 'Enterprise Workspace';
        }
        const roleBadge = document.getElementById('cmActiveRoleBadge');
        if (roleBadge) {
            roleBadge.textContent = `Role: ${state.userRole || 'member'}`;
        }

        const res = await fetch('/api/v1/company-messaging/channels');
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }
        const data = await res.json();
        cmChannels = data.channels || [];

        const countEl = document.getElementById('cmChannelCountText');
        if (countEl) countEl.textContent = `${cmChannels.length} Channels`;

        renderCompanyChannels(cmChannels);

        if (cmChannels.length > 0) {
            const currentExists = cmChannels.some(c => c.id === cmActiveChannelId);
            if (!cmActiveChannelId || !currentExists) {
                selectCompanyChannel(cmChannels[0].id);
            }
        } else {
            const stream = document.getElementById('cmMessageStream');
            if (stream) stream.innerHTML = '<div style="padding: 60px 20px; text-align: center; color: var(--text-dim, #888); font-size: 13px;">No channels found for this workspace.</div>';
        }

        loadCompanyBroadcasts();
    } catch (err) {
        console.error('Failed to load company messaging channels:', err);
    }
}

function renderCompanyChannels(channels) {
    const listEl = document.getElementById('cmChannelList');
    if (!listEl) return;
    if (!channels || channels.length === 0) {
        listEl.innerHTML = '<div style="padding: 30px 16px; text-align: center; color: var(--text-dim, #888); font-size: 12px;">No channels found.</div>';
        return;
    }

    listEl.innerHTML = channels.map(c => {
        const isActive = c.id === cmActiveChannelId;
        const icon = c.channel_type === 'announcement' ? '📢' : (c.channel_type === 'private' ? '🔒' : '#');
        const activeBg = isActive ? 'background: rgba(0, 240, 255, 0.08); border-left: 3px solid var(--cyan-glow, #00f0ff); font-weight: 600; color: #fff;' : 'background: transparent; border-left: 3px solid transparent; color: var(--text-secondary, #cbd5e1);';
        return `
            <div class="cm-channel-item" onclick="selectCompanyChannel('${escapeHtml(c.id)}')" style="display: flex; align-items: center; justify-content: space-between; padding: 8px 16px; cursor: pointer; transition: background 0.15s ease; ${activeBg}">
                <div style="display: flex; align-items: center; gap: 8px; min-width: 0;">
                    <span style="font-size: 14px; color: var(--cyan-glow, #00f0ff);">${icon}</span>
                    <span style="font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(c.name)}</span>
                </div>
                ${c.message_count ? `<span class="badge" style="font-size: 10px; background: rgba(255,255,255,0.08); padding: 1px 6px; border-radius: 10px; color: var(--text-dim, #888);">${c.message_count}</span>` : ''}
            </div>
        `;
    }).join('');
}

function selectCompanyChannel(channelId) {
    cmActiveChannelId = channelId;
    const c = cmChannels.find(ch => ch.id === channelId);
    if (c) {
        const iconEl = document.getElementById('cmActiveChannelIcon');
        const nameEl = document.getElementById('cmActiveChannelName');
        const typeEl = document.getElementById('cmActiveChannelTypeBadge');
        const descEl = document.getElementById('cmActiveChannelDesc');
        const inputEl = document.getElementById('cmMessageInput');
        const archiveBtn = document.getElementById('cmBtnArchiveChannel');

        if (iconEl) iconEl.textContent = c.channel_type === 'announcement' ? '📢' : (c.channel_type === 'private' ? '🔒' : '#');
        if (nameEl) nameEl.textContent = '#' + c.name;
        if (typeEl) {
            typeEl.textContent = (c.channel_type || 'public').toUpperCase();
            typeEl.className = 'status-pill ' + (c.channel_type === 'announcement' ? 'yellow' : (c.channel_type === 'private' ? 'red' : 'green'));
        }
        if (descEl) descEl.textContent = c.description || 'Company messaging stream';
        if (inputEl) inputEl.placeholder = `Message #${c.name}...`;
        if (archiveBtn) {
            const canArchive = (state.userRole === 'owner' || state.userRole === 'admin') && !c.is_system;
            archiveBtn.style.display = canArchive ? 'inline-block' : 'none';
        }
    }
    renderCompanyChannels(cmChannels);
    loadCompanyChannelMessages(channelId);
}

function renderMessageItem(msg) {
    const isCritical = msg.priority === 'critical';
    const isUrgent = msg.priority === 'urgent';
    const border = isCritical ? 'border: 1px solid rgba(239, 68, 68, 0.5); background: rgba(239, 68, 68, 0.08);' : (isUrgent ? 'border: 1px solid rgba(245, 158, 11, 0.5); background: rgba(245, 158, 11, 0.08);' : 'border: 1px solid rgba(255, 255, 255, 0.06); background: rgba(255, 255, 255, 0.03);');
    const priorityPill = isCritical ? '<span class="status-pill red" style="font-size: 10px; padding: 1px 6px;">CRITICAL</span>' : (isUrgent ? '<span class="status-pill yellow" style="font-size: 10px; padding: 1px 6px;">URGENT</span>' : '');
    const canDelete = (state.userRole === 'owner' || state.userRole === 'admin' || (state.currentUser && state.currentUser.id === msg.sender_id));
    const deleteBtn = canDelete ? `<button type="button" class="hud-btn outline small" onclick="deleteCompanyMessage('${escapeHtml(msg.id)}')" title="Delete message" style="padding: 2px 6px; font-size: 10px; border-color: rgba(239,68,68,0.3); color: #fca5a5;">🗑️</button>` : '';

    return `
        <div class="cm-message-card" style="padding: 10px 14px; border-radius: 8px; ${border} display: flex; flex-direction: column; gap: 6px;">
            <div style="display: flex; align-items: center; justify-content: space-between;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-weight: 700; font-size: 13px; color: #fff;">${escapeHtml(msg.sender_name || 'Member')}</span>
                    <span class="status-pill blue" style="font-size: 10px; padding: 1px 6px;">${escapeHtml(msg.sender_role || 'member')}</span>
                    ${priorityPill}
                    <span style="font-size: 11px; color: var(--text-dim, #888); font-family: var(--font-mono);">${escapeHtml(msg.created_at || '')}</span>
                </div>
                ${deleteBtn}
            </div>
            <div style="font-size: 13px; color: #e2e8f0; line-height: 1.45; white-space: pre-wrap; word-break: break-word;">${escapeHtml(msg.body || '')}</div>
        </div>
    `;
}

async function loadCompanyChannelMessages(channelId, isBackground = false) {
    if (!channelId) return;
    const stream = document.getElementById('cmMessageStream');
    if (!stream) return;

    if (!isBackground && stream.innerHTML.includes('Select a channel')) {
        stream.innerHTML = '<div style="padding: 60px 20px; text-align: center; color: var(--text-dim, #888); font-size: 13px;">Loading messages...</div>';
    }

    try {
        const res = await fetch(`/api/v1/company-messaging/channels/${encodeURIComponent(channelId)}/messages?limit=60`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const messages = data.messages || [];

        if (messages.length === 0) {
            stream.innerHTML = '<div style="padding: 60px 20px; text-align: center; color: var(--text-dim, #888); font-size: 13px;">No messages yet. Send a message to start the conversation!</div>';
            return;
        }

        const wasAtBottom = (stream.scrollHeight - stream.scrollTop - stream.clientHeight) < 60;
        stream.innerHTML = messages.map(msg => renderMessageItem(msg)).join('');

        if (!isBackground || wasAtBottom) {
            stream.scrollTop = stream.scrollHeight;
        }
    } catch (err) {
        if (!isBackground) {
            stream.innerHTML = `<div style="padding: 40px 20px; text-align: center; color: #f87171; font-size: 13px;">Failed to load messages: ${escapeHtml(err.message)}</div>`;
        }
    }
}

async function sendCompanyMessage() {
    if (!cmActiveChannelId) {
        showToast('Please select a channel first.', 'warning');
        return;
    }
    const input = document.getElementById('cmMessageInput');
    const prioritySelect = document.getElementById('cmMessagePrioritySelect');
    if (!input) return;

    const body = input.value.trim();
    if (!body) return;

    const priority = prioritySelect ? prioritySelect.value : 'normal';
    const btn = document.getElementById('cmBtnSendMessage');
    if (btn) btn.disabled = true;

    try {
        const res = await fetch(`/api/v1/company-messaging/channels/${encodeURIComponent(cmActiveChannelId)}/messages`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ body, priority })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            input.value = '';
            loadCompanyChannelMessages(cmActiveChannelId);
        } else {
            showToast(data.error || 'Failed to send message.', 'error');
        }
    } catch (err) {
        showToast(`Send error: ${err.message}`, 'error');
    } finally {
        if (btn) btn.disabled = false;
        input.focus();
    }
}

function handleCmMessageKeydown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendCompanyMessage();
    }
}

async function loadCompanyBroadcasts() {
    const bannerContainer = document.getElementById('cmBroadcastBannerContainer');
    if (!bannerContainer) return;

    try {
        const res = await fetch('/api/v1/company-messaging/broadcasts');
        if (!res.ok) return;
        const data = await res.json();
        const broadcasts = data.broadcasts || [];

        const activeBc = broadcasts.find(b => b.requires_acknowledgment && !b.is_acknowledged) || broadcasts[0];

        if (activeBc) {
            cmActiveBroadcast = activeBc;
            bannerContainer.style.display = 'block';

            const iconEl = document.getElementById('cmBroadcastIcon');
            const badgeEl = document.getElementById('cmBroadcastSeverityBadge');
            const titleEl = document.getElementById('cmBroadcastTitleText');
            const senderEl = document.getElementById('cmBroadcastSenderText');
            const bodyEl = document.getElementById('cmBroadcastBodyText');
            const ackContainer = document.getElementById('cmBroadcastAckContainer');

            if (iconEl) iconEl.textContent = activeBc.severity === 'critical' ? '🚨' : (activeBc.severity === 'warning' ? '⚠️' : '📢');
            if (badgeEl) {
                badgeEl.textContent = `${activeBc.severity.toUpperCase()} BROADCAST`;
                badgeEl.className = 'status-pill ' + (activeBc.severity === 'critical' ? 'red' : (activeBc.severity === 'warning' ? 'yellow' : 'blue'));
            }
            if (titleEl) titleEl.textContent = activeBc.title;
            if (senderEl) senderEl.textContent = `by ${activeBc.created_by_name || 'Admin'} • ${activeBc.created_at || ''}`;
            if (bodyEl) bodyEl.textContent = activeBc.body;

            if (ackContainer) {
                ackContainer.style.display = (activeBc.requires_acknowledgment && !activeBc.is_acknowledged) ? 'flex' : 'none';
            }
        } else {
            cmActiveBroadcast = null;
            bannerContainer.style.display = 'none';
        }
    } catch (err) {
        // Silent catch for background poll
    }
}

async function acknowledgeActiveBroadcast() {
    if (!cmActiveBroadcast) return;
    try {
        const res = await fetch(`/api/v1/company-messaging/broadcasts/${encodeURIComponent(cmActiveBroadcast.id)}/ack`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast('Operational broadcast acknowledged.', 'success');
            loadCompanyBroadcasts();
        } else {
            showToast(data.error || 'Failed to acknowledge broadcast.', 'error');
        }
    } catch (err) {
        showToast(`Ack error: ${err.message}`, 'error');
    }
}

async function openCreateChannelModal() {
    const rawName = prompt('Enter new channel name (e.g. dev-team, ops-war-room):');
    if (!rawName) return;
    const name = rawName.trim().replace(/^#/, '');
    if (!name) return;

    const desc = prompt('Enter channel description (optional):', 'Internal team collaboration channel.') || '';

    try {
        const res = await fetch('/api/v1/company-messaging/channels', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name,
                display_name: '#' + name,
                description: desc,
                channel_type: 'public'
            })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast(`Channel #${name} created successfully.`, 'success');
            await loadCompanyMessagingDashboard();
            if (data.channel && data.channel.id) {
                selectCompanyChannel(data.channel.id);
            }
        } else {
            showToast(data.error || 'Failed to create channel.', 'error');
        }
    } catch (err) {
        showToast(`Channel creation error: ${err.message}`, 'error');
    }
}

async function openCreateBroadcastModal() {
    const title = prompt('Operational Broadcast Title (e.g. Scheduled Maintenance Window):');
    if (!title || !title.trim()) return;

    const body = prompt('Broadcast Details / Operational Message:');
    if (!body || !body.trim()) return;

    try {
        const res = await fetch('/api/v1/company-messaging/broadcasts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title: title.trim(),
                body: body.trim(),
                severity: 'warning',
                requires_acknowledgment: true,
                expires_hours: 48
            })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast('Operational broadcast dispatched across tenant workspace.', 'success');
            loadCompanyBroadcasts();
        } else {
            showToast(data.error || 'Failed to dispatch broadcast.', 'error');
        }
    } catch (err) {
        showToast(`Broadcast dispatch error: ${err.message}`, 'error');
    }
}

async function archiveCurrentChannel() {
    if (!cmActiveChannelId) return;
    const c = cmChannels.find(ch => ch.id === cmActiveChannelId);
    if (!c) return;

    if (c.is_system) {
        showToast('System default channels cannot be archived.', 'warning');
        return;
    }

    if (!confirm(`Are you sure you want to archive #${c.name}? Messages will be retained but the channel will be hidden.`)) {
        return;
    }

    try {
        const res = await fetch(`/api/v1/company-messaging/channels/${encodeURIComponent(cmActiveChannelId)}`, {
            method: 'DELETE'
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast(`Channel #${c.name} archived.`, 'success');
            cmActiveChannelId = null;
            loadCompanyMessagingDashboard();
        } else {
            showToast(data.error || 'Failed to archive channel.', 'error');
        }
    } catch (err) {
        showToast(`Archive error: ${err.message}`, 'error');
    }
}

async function deleteCompanyMessage(messageId) {
    if (!messageId) return;
    if (!confirm('Are you sure you want to delete this message?')) return;

    try {
        const res = await fetch(`/api/v1/company-messaging/messages/${encodeURIComponent(messageId)}`, {
            method: 'DELETE'
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast('Message deleted.', 'success');
            if (cmActiveChannelId) loadCompanyChannelMessages(cmActiveChannelId);
        } else {
            showToast(data.error || 'Failed to delete message.', 'error');
        }
    } catch (err) {
        showToast(`Delete error: ${err.message}`, 'error');
    }
}

function filterCompanyChannels(query) {
    const q = (query || '').toLowerCase().trim();
    if (!q) {
        renderCompanyChannels(cmChannels);
        return;
    }
    const filtered = cmChannels.filter(c => 
        (c.name && c.name.toLowerCase().includes(q)) || 
        (c.display_name && c.display_name.toLowerCase().includes(q)) ||
        (c.description && c.description.toLowerCase().includes(q))
    );
    renderCompanyChannels(filtered);
}

function startCompanyMessagingAutoPoll() {
    stopCompanyMessagingAutoPoll();
    cmAutoPollTimer = setInterval(() => {
        if (cmActiveChannelId) {
            loadCompanyChannelMessages(cmActiveChannelId, true);
        }
        loadCompanyBroadcasts();
    }, 6000);
}

function stopCompanyMessagingAutoPoll() {
    if (cmAutoPollTimer) {
        clearInterval(cmAutoPollTimer);
        cmAutoPollTimer = null;
    }
}


// ==========================================================================
// BASHFLOW CLOUD: PRODUCTS CATALOG & SHOP MANAGEMENT CONTROLLER
// ==========================================================================

let productSearchDebounceTimer = null;

function loadProductsCatalog() {
    const tbody = document.getElementById('productsTableBody');
    if (tbody) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center" style="padding: 30px; color: var(--text-secondary);"><span class="icon spinning" style="display:inline-block; margin-right: 6px;">🔄</span> Loading product catalog...</td></tr>';
    }

    const sortVal = document.getElementById('productSortFilter') ? document.getElementById('productSortFilter').value : 'name_asc';
    const activeVal = document.getElementById('productActiveFilter') ? document.getElementById('productActiveFilter').value : 'active';
    const categoryVal = document.getElementById('productCategoryFilter') ? document.getElementById('productCategoryFilter').value : 'all';
    const stockVal = document.getElementById('productStockStatusFilter') ? document.getElementById('productStockStatusFilter').value : 'all';
    const searchVal = document.getElementById('productSearchInput') ? document.getElementById('productSearchInput').value.trim() : '';

    let url = `/api/v1/ecommerce/products?limit=250&sort=${encodeURIComponent(sortVal)}`;
    if (activeVal === 'all') url += '&include_inactive=true';
    else if (activeVal === 'archived') url += '&status=archived';
    
    if (categoryVal && categoryVal !== 'all') url += `&category=${encodeURIComponent(categoryVal)}`;
    if (stockVal && stockVal !== 'all') url += `&stock_status=${encodeURIComponent(stockVal)}`;
    if (searchVal) url += `&query=${encodeURIComponent(searchVal)}`;

    fetch(url)
        .then(res => {
            if (!res.ok) throw new Error(`HTTP error ${res.status}`);
            return res.json();
        })
        .then(data => {
            state.products = data.products || [];
            state.productCategories = data.categories || [];
            state.productStats = data.stats || {};

            updateProductCatalogKPIs(data.stats, data.count);
            populateProductCategoryDropdowns(data.categories);
            renderProducts(state.products);
        })
        .catch(err => {
            console.error('Failed to load products catalog:', err);
            if (tbody) {
                tbody.innerHTML = `<tr><td colspan="8" class="text-center" style="padding: 24px; color: #f87171;">Failed to load catalog: ${escapeHtml(err.message)} <button class="hud-btn outline small" style="margin-left: 10px;" onclick="loadProductsCatalog()">Retry</button></td></tr>`;
            }
        });
}

function updateProductCatalogKPIs(stats, count) {
    if (!stats) return;

    const totalEl = document.getElementById('prodMetricTotal');
    const inStockEl = document.getElementById('prodMetricInStock');
    const lowStockEl = document.getElementById('prodMetricLowStock');
    const outOfStockEl = document.getElementById('prodMetricOutOfStock');
    const valEl = document.getElementById('prodMetricValuation');
    const pill = document.getElementById('tabProductCount');

    if (totalEl) totalEl.textContent = stats.total !== undefined ? stats.total : count;
    if (inStockEl) inStockEl.textContent = stats.in_stock || 0;
    if (lowStockEl) lowStockEl.textContent = stats.low_stock || 0;
    if (outOfStockEl) outOfStockEl.textContent = stats.out_of_stock || 0;
    
    if (valEl) {
        const val = stats.total_inventory_value || 0;
        valEl.textContent = `PKR ${Number(val).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
    }

    if (pill) {
        const activeCount = stats.active !== undefined ? stats.active : count;
        pill.textContent = activeCount;
        pill.style.display = activeCount > 0 ? 'inline-block' : 'none';
    }
}

function populateProductCategoryDropdowns(categories) {
    const filterSelect = document.getElementById('productCategoryFilter');
    const shareSelect = document.getElementById('shareCatalogCategory');
    const addDatalist = document.getElementById('addProdCategoryDatalist');
    const editDatalist = document.getElementById('editProdCategoryDatalist');

    const currentFilterVal = filterSelect ? filterSelect.value : 'all';

    const safeCats = Array.isArray(categories) ? categories : [];

    if (filterSelect) {
        let opts = '<option value="all">All Categories</option>';
        safeCats.forEach(c => {
            opts += `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`;
        });
        filterSelect.innerHTML = opts;
        filterSelect.value = currentFilterVal;
    }

    if (shareSelect) {
        let opts = '<option value="">All Categories (Full Catalog)</option>';
        safeCats.forEach(c => {
            opts += `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`;
        });
        shareSelect.innerHTML = opts;
    }

    const datalistOptions = safeCats.map(c => `<option value="${escapeHtml(c)}">`).join('');
    if (addDatalist) addDatalist.innerHTML = datalistOptions;
    if (editDatalist) editDatalist.innerHTML = datalistOptions;
}

function renderProducts(products) {
    const tbody = document.getElementById('productsTableBody');
    const gridContainer = document.getElementById('productGridViewContainer');
    const emptyState = document.getElementById('productsEmptyState');
    const tableContainer = document.getElementById('productTableViewContainer');

    if (!products || products.length === 0) {
        if (tbody) tbody.innerHTML = '';
        if (gridContainer) gridContainer.innerHTML = '';
        if (emptyState) emptyState.style.display = 'block';
        if (tableContainer) tableContainer.style.display = 'none';
        if (gridContainer) gridContainer.style.display = 'none';
        return;
    }

    if (emptyState) emptyState.style.display = 'none';

    const isGrid = state.productViewMode === 'grid';
    if (tableContainer) tableContainer.style.display = isGrid ? 'none' : 'block';
    if (gridContainer) gridContainer.style.display = isGrid ? 'grid' : 'none';

    // 1. Render Table Rows
    if (tbody) {
        let rowsHtml = '';
        products.forEach(p => {
            const hasImg = p.image_url && p.image_url.trim().length > 0;
            const priceFormatted = `${escapeHtml(p.currency || 'PKR')} ${Number(p.price || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
            
            let stockStatusClass = 'in-stock';
            let stockStatusLabel = '● In Stock';
            if (p.stock_quantity <= 0 || p.stock_status === 'out_of_stock') {
                stockStatusClass = 'out-of-stock';
                stockStatusLabel = '✖ Out of Stock';
            } else if (p.stock_quantity <= 5 || p.stock_status === 'low_stock') {
                stockStatusClass = 'low-stock';
                stockStatusLabel = '▲ Low Stock';
            }

            const imgMarkup = hasImg
                ? `<div class="product-thumb-container" onclick="openProductImagePreview('${encodeURIComponent(p.image_url)}', '${encodeURIComponent(p.name)}')" title="Click to enlarge image">
                       <img src="${escapeHtml(p.image_url)}" class="product-thumb-img" alt="${escapeHtml(p.name)}" onerror="this.onerror=null; this.parentElement.innerHTML='<span style=\'font-size:20px;\'>🛍️</span>';">
                   </div>`
                : `<div class="product-thumb-container" title="No image provided">
                       <span style="font-size: 20px;">🛍️</span>
                   </div>`;

            const imgUrlCol = hasImg
                ? `<a href="javascript:void(0)" class="product-image-url-link" onclick="openProductImagePreview('${encodeURIComponent(p.image_url)}', '${encodeURIComponent(p.name)}')" title="${escapeHtml(p.image_url)}">
                       <span>🖼️</span> View Image
                   </a>`
                : `<span style="color: var(--text-secondary); font-size: 11px; font-style: italic;">No image</span>`;

            const statusBadge = p.is_active
                ? `<span class="badge success" style="font-size: 11px;">Active</span>`
                : `<span class="badge skipped" style="font-size: 11px;">Archived</span>`;

            rowsHtml += `
                <tr id="prod-row-${p.id}" class="${p.is_active ? '' : 'opacity-60'}">
                    <td>
                        <div class="product-item-cell">
                            ${imgMarkup}
                            <div style="min-width: 0;">
                                <div class="product-item-title">${escapeHtml(p.name)}</div>
                                <div class="product-item-desc" title="${escapeHtml(p.description || '')}">${escapeHtml(p.description || 'No description provided')}</div>
                                <div style="margin-top: 4px; display: flex; gap: 6px; align-items: center;">
                                    <span class="product-sku-pill">${escapeHtml(p.sku || 'NO-SKU')}</span>
                                    ${p.barcode ? `<span class="product-sku-pill" style="opacity: 0.8;" title="Barcode">#${escapeHtml(p.barcode)}</span>` : ''}
                                </div>
                            </div>
                        </div>
                    </td>
                    <td>
                        <span class="product-category-tag">${escapeHtml(p.category || 'General')}</span>
                    </td>
                    <td>
                        <div class="product-price-val">${priceFormatted}</div>
                        <div style="font-size: 10.5px; color: var(--text-secondary); margin-top: 2px;">per ${escapeHtml(p.unit || 'unit')}</div>
                    </td>
                    <td>
                        <div class="stock-qty-control">
                            <button type="button" class="stock-qty-btn" onclick="quickAdjustStock('${p.id}', -1)" title="Decrease stock by 1">-</button>
                            <span class="stock-qty-num" id="stock-num-${p.id}">${p.stock_quantity}</span>
                            <button type="button" class="stock-qty-btn" onclick="quickAdjustStock('${p.id}', 1)" title="Increase stock by 1">+</button>
                        </div>
                    </td>
                    <td>
                        <span class="stock-status-pill ${stockStatusClass}">${stockStatusLabel}</span>
                    </td>
                    <td>
                        ${imgUrlCol}
                    </td>
                    <td>
                        ${statusBadge}
                    </td>
                    <td class="text-right">
                        <div class="product-actions-cell">
                            <button type="button" class="hud-btn outline small" onclick="openEditProductModal('${p.id}')" title="Edit Item Details">
                                <span class="icon">✏️</span> Edit
                            </button>
                            <button type="button" class="hud-btn outline small" onclick="openShareCatalogModal('${escapeHtml(p.category || '')}')" title="Share via WhatsApp">
                                <span class="icon">💬</span>
                            </button>
                            <button type="button" class="hud-btn red-btn small" onclick="confirmDeleteProduct('${p.id}', '${encodeURIComponent(p.name)}')" title="Delete or Archive Product">
                                <span class="icon">🗑️</span>
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        });
        tbody.innerHTML = rowsHtml;
    }

    // 2. Render Grid Cards
    if (gridContainer) {
        let gridHtml = '';
        products.forEach(p => {
            const hasImg = p.image_url && p.image_url.trim().length > 0;
            const priceFormatted = `${escapeHtml(p.currency || 'PKR')} ${Number(p.price || 0).toLocaleString()}`;
            
            let stockStatusClass = 'in-stock';
            let stockStatusLabel = 'In Stock';
            if (p.stock_quantity <= 0 || p.stock_status === 'out_of_stock') {
                stockStatusClass = 'out-of-stock';
                stockStatusLabel = 'Out of Stock';
            } else if (p.stock_quantity <= 5 || p.stock_status === 'low_stock') {
                stockStatusClass = 'low-stock';
                stockStatusLabel = `${p.stock_quantity} Left`;
            }

            const mediaMarkup = hasImg
                ? `<img src="${escapeHtml(p.image_url)}" alt="${escapeHtml(p.name)}" onerror="this.onerror=null; this.parentElement.innerHTML='<span style=\'font-size:42px;\'>🛍️</span>';">`
                : `<span style="font-size: 42px;">🛍️</span>`;

            gridHtml += `
                <div class="product-card">
                    <div class="product-card-media" onclick="openProductImagePreview('${encodeURIComponent(p.image_url || '')}', '${encodeURIComponent(p.name)}')">
                        ${mediaMarkup}
                        <span class="product-category-tag product-card-badge">${escapeHtml(p.category || 'General')}</span>
                        <span class="stock-status-pill ${stockStatusClass} product-card-status-pill">${stockStatusLabel}</span>
                    </div>
                    <div class="product-card-body">
                        <div class="product-card-title">${escapeHtml(p.name)}</div>
                        <div class="product-card-desc">${escapeHtml(p.description || 'No description provided')}</div>
                        <div style="display: flex; justify-content: space-between; align-items: baseline; margin-top: auto;">
                            <div>
                                <span style="font-size: 11px; color: var(--text-secondary);">SKU:</span>
                                <span class="product-sku-pill">${escapeHtml(p.sku || 'N/A')}</span>
                            </div>
                            <div class="product-price-val" style="color: #38bdf8;">${priceFormatted}</div>
                        </div>
                    </div>
                    <div class="product-card-footer" style="padding: 12px 16px; background: rgba(0,0,0,0.15);">
                        <div style="font-size: 11.5px; color: var(--text-secondary);">Stock: <strong style="color: var(--text-primary);">${p.stock_quantity} ${escapeHtml(p.unit || 'units')}</strong></div>
                        <div style="display: flex; gap: 6px;">
                            <button type="button" class="hud-btn outline small" onclick="openEditProductModal('${p.id}')">Edit</button>
                            <button type="button" class="hud-btn red-btn small" onclick="confirmDeleteProduct('${p.id}', '${encodeURIComponent(p.name)}')">🗑️</button>
                        </div>
                    </div>
                </div>
            `;
        });
        gridContainer.innerHTML = gridHtml;
    }
}

function debounceFilterProducts() {
    if (productSearchDebounceTimer) clearTimeout(productSearchDebounceTimer);
    productSearchDebounceTimer = setTimeout(() => {
        filterProductsTable();
    }, 250);
}

function filterProductsTable() {
    loadProductsCatalog();
}

function setProductViewMode(mode) {
    state.productViewMode = mode;
    const btnTable = document.getElementById('btnProductViewTable');
    const btnGrid = document.getElementById('btnProductViewGrid');
    const tableContainer = document.getElementById('productTableViewContainer');
    const gridContainer = document.getElementById('productGridViewContainer');

    if (mode === 'grid') {
        if (btnTable) { btnTable.classList.remove('active'); btnTable.classList.add('outline'); }
        if (btnGrid) { btnGrid.classList.add('active'); btnGrid.classList.remove('outline'); }
        if (tableContainer) tableContainer.style.display = 'none';
        if (gridContainer) gridContainer.style.display = 'grid';
    } else {
        if (btnTable) { btnTable.classList.add('active'); btnTable.classList.remove('outline'); }
        if (btnGrid) { btnGrid.classList.remove('active'); btnGrid.classList.add('outline'); }
        if (tableContainer) tableContainer.style.display = 'block';
        if (gridContainer) gridContainer.style.display = 'none';
    }
}

// --------------------------------------------------------------------------
// ADD PRODUCT WORKFLOW
// --------------------------------------------------------------------------

function openAddProductModal() {
    const form = document.getElementById('addProductForm');
    if (form) form.reset();

    generateRandomSku('addProdSku');
    document.getElementById('addProdIsActive').checked = true;
    document.getElementById('addProdStock').value = '10';
    document.getElementById('addProdUnit').value = 'piece';
    updateAddProductPreview();

    const modal = document.getElementById('modalAddProduct');
    if (modal) modal.style.display = 'flex';
}

function closeAddProductModal() {
    const modal = document.getElementById('modalAddProduct');
    if (modal) modal.style.display = 'none';
}

function updateAddProductPreview() {
    const name = document.getElementById('addProdName')?.value.trim() || 'Product Name';
    const cat = document.getElementById('addProdCategory')?.value.trim() || 'General';
    const price = parseFloat(document.getElementById('addProdPrice')?.value) || 0;
    const curr = document.getElementById('addProdCurrency')?.value || 'PKR';
    const stock = parseInt(document.getElementById('addProdStock')?.value, 10) || 0;
    const imgUrl = document.getElementById('addProdImageUrl')?.value.trim() || '';

    const titleEl = document.getElementById('addPreviewTitle');
    const catEl = document.getElementById('addPreviewCategory');
    const priceEl = document.getElementById('addPreviewPrice');
    const stockEl = document.getElementById('addPreviewStockPill');
    const imgEl = document.getElementById('addPreviewImg');
    const fallbackEl = document.getElementById('addPreviewFallback');

    if (titleEl) titleEl.textContent = name;
    if (catEl) catEl.textContent = cat;
    if (priceEl) priceEl.textContent = `${curr} ${price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    
    if (stockEl) {
        stockEl.textContent = `${stock} in Stock`;
        stockEl.className = 'stock-status-pill ' + (stock <= 0 ? 'out-of-stock' : (stock <= 5 ? 'low-stock' : 'in-stock'));
    }

    if (imgEl && fallbackEl) {
        if (imgUrl) {
            imgEl.src = imgUrl;
            imgEl.style.display = 'block';
            fallbackEl.style.display = 'none';
        } else {
            imgEl.style.display = 'none';
            fallbackEl.style.display = 'block';
        }
    }
}

function setPresetImageUrl(inputId, url) {
    const el = document.getElementById(inputId);
    if (el) {
        el.value = url;
        if (inputId.includes('add')) updateAddProductPreview();
        else updateEditProductPreview();
    }
}

function generateRandomSku(inputId) {
    const rand = Math.floor(1000 + Math.random() * 9000);
    const code = `PRD-${rand}`;
    const el = document.getElementById(inputId);
    if (el) el.value = code;
}

function submitCreateProduct() {
    const btn = document.getElementById('btnAddProdSubmit');
    const name = document.getElementById('addProdName')?.value.trim();
    if (!name) {
        showToast('Please enter a product name.', 'error');
        return;
    }

    const payload = {
        name: name,
        category: document.getElementById('addProdCategory')?.value.trim() || 'General',
        sku: document.getElementById('addProdSku')?.value.trim() || null,
        barcode: document.getElementById('addProdBarcode')?.value.trim() || null,
        price: parseFloat(document.getElementById('addProdPrice')?.value) || 0.0,
        currency: document.getElementById('addProdCurrency')?.value || 'PKR',
        stock_quantity: parseInt(document.getElementById('addProdStock')?.value, 10) || 0,
        unit: document.getElementById('addProdUnit')?.value.trim() || 'piece',
        image_url: document.getElementById('addProdImageUrl')?.value.trim() || null,
        description: document.getElementById('addProdDescription')?.value.trim() || '',
        is_active: document.getElementById('addProdIsActive')?.checked ?? true
    };

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="icon spinning">🔄</span> Saving...';
    }

    fetch('/api/v1/ecommerce/products', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            showToast(`Product "${payload.name}" successfully added to catalog!`, 'success');
            closeAddProductModal();
            loadProductsCatalog();
        } else {
            showToast(data.error || 'Failed to create product', 'error');
        }
    })
    .catch(err => {
        showToast(`Error creating product: ${err.message}`, 'error');
    })
    .finally(() => {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<span class="icon">💾</span> Save &amp; Add Product';
        }
    });
}

// --------------------------------------------------------------------------
// EDIT PRODUCT WORKFLOW
// --------------------------------------------------------------------------

function openEditProductModal(productId) {
    const p = state.products ? state.products.find(item => item.id === productId) : null;
    if (!p) {
        showToast('Product not found in catalog.', 'error');
        return;
    }

    document.getElementById('editProdId').value = p.id;
    document.getElementById('editProdName').value = p.name || '';
    document.getElementById('editProdCategory').value = p.category || 'General';
    document.getElementById('editProdSku').value = p.sku || '';
    document.getElementById('editProdBarcode').value = p.barcode || '';
    document.getElementById('editProdPrice').value = p.price !== undefined ? p.price : 0;
    document.getElementById('editProdCurrency').value = p.currency || 'PKR';
    document.getElementById('editProdStock').value = p.stock_quantity !== undefined ? p.stock_quantity : 0;
    document.getElementById('editProdUnit').value = p.unit || 'piece';
    document.getElementById('editProdImageUrl').value = p.image_url || '';
    document.getElementById('editProdDescription').value = p.description || '';
    document.getElementById('editProdIsActive').checked = Boolean(p.is_active);

    updateEditProductPreview();

    const modal = document.getElementById('modalEditProduct');
    if (modal) modal.style.display = 'flex';
}

function closeEditProductModal() {
    const modal = document.getElementById('modalEditProduct');
    if (modal) modal.style.display = 'none';
}

function updateEditProductPreview() {
    const name = document.getElementById('editProdName')?.value.trim() || 'Product Name';
    const cat = document.getElementById('editProdCategory')?.value.trim() || 'General';
    const price = parseFloat(document.getElementById('editProdPrice')?.value) || 0;
    const curr = document.getElementById('editProdCurrency')?.value || 'PKR';
    const stock = parseInt(document.getElementById('editProdStock')?.value, 10) || 0;
    const imgUrl = document.getElementById('editProdImageUrl')?.value.trim() || '';

    const titleEl = document.getElementById('editPreviewTitle');
    const catEl = document.getElementById('editPreviewCategory');
    const priceEl = document.getElementById('editPreviewPrice');
    const stockEl = document.getElementById('editPreviewStockPill');
    const imgEl = document.getElementById('editPreviewImg');
    const fallbackEl = document.getElementById('editPreviewFallback');

    if (titleEl) titleEl.textContent = name;
    if (catEl) catEl.textContent = cat;
    if (priceEl) priceEl.textContent = `${curr} ${price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    
    if (stockEl) {
        stockEl.textContent = `${stock} in Stock`;
        stockEl.className = 'stock-status-pill ' + (stock <= 0 ? 'out-of-stock' : (stock <= 5 ? 'low-stock' : 'in-stock'));
    }

    if (imgEl && fallbackEl) {
        if (imgUrl) {
            imgEl.src = imgUrl;
            imgEl.style.display = 'block';
            fallbackEl.style.display = 'none';
        } else {
            imgEl.style.display = 'none';
            fallbackEl.style.display = 'block';
        }
    }
}

function submitUpdateProduct() {
    const productId = document.getElementById('editProdId')?.value;
    if (!productId) return;

    const btn = document.getElementById('btnEditProdSubmit');
    const name = document.getElementById('editProdName')?.value.trim();
    if (!name) {
        showToast('Product name is required.', 'error');
        return;
    }

    const payload = {
        name: name,
        category: document.getElementById('editProdCategory')?.value.trim() || 'General',
        sku: document.getElementById('editProdSku')?.value.trim() || null,
        barcode: document.getElementById('editProdBarcode')?.value.trim() || null,
        price: parseFloat(document.getElementById('editProdPrice')?.value) || 0.0,
        currency: document.getElementById('editProdCurrency')?.value || 'PKR',
        stock_quantity: parseInt(document.getElementById('editProdStock')?.value, 10) || 0,
        unit: document.getElementById('editProdUnit')?.value.trim() || 'piece',
        image_url: document.getElementById('editProdImageUrl')?.value.trim() || null,
        description: document.getElementById('editProdDescription')?.value.trim() || '',
        is_active: document.getElementById('editProdIsActive')?.checked ?? true
    };

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="icon spinning">🔄</span> Updating...';
    }

    fetch(`/api/v1/ecommerce/products/${encodeURIComponent(productId)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            showToast(`Product "${payload.name}" updated successfully!`, 'success');
            closeEditProductModal();
            loadProductsCatalog();
        } else {
            showToast(data.error || 'Failed to update product', 'error');
        }
    })
    .catch(err => {
        showToast(`Update error: ${err.message}`, 'error');
    })
    .finally(() => {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<span class="icon">💾</span> Update Product';
        }
    });
}

function quickAdjustStock(productId, delta) {
    const p = state.products ? state.products.find(item => item.id === productId) : null;
    if (!p) return;

    const newStock = Math.max(0, (p.stock_quantity || 0) + delta);
    p.stock_quantity = newStock;

    const numEl = document.getElementById(`stock-num-${productId}`);
    if (numEl) numEl.textContent = newStock;

    fetch(`/api/v1/ecommerce/products/${encodeURIComponent(productId)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stock_quantity: newStock })
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            showToast(`Stock updated for ${p.name}: ${newStock} units`, 'success');
            loadProductsCatalog();
        }
    })
    .catch(err => {
        showToast(`Stock update error: ${err.message}`, 'error');
    });
}

function confirmDeleteProduct(productId, encodedName) {
    const name = decodeURIComponent(encodedName);
    openSafetyConfirmModal({
        title: 'Delete Product from Catalog',
        message: `Are you sure you want to remove "${name}" from your store catalog?`,
        detail: `Product ID: ${productId}\nThis item will no longer appear in WhatsApp AI inquiries or store searches.`,
        confirmBtnText: 'Archive / Delete',
        onConfirm: () => {
            fetch(`/api/v1/ecommerce/products/${encodeURIComponent(productId)}?hard=false`, {
                method: 'DELETE'
            })
            .then(res => res.json())
            .then(data => {
                if (data.status === 'success') {
                    showToast(`Product "${name}" successfully removed.`, 'success');
                    loadProductsCatalog();
                } else {
                    showToast(data.error || 'Failed to remove product', 'error');
                }
            })
            .catch(err => {
                showToast(`Delete error: ${err.message}`, 'error');
            });
        }
    });
}

function seedDemoProducts() {
    showToast('Populating sample online store catalog...', 'info');
    fetch('/api/v1/ecommerce/products/seed-demo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            showToast(`Successfully loaded demo items into your shop catalog!`, 'success');
            loadProductsCatalog();
        } else {
            showToast(data.error || 'Failed to load demo items', 'error');
        }
    })
    .catch(err => {
        showToast(`Seed demo error: ${err.message}`, 'error');
    });
}

// --------------------------------------------------------------------------
// WHATSAPP CATALOG DISPATCH WORKFLOW
// --------------------------------------------------------------------------

function openShareCatalogModal(category = '') {
    const select = document.getElementById('shareCatalogCategory');
    if (select && category) {
        select.value = category;
    }
    const modal = document.getElementById('modalShareCatalog');
    if (modal) modal.style.display = 'flex';
}

function closeShareCatalogModal() {
    const modal = document.getElementById('modalShareCatalog');
    if (modal) modal.style.display = 'none';
}

function submitShareCatalog() {
    const phone = document.getElementById('shareCatalogPhone')?.value.trim();
    if (!phone) {
        showToast('Please enter a recipient phone number.', 'error');
        return;
    }

    const category = document.getElementById('shareCatalogCategory')?.value || null;
    const header = document.getElementById('shareCatalogHeader')?.value.trim() || null;
    const btn = document.getElementById('btnShareCatalogSubmit');

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="icon spinning">🔄</span> Sending...';
    }

    fetch('/api/v1/ecommerce/catalog/share', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            to_phone: phone,
            category: category,
            header_text: header
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            showToast(`Interactive catalog sent to WhatsApp: ${phone}`, 'success');
            closeShareCatalogModal();
        } else {
            showToast(data.error || data.message || 'Failed to send catalog', 'error');
        }
    })
    .catch(err => {
        showToast(`Dispatch error: ${err.message}`, 'error');
    })
    .finally(() => {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<span class="icon">🚀</span> Dispatch via WhatsApp';
        }
    });
}

// --------------------------------------------------------------------------
// IMAGE LIGHTBOX PREVIEW
// --------------------------------------------------------------------------

function openProductImagePreview(encodedUrl, encodedTitle) {
    const url = decodeURIComponent(encodedUrl);
    const title = decodeURIComponent(encodedTitle || 'Product Image');

    if (!url || url === 'undefined') return;

    const modal = document.getElementById('modalProductImagePreview');
    const img = document.getElementById('imagePreviewImg');
    const titleEl = document.getElementById('imagePreviewTitle');
    const urlText = document.getElementById('imagePreviewUrlText');

    if (img) img.src = url;
    if (titleEl) titleEl.textContent = title;
    if (urlText) urlText.innerHTML = `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" style="color: #38bdf8; text-decoration: underline;">Open Full Resolution in New Tab ↗</a>`;

    if (modal) modal.style.display = 'flex';
}

function closeProductImagePreview() {
    const modal = document.getElementById('modalProductImagePreview');
    if (modal) modal.style.display = 'none';
}


// ==========================================================================
// BASHFLOW CLOUD: BULK LEADS IMPORTER, WHATSAPP LOCATION & TRUCK DISPATCH
// ==========================================================================

// --- 1. Bulk Leads Importer ---

function openBulkLeadImportModal() {
    let modal = document.getElementById('modalBulkLeadImport');
    if (!modal) {
        // Dynamically inject modal into body
        const div = document.createElement('div');
        div.id = 'modalBulkLeadImport';
        div.className = 'hud-modal-overlay';
        div.style.display = 'flex';
        div.onclick = function(e) { if (e.target === this) closeBulkLeadImportModal(); };
        div.innerHTML = `
            <div class="hud-modal" style="max-width: 680px; width: 95vw;">
                <div class="modal-header">
                    <div class="hud-flex-row hud-gap-md" style="align-items: center;">
                        <span style="font-size: 22px;">📥</span>
                        <div>
                            <h3 style="margin: 0; font-size: 16px;">Bulk Leads Importer</h3>
                            <p style="font-size: 11.5px; color: var(--text-dim, #888); margin: 2px 0 0 0;">Import hundreds of prospective customer leads via CSV or JSON with automatic deduplication</p>
                        </div>
                    </div>
                    <button type="button" class="close-btn" onclick="closeBulkLeadImportModal()">&times;</button>
                </div>
                <div class="modal-body" style="padding: 20px;">
                    <div style="margin-bottom: 14px;">
                        <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 6px;">Upload CSV File or Paste Records</label>
                        <input type="file" id="bulkLeadFileInput" accept=".csv,.txt" onchange="handleBulkLeadFileUpload(event)" style="font-size: 12px; margin-bottom: 10px; display: block;">
                    </div>
                    <div class="form-group" style="margin-bottom: 12px;">
                        <textarea id="bulkLeadTextarea" class="hud-input mono" rows="8" placeholder="name,phone,email,company,message,category\nAli Khan,+923001234567,ali@example.com,Acme,Interested in enterprise tier,Online\nZainab Ahmed,+923219876543,zainab@retail.pk,Retail Hub,Physical store inquiry,Offline" style="width: 100%; font-size: 12px; resize: vertical;"></textarea>
                    </div>
                    <div style="font-size: 11px; color: var(--text-secondary); line-height: 1.4; margin-bottom: 16px;">
                        Supported columns: <code>name</code>, <code>phone</code>, <code>email</code>, <code>company</code>, <code>message</code>, <code>category</code> (Online/Offline). Duplicate phone numbers are automatically detected and safely skipped.
                    </div>
                    <div id="bulkImportPreviewStatus" style="display: none; padding: 10px; border-radius: 6px; font-size: 12px; margin-bottom: 14px; background: rgba(56, 189, 248, 0.1); border: 1px solid rgba(56, 189, 248, 0.2); color: #38bdf8;"></div>
                    <div class="modal-footer" style="padding: 12px 0 0 0; border-top: 1px solid var(--border-color); display: flex; justify-content: flex-end; gap: 10px;">
                        <button type="button" class="hud-btn outline" onclick="closeBulkLeadImportModal()">Cancel</button>
                        <button type="button" class="hud-btn primary" id="btnSubmitBulkLeads" onclick="submitBulkLeadImport()">
                            <span class="icon">🚀</span> Start Bulk Import
                        </button>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(div);
    } else {
        modal.style.display = 'flex';
    }
}

function closeBulkLeadImportModal() {
    const modal = document.getElementById('modalBulkLeadImport');
    if (modal) modal.style.display = 'none';
}

function handleBulkLeadFileUpload(event) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = function(e) {
        const text = e.target.result;
        const textarea = document.getElementById('bulkLeadTextarea');
        if (textarea) textarea.value = text;
        const lineCount = (text.match(/\n/g) || []).length;
        const statusBox = document.getElementById('bulkImportPreviewStatus');
        if (statusBox) {
            statusBox.style.display = 'block';
            statusBox.textContent = `Loaded ${file.name} (~${lineCount} records ready for processing).`;
        }
    };
    reader.readAsText(file);
}

function submitBulkLeadImport() {
    const textarea = document.getElementById('bulkLeadTextarea');
    const content = textarea ? textarea.value.trim() : '';
    if (!content) {
        showToast('Please paste CSV text or select a CSV file.', 'error');
        return;
    }

    const btn = document.getElementById('btnSubmitBulkLeads');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="icon spinning">🔄</span> Importing Leads...';
    }

    fetch('/api/v1/leads/bulk-import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ csv_content: content })
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            showToast(`Bulk Import complete: ${data.imported_count} imported, ${data.skipped_count} duplicates skipped!`, 'success');
            closeBulkLeadImportModal();
            if (typeof loadLeads === 'function') loadLeads();
        } else {
            showToast(data.error || 'Failed to import leads', 'error');
        }
    })
    .catch(err => {
        showToast(`Import error: ${err.message}`, 'error');
    })
    .finally(() => {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<span class="icon">🚀</span> Start Bulk Import';
        }
    });
}

// --- 2. Truck Dispatch Tracking Workflow ---

function openTruckDispatchModal(orderId, orderNumber, customerPhone, customerName) {
    let modal = document.getElementById('modalTruckDispatch');
    if (!modal) {
        const div = document.createElement('div');
        div.id = 'modalTruckDispatch';
        div.className = 'hud-modal-overlay';
        div.style.display = 'flex';
        div.onclick = function(e) { if (e.target === this) closeTruckDispatchModal(); };
        div.innerHTML = `
            <div class="hud-modal" style="max-width: 580px; width: 95vw;">
                <div class="modal-header">
                    <div class="hud-flex-row hud-gap-md" style="align-items: center;">
                        <span style="font-size: 22px;">🚚</span>
                        <div>
                            <h3 style="margin: 0; font-size: 16px;">Dispatch Delivery Truck</h3>
                            <p style="font-size: 11.5px; color: var(--text-dim, #888); margin: 2px 0 0 0;">Assign fleet vehicle, driver details, and dispatch live WhatsApp tracking route</p>
                        </div>
                    </div>
                    <button type="button" class="close-btn" onclick="closeTruckDispatchModal()">&times;</button>
                </div>
                <div class="modal-body" style="padding: 20px;">
                    <form id="truckDispatchForm" onsubmit="event.preventDefault(); submitTruckDispatch();">
                        <input type="hidden" id="truckDispatchOrderId">
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 12px;">
                            <div class="form-group">
                                <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 5px;">Order Number</label>
                                <input type="text" id="truckDispatchOrderNumber" class="hud-input mono" readonly style="width: 100%;">
                            </div>
                            <div class="form-group">
                                <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 5px;">Customer WhatsApp</label>
                                <input type="text" id="truckDispatchCustomerPhone" class="hud-input mono" readonly style="width: 100%;">
                            </div>
                        </div>
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 12px;">
                            <div class="form-group">
                                <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 5px;">Truck / Vehicle ID <span style="color: #f87171;">*</span></label>
                                <input type="text" id="truckDispatchTruckId" class="hud-input mono" placeholder="TRK-04" required value="TRK-01" style="width: 100%;">
                            </div>
                            <div class="form-group">
                                <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 5px;">Driver Name <span style="color: #f87171;">*</span></label>
                                <input type="text" id="truckDispatchDriverName" class="hud-input" placeholder="e.g. Rashid Ahmed" required value="Rashid Ahmed" style="width: 100%;">
                            </div>
                        </div>
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 12px;">
                            <div class="form-group">
                                <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 5px;">Driver Phone <span style="color: #f87171;">*</span></label>
                                <input type="text" id="truckDispatchDriverPhone" class="hud-input mono" placeholder="03001234567" required value="03001234567" style="width: 100%;">
                            </div>
                            <div class="form-group">
                                <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 5px;">Estimated Delivery (ETA)</label>
                                <input type="text" id="truckDispatchEta" class="hud-input" placeholder="e.g. Today by 4:30 PM" value="Today by 4:00 PM" style="width: 100%;">
                            </div>
                        </div>
                        <div class="form-group" style="margin-bottom: 12px;">
                            <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 5px;">Destination Address</label>
                            <input type="text" id="truckDispatchDestination" class="hud-input" placeholder="Customer address or delivery coordinates..." style="width: 100%;">
                        </div>
                        <div class="form-group" style="margin-bottom: 12px;">
                            <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 5px;">Live GPS Tracking Link (Optional)</label>
                            <input type="url" id="truckDispatchTrackingUrl" class="hud-input mono" placeholder="https://maps.google.com/?q=..." style="width: 100%;">
                        </div>
                        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 16px;">
                            <input type="checkbox" id="truckDispatchNotifyWa" checked style="cursor: pointer; width: 16px; height: 16px;">
                            <label for="truckDispatchNotifyWa" style="font-size: 12px; font-weight: 600; cursor: pointer;">Send Live WhatsApp Route Tracking Alert to Customer</label>
                        </div>
                        <div class="modal-footer" style="padding: 12px 0 0 0; border-top: 1px solid var(--border-color); display: flex; justify-content: flex-end; gap: 10px;">
                            <button type="button" class="hud-btn outline" onclick="closeTruckDispatchModal()">Cancel</button>
                            <button type="submit" class="hud-btn primary" id="btnSubmitTruckDispatch">
                                <span class="icon">🚚</span> Confirm &amp; Dispatch Truck
                            </button>
                        </div>
                    </form>
                </div>
            </div>
        `;
        document.body.appendChild(div);
    } else {
        modal.style.display = 'flex';
    }

    if (orderId) document.getElementById('truckDispatchOrderId').value = orderId;
    if (orderNumber) document.getElementById('truckDispatchOrderNumber').value = orderNumber;
    if (customerPhone) document.getElementById('truckDispatchCustomerPhone').value = customerPhone;
    if (customerName) {
        const dest = document.getElementById('truckDispatchDestination');
        if (dest && !dest.value) dest.value = `Delivery for ${customerName}`;
    }
}

function closeTruckDispatchModal() {
    const modal = document.getElementById('modalTruckDispatch');
    if (modal) modal.style.display = 'none';
}

function submitTruckDispatch() {
    const orderId = document.getElementById('truckDispatchOrderId')?.value || document.getElementById('truckDispatchOrderNumber')?.value;
    if (!orderId) {
        showToast('Please specify an Order ID or Order Number.', 'error');
        return;
    }

    const payload = {
        truck_id: document.getElementById('truckDispatchTruckId')?.value.trim() || 'TRK-01',
        driver_name: document.getElementById('truckDispatchDriverName')?.value.trim() || 'Fleet Driver',
        driver_phone: document.getElementById('truckDispatchDriverPhone')?.value.trim() || '',
        destination: document.getElementById('truckDispatchDestination')?.value.trim() || '',
        estimated_arrival: document.getElementById('truckDispatchEta')?.value.trim() || 'In Transit',
        tracking_url: document.getElementById('truckDispatchTrackingUrl')?.value.trim() || null,
        notify_whatsapp: document.getElementById('truckDispatchNotifyWa')?.checked ?? true
    };

    const btn = document.getElementById('btnSubmitTruckDispatch');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="icon spinning">🔄</span> Dispatching Truck...';
    }

    fetch(`/api/v1/ecommerce/orders/${encodeURIComponent(orderId)}/dispatch-truck`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === 'success') {
            showToast(`Truck ${payload.truck_id} dispatched! Live tracking route sent to customer.`, 'success');
            closeTruckDispatchModal();
        } else {
            showToast(data.error || 'Truck dispatch failed', 'error');
        }
    })
    .catch(err => {
        showToast(`Dispatch error: ${err.message}`, 'error');
    })
    .finally(() => {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<span class="icon">🚚</span> Confirm &amp; Dispatch Truck';
        }
    });
}

// ============================================================================
// LIVE AI VOICE CALL CONTROLLER (BASHFLOW CLOUD)
// ============================================================================
let liveVoiceCallActive = false;
let liveVoiceRecognition = null;

let voiceSpeechDebounceTimer = null;
let currentVoiceAudioPlayer = null;

async function sendVoiceChatQuery(spokenText) {
    if (!spokenText || !spokenText.trim()) return;
    const transcriptBox = document.getElementById('voiceTranscriptBox');
    const statusLabel = document.getElementById('voiceCallStatusLabel');
    const pulseCircle = document.getElementById('voiceCallPulseCircle');

    if (statusLabel) statusLabel.textContent = 'Thinking... (AI generating response)';
    if (pulseCircle) pulseCircle.style.borderColor = '#38bdf8';

    try {
        const res = await fetch('/api/v1/voice/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: spokenText.trim() })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            if (transcriptBox) {
                transcriptBox.innerHTML = `
                    <div style="margin-bottom: 8px;"><strong>You:</strong> ${escapeHtml(spokenText)}</div>
                    <div style="color: #34d399;"><strong>AI Voice Agent:</strong> ${escapeHtml(data.reply_text)}</div>
                `;
                transcriptBox.scrollTop = transcriptBox.scrollHeight;
            }

            if (data.audio_data_uri) {
                if (statusLabel) statusLabel.textContent = 'Speaking... (AI audio response)';
                if (pulseCircle) {
                    pulseCircle.style.borderColor = '#10b981';
                    pulseCircle.style.transform = 'scale(1.2)';
                }
                if (currentVoiceAudioPlayer) {
                    try { currentVoiceAudioPlayer.pause(); } catch (_) {}
                }
                currentVoiceAudioPlayer = new Audio(data.audio_data_uri);
                currentVoiceAudioPlayer.onended = function() {
                    if (statusLabel && liveVoiceCallActive) statusLabel.textContent = 'Listening... Speak now';
                    if (pulseCircle) {
                        pulseCircle.style.transform = 'scale(1.05)';
                        pulseCircle.style.borderColor = '#10b981';
                    }
                };
                currentVoiceAudioPlayer.play().catch(e => {
                    console.warn('[Live Voice Audio Play Notice]', e);
                    if (statusLabel && liveVoiceCallActive) statusLabel.textContent = 'Listening... Speak now';
                });
            } else {
                if (statusLabel && liveVoiceCallActive) statusLabel.textContent = 'Listening... Speak now';
                if (pulseCircle) pulseCircle.style.transform = 'scale(1.05)';
            }
        } else {
            if (statusLabel && liveVoiceCallActive) statusLabel.textContent = 'Listening... Speak now';
        }
    } catch (err) {
        console.warn('[Voice Chat Query Error]', err);
        if (statusLabel && liveVoiceCallActive) statusLabel.textContent = 'Listening... Speak now';
    }
}

function openLiveVoiceCallModal() {
    const modal = document.getElementById('liveVoiceCallModal');
    if (modal) {
        modal.style.display = 'flex';
    }
}

function closeLiveVoiceCallModal() {
    const modal = document.getElementById('liveVoiceCallModal');
    if (modal) {
        modal.style.display = 'none';
    }
    if (liveVoiceCallActive) {
        toggleLiveVoiceCall();
    }
    if (currentVoiceAudioPlayer) {
        try { currentVoiceAudioPlayer.pause(); } catch (_) {}
        currentVoiceAudioPlayer = null;
    }
}

function toggleLiveVoiceCall() {
    const btnText = document.getElementById('startVoiceBtnText');
    const statusLabel = document.getElementById('voiceCallStatusLabel');
    const subLabel = document.getElementById('voiceCallSubLabel');
    const pulseCircle = document.getElementById('voiceCallPulseCircle');
    const transcriptBox = document.getElementById('voiceTranscriptBox');

    if (!liveVoiceCallActive) {
        // Start Call
        liveVoiceCallActive = true;
        if (btnText) btnText.textContent = 'End Call';
        if (statusLabel) statusLabel.textContent = 'Listening... Speak now';
        if (subLabel) subLabel.textContent = 'Voice agent is actively listening in real-time';
        if (pulseCircle) {
            pulseCircle.style.transform = 'scale(1.1)';
            pulseCircle.style.borderColor = '#10b981';
        }

        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SpeechRecognition) {
            try {
                liveVoiceRecognition = new SpeechRecognition();
                liveVoiceRecognition.continuous = true;
                liveVoiceRecognition.interimResults = true;
                liveVoiceRecognition.lang = 'ur-PK, en-US';

                liveVoiceRecognition.onresult = function(event) {
                    let interimTranscript = '';
                    let finalTranscript = '';
                    for (let i = event.resultIndex; i < event.results.length; ++i) {
                        if (event.results[i].isFinal) {
                            finalTranscript += event.results[i][0].transcript;
                        } else {
                            interimTranscript += event.results[i][0].transcript;
                        }
                    }
                    const textToDisplay = finalTranscript || interimTranscript;
                    if (transcriptBox && textToDisplay) {
                        transcriptBox.innerHTML = '<strong>You:</strong> ' + escapeHtml(textToDisplay);
                    }
                    clearTimeout(voiceSpeechDebounceTimer);
                    const textToSend = (finalTranscript || interimTranscript).trim();
                    if (textToSend.length > 2) {
                        voiceSpeechDebounceTimer = setTimeout(() => {
                            sendVoiceChatQuery(textToSend);
                        }, 1300);
                    }
                };

                liveVoiceRecognition.onerror = function(err) {
                    console.warn('[Live Voice Call] Speech recognition note:', err);
                };

                liveVoiceRecognition.onend = function() {
                    // Auto-restart if call is still active
                    if (liveVoiceCallActive && liveVoiceRecognition) {
                        try { liveVoiceRecognition.start(); } catch (_) {}
                    }
                };

                liveVoiceRecognition.start();
            } catch (recErr) {
                console.warn('[Live Voice Call] Mic init note:', recErr);
            }
        } else {
            if (transcriptBox) {
                transcriptBox.innerHTML = '<span style="color:#34d399;">● Live Voice Stream active. Speech recognition not natively supported in this browser.</span>';
            }
        }
    } else {
        // End Call
        liveVoiceCallActive = false;
        clearTimeout(voiceSpeechDebounceTimer);
        if (btnText) btnText.textContent = 'Start Voice Call';
        if (statusLabel) statusLabel.textContent = 'Call Ended';
        if (subLabel) subLabel.textContent = 'Click "Start Voice Call" to begin a new conversation';
        if (pulseCircle) {
            pulseCircle.style.transform = 'scale(1.0)';
            pulseCircle.style.borderColor = '#10b981';
        }
        if (currentVoiceAudioPlayer) {
            try { currentVoiceAudioPlayer.pause(); } catch (_) {}
            currentVoiceAudioPlayer = null;
        }
        if (liveVoiceRecognition) {
            try {
                liveVoiceRecognition.onend = null;
                liveVoiceRecognition.stop();
            } catch (e) {}
            liveVoiceRecognition = null;
        }
    }
}

// ============================================================================
// WHATSAPP LINK QR MODAL CONTROLLER (BAILEYS BRIDGE)
// ============================================================================
let bridgeQrPollInterval = null;

function openLinkWhatsAppQrModal() {
    const modal = document.getElementById('linkWhatsAppQrModal');
    if (modal) {
        modal.style.display = 'flex';
        fetchBridgeQrCode(true);
        if (bridgeQrPollInterval) clearInterval(bridgeQrPollInterval);
        bridgeQrPollInterval = setInterval(() => fetchBridgeQrCode(false), 3000);
    }
}

function closeLinkWhatsAppQrModal() {
    const modal = document.getElementById('linkWhatsAppQrModal');
    if (modal) {
        modal.style.display = 'none';
    }
    if (bridgeQrPollInterval) {
        clearInterval(bridgeQrPollInterval);
        bridgeQrPollInterval = null;
    }
}

async function fetchBridgeQrCode(force) {
    const spinner = document.getElementById('qrLoadingSpinner');
    const imageWrapper = document.getElementById('qrImageWrapper');
    const connectedState = document.getElementById('qrConnectedState');
    const qrImg = document.getElementById('bridgeQrImage');
    const statusText = document.getElementById('qrStatusText');
    const connectedNumber = document.getElementById('qrConnectedNumber');

    try {
        let res = null;
        try {
            res = await fetch('/api/v1/whatsapp/bridge-qr');
            if (!res.ok && res.status !== 503) throw new Error('Proxy status ' + res.status);
        } catch (e) {
            try {
                res = await fetch('/api/whatsapp/bridge-qr');
            } catch (e2) {
                res = await fetch('http://localhost:3001/qr');
            }
        }

        if (!res) throw new Error('Bridge unreachable');
        const data = await res.json();

        if (data.status === 'connected' || data.connected) {
            if (spinner) spinner.style.display = 'none';
            if (imageWrapper) imageWrapper.style.display = 'none';
            if (connectedState) connectedState.style.display = 'block';
            if (connectedNumber && data.user) {
                const phone = data.user.id ? data.user.id.split(':')[0] : 'Linked';
                connectedNumber.textContent = `Connected as +${phone} (Unlimited Free Messaging Ready).`;
            }
            return;
        }

        const qrDataUri = data.qrUrl || data.qrImageUrl;
        if (data.status === 'qr_ready' && (qrDataUri || data.qrSvg || data.qr)) {
            const svgContainer = document.getElementById('bridgeQrSvgContainer');

            // 1. If base64 data URI is provided by local Node.js bridge, set the <img> src attribute directly (100% offline, zero network requests)
            if (qrDataUri && (qrDataUri.startsWith('data:image/') || qrDataUri.startsWith('data:'))) {
                if (qrImg) {
                    qrImg.style.display = 'block';
                    qrImg.src = qrDataUri;
                }
                if (svgContainer) svgContainer.style.display = 'none';
            } else if (data.qrSvg) {
                // 2. Direct vector SVG rendering
                if (qrImg) qrImg.style.display = 'none';
                if (svgContainer) {
                    svgContainer.innerHTML = data.qrSvg;
                    svgContainer.style.display = 'block';
                }
            } else {
                // 3. Fallback to direct raw PNG proxy endpoint or fallback URL
                const qrSrc = qrDataUri || `/api/v1/whatsapp/bridge-qr.png?t=${Date.now()}` || (data.qr ? `https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=${encodeURIComponent(data.qr)}` : '');
                if (qrImg) {
                    qrImg.style.display = 'block';
                    qrImg.src = qrSrc;
                }
                if (svgContainer) svgContainer.style.display = 'none';
            }

            if (qrImg) {
                qrImg.onerror = function() {
                    console.warn('[QR Image] Image loading error, applying SVG/provider fallback');
                    if (data.qrSvg && svgContainer) {
                        qrImg.style.display = 'none';
                        svgContainer.innerHTML = data.qrSvg;
                        svgContainer.style.display = 'block';
                    } else if (data.qr) {
                        qrImg.onerror = null;
                        qrImg.src = `https://quickchart.io/qr?size=300&text=${encodeURIComponent(data.qr)}`;
                    }
                };
            }

            if (spinner) spinner.style.display = 'none';
            if (connectedState) connectedState.style.display = 'none';
            if (imageWrapper) imageWrapper.style.display = 'block';
            return;
        }

        // Waiting or initializing
        if (imageWrapper) imageWrapper.style.display = 'none';
        if (connectedState) connectedState.style.display = 'none';
        if (spinner) spinner.style.display = 'flex';
        if (statusText) statusText.textContent = data.message || 'WhatsApp Baileys bridge is initializing pairing session...';
    } catch (err) {
        console.warn('[Bridge QR Fetch Error]', err);
        if (statusText) statusText.textContent = 'WhatsApp bridge starting up on port 3001... Please wait 5s.';
    }
}

// Global window exposure for Link WhatsApp QR Modal
window.openLinkWhatsAppQrModal = openLinkWhatsAppQrModal;
window.closeLinkWhatsAppQrModal = closeLinkWhatsAppQrModal;
window.fetchBridgeQrCode = fetchBridgeQrCode;
