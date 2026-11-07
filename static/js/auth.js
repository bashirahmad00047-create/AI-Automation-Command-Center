/**
 * BashFlow Cloud - Authentication & Tenancy Module (auth.js)
 * Phase 7: Frontend Decoupling & Modularization
 * Handles: Session state, tenant switching, auth modals, login/register/logout flows.
 */

(function(window, document) {
    'use strict';

    const BashFlowAuth = {
        state: {
            currentUser: null,
            currentOrg: null,
            userRole: 'guest',
            organizations: []
        },

        async init() {
            return this.initAuthAndTenancy();
        },

        async initAuthAndTenancy() {
            try {
                const res = await fetch('/api/v1/auth/me');
                if (res.ok) {
                    const data = await res.json();
                    this.state.currentUser = data.user;
                    this.state.currentOrg = data.current_organization || data.organization;
                    this.state.userRole = data.role || 'admin';
                    const activeOrgId = this.state.currentOrg?.id || 'org-enterprise-default';
                    window._currentOrgId = activeOrgId;
                    try { localStorage.setItem('selectedOrgId', activeOrgId); } catch (_) {}

                    if (window.state) {
                        window.state.currentUser = this.state.currentUser;
                        window.state.currentOrg = this.state.currentOrg;
                        window.state.userRole = this.state.userRole;
                    }

                    this.updateUserBadgeUI();
                    this.updateAuthHeaderUI(true);
                    this.closeAuthModal(true);
                    await this.loadOrganizationsList();
                    return data;
                } else if (res.status === 401 || res.status === 403) {
                    this.state.currentUser = null;
                    this.state.currentOrg = null;
                    this.state.userRole = 'guest';
                    if (window.state) {
                        window.state.currentUser = null;
                        window.state.currentOrg = null;
                        window.state.userRole = 'guest';
                    }
                    this.updateUserBadgeUI();
                    this.updateAuthHeaderUI(false);
                }
            } catch (err) {
                console.warn('[BashFlowAuth] initAuthAndTenancy notice:', err.message);
            }
            return null;
        },

        updateAuthHeaderUI(isLoggedIn) {
            const userMenuBtn = document.getElementById('userMenuBtn');
            const authLoginBtn = document.getElementById('authLoginBtn');
            const userRoleBadge = document.getElementById('userRoleBadge');
            const currentOrgName = document.getElementById('currentOrgName');

            if (isLoggedIn && this.state.currentUser) {
                if (authLoginBtn) authLoginBtn.style.display = 'none';
                if (userMenuBtn) userMenuBtn.style.display = 'flex';
                const userNameEl = document.getElementById('topbarUserName');
                if (userNameEl) {
                    userNameEl.textContent = this.state.currentUser.full_name || this.state.currentUser.email || 'Operator';
                }
                if (userRoleBadge) {
                    userRoleBadge.textContent = (this.state.userRole || 'admin').toUpperCase();
                }
                if (currentOrgName && this.state.currentOrg) {
                    currentOrgName.textContent = this.state.currentOrg.name || 'Default Workspace';
                }
            } else {
                if (authLoginBtn) authLoginBtn.style.display = 'flex';
                if (userMenuBtn) userMenuBtn.style.display = 'none';
                if (userRoleBadge) userRoleBadge.textContent = 'GUEST';
            }
        },

        updateUserBadgeUI() {
            const badge = document.getElementById('currentUserBadge');
            if (!badge) return;
            if (this.state.currentUser) {
                badge.textContent = this.state.currentUser.full_name || this.state.currentUser.email || 'User';
                badge.title = `Signed in as ${this.state.currentUser.email} (${this.state.userRole})`;
            } else {
                badge.textContent = 'Sign In';
                badge.title = 'Not signed in';
            }
        },

        async loadOrganizationsList() {
            try {
                const res = await fetch('/api/v1/organizations');
                if (res.ok) {
                    const data = await res.json();
                    this.state.organizations = data.organizations || data || [];
                    this.renderOrgSelector();
                }
            } catch (e) {
                console.warn('[BashFlowAuth] loadOrganizationsList notice:', e.message);
            }
        },

        renderOrgSelector() {
            const select = document.getElementById('workspaceSelect');
            if (!select || !Array.isArray(this.state.organizations)) return;
            select.innerHTML = '';
            this.state.organizations.forEach(org => {
                const opt = document.createElement('option');
                opt.value = org.id;
                opt.textContent = org.name;
                if (this.state.currentOrg && this.state.currentOrg.id === org.id) {
                    opt.selected = true;
                }
                select.appendChild(opt);
            });
        },

        async switchOrganization(orgId) {
            try {
                const res = await fetch(`/api/v1/organizations/switch/${orgId}`, { method: 'POST' });
                if (res.ok) {
                    window.location.reload();
                }
            } catch (err) {
                console.error('[BashFlowAuth] switchOrganization error:', err);
            }
        },

        openAuthModal(tab = 'login') {
            const modal = document.getElementById('authModal');
            if (modal) {
                modal.style.display = 'flex';
                this.switchAuthTab(tab);
            }
        },

        closeAuthModal(force = false) {
            const modal = document.getElementById('authModal');
            if (modal) modal.style.display = 'none';
        },

        switchAuthTab(tab) {
            const loginForm = document.getElementById('loginForm');
            const registerForm = document.getElementById('registerForm');
            const forgotForm = document.getElementById('forgotPasswordForm');
            const tabLogin = document.getElementById('authTabLogin');
            const tabRegister = document.getElementById('authTabRegister');

            ['loginErrorMessage', 'registerErrorMessage', 'forgotErrorMessage'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.style.display = 'none';
            });

            if (loginForm) loginForm.style.display = tab === 'login' ? 'block' : 'none';
            if (registerForm) registerForm.style.display = tab === 'register' ? 'block' : 'none';
            if (forgotForm) forgotForm.style.display = tab === 'forgot' ? 'block' : 'none';

            if (tabLogin) tabLogin.classList.toggle('active', tab === 'login');
            if (tabRegister) tabRegister.classList.toggle('active', tab === 'register');
        },

        async handleLogin(e) {
            if (e && e.preventDefault) e.preventDefault();
            const email = (document.getElementById('loginEmail')?.value || '').trim();
            const password = document.getElementById('loginPassword')?.value || '';
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
                    this.closeAuthModal(true);
                    if (typeof showToast === 'function') {
                        showToast(`Welcome back, ${data.user ? data.user.full_name : 'Operator'}!`, 'success');
                    }
                    await this.initAuthAndTenancy();
                    if (typeof refreshAllData === 'function') refreshAllData();
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
        },

        async handleRegister(e) {
            if (e && e.preventDefault) e.preventDefault();
            const full_name = (document.getElementById('regFullName')?.value || '').trim();
            const email = (document.getElementById('regEmail')?.value || '').trim();
            const password = document.getElementById('regPassword')?.value || '';
            let organization_name = (document.getElementById('regOrgName')?.value || '').trim();
            if (!organization_name) organization_name = full_name ? `${full_name}'s Workspace` : 'Primary Workspace';
            const organization_slug = (document.getElementById('regOrgSlug')?.value || '').trim() ||
                organization_name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
            const plan_tier = document.getElementById('regPlanTier')?.value || 'free';
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
                        organization_slug,
                        plan_tier
                    })
                });
                const data = await res.json();
                if (res.ok) {
                    this.closeAuthModal(true);
                    if (typeof showToast === 'function') {
                        showToast(`Account created successfully! Welcome, ${full_name || 'Operator'}!`, 'success');
                    }
                    await this.initAuthAndTenancy();
                    if (typeof refreshAllData === 'function') refreshAllData();
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
        },

        async handleLogout() {
            try {
                await fetch('/logout', { method: 'POST', headers: { 'Accept': 'application/json' } });
            } catch (e) {
                console.error('[BashFlowAuth] Logout notice:', e);
            }
            this.state.currentUser = null;
            this.state.currentOrg = null;
            this.state.userRole = 'guest';
            if (window.state) {
                window.state.currentUser = null;
                window.state.currentOrg = null;
                window.state.userRole = 'guest';
            }
            this.updateUserBadgeUI();
            this.updateAuthHeaderUI(false);
            window.location.href = '/login';
        }
    };

    // Expose module globally and bind legacy function signatures
    BashFlowAuth.getEffectiveOrgId = function() {
        return this.state.currentOrg?.id ||
            window.state?.currentOrg?.id ||
            window.state?.currentUser?.organization_id ||
            window._currentOrgId ||
            (function() { try { return localStorage.getItem('selectedOrgId'); } catch (_) { return null; } })() ||
            'org-enterprise-default';
    };
    window.BashFlowAuth = BashFlowAuth;
    window.getEffectiveOrgId = () => BashFlowAuth.getEffectiveOrgId();
    window.initAuthAndTenancy = () => BashFlowAuth.initAuthAndTenancy();
    window.updateAuthHeaderUI = (isLoggedIn) => BashFlowAuth.updateAuthHeaderUI(isLoggedIn);
    window.updateUserBadgeUI = () => BashFlowAuth.updateUserBadgeUI();
    window.loadOrganizationsList = () => BashFlowAuth.loadOrganizationsList();
    window.closeAuthModal = (force) => BashFlowAuth.closeAuthModal(force);
    window.switchAuthTab = (tab) => BashFlowAuth.switchAuthTab(tab);
    window.handleLogin = (e) => BashFlowAuth.handleLogin(e);
    window.handleRegister = (e) => BashFlowAuth.handleRegister(e);
    window.handleLogout = () => BashFlowAuth.handleLogout();

})(window, document);
