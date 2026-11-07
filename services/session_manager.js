/**
 * Multi-Tenant WhatsApp Baileys Session & Connection Pool Manager
 * -------------------------------------------------------------
 * Eliminates the single-socket / singleton auth directory bottleneck (Audit Area 15).
 * Enables concurrent WhatsApp sessions for multiple B2B SaaS businesses/tenants.
 */

const path = require('path');
const fs = require('fs');

/**
 * Resolves the base root directory for all Baileys authentication state.
 * Detects persistent disk mount paths on container hosts or uses local directory.
 */
function resolveBaseAuthDir() {
  if (process.env.AUTH_DIR && process.env.AUTH_DIR.trim()) {
    return path.resolve(process.env.AUTH_DIR.trim());
  }
  const candidateMounts = [
    process.env.RENDER_DISK_PATH,
    process.env.PERSISTENT_DATA_DIR,
    '/var/data',
    '/data',
    '/mnt/data',
    '/opt/render/project/src/baileys_auth'
  ].filter(Boolean);

  for (const mount of candidateMounts) {
    try {
      if (fs.existsSync(mount)) {
        const candidateAuth = mount.endsWith('baileys_auth') ? mount : path.join(mount, 'baileys_auth');
        return candidateAuth;
      }
    } catch (_) {}
  }
  return path.join(__dirname, '..', 'baileys_auth');
}

/**
 * Resolves an isolated authentication storage directory for a specific tenant.
 * Guarantees zero cross-contamination of WhatsApp cryptographic keys between businesses.
 */
function resolveTenantAuthDir(baseDir, tenantId) {
  const cleanTenant = (tenantId || 'default').toString().trim().replace(/[^a-zA-Z0-9_\-\.]/g, '_');
  
  // Backward compatibility: If tenantId is 'default' and baseDir directly contains creds.json,
  // continue using baseDir so existing single-tenant sessions are preserved without re-scanning QR.
  if (cleanTenant === 'default') {
    const legacyCreds = path.join(baseDir, 'creds.json');
    if (fs.existsSync(legacyCreds)) {
      return baseDir;
    }
    const tenantDefault = path.join(baseDir, 'tenant_default');
    if (fs.existsSync(tenantDefault)) {
      return tenantDefault;
    }
    return baseDir;
  }

  // Tenant-isolated directory: <baseDir>/tenant_<tenantId>
  const tenantDir = path.join(baseDir, `tenant_${cleanTenant}`);
  if (!fs.existsSync(tenantDir)) {
    fs.mkdirSync(tenantDir, { recursive: true });
  }
  return tenantDir;
}

/**
 * Validates whether an authentication directory holds a linked, verified WhatsApp session.
 */
function isAuthenticatedCreds(dir) {
  try {
    const credsPath = path.join(dir, 'creds.json');
    if (!fs.existsSync(credsPath) || fs.statSync(credsPath).size < 100) return false;
    const creds = JSON.parse(fs.readFileSync(credsPath, 'utf8'));
    const hasNoise = Boolean(creds && creds.noiseKey && (creds.noiseKey.private || creds.noiseKey.public));
    const hasKeys = Boolean(creds && (creds.signedIdentityKey || creds.signedPreKey));
    const hasMeOrReg = Boolean(creds && (creds.registered === true || (creds.me && creds.me.id)));
    return Boolean(hasNoise && hasKeys && hasMeOrReg);
  } catch (_) {
    return false;
  }
}

/**
 * Represents an isolated WhatsApp session instance for a single tenant / business.
 */
class TenantSession {
  constructor(tenantId, authDir) {
    this.tenantId = (tenantId || 'default').toString().trim();
    this.authDir = authDir;
    this.sock = null;
    this.isConnected = false;
    this.isStarting = false;
    this.currentQr = null;
    this.currentQrUrl = null;
    this.currentQrSvg = null;
    this.latestQr = null;
    this.latestQrDataUrl = null;
    this.lastQrGeneratedTime = 0;
    this.authenticatedUserPhone = null;
    this.authenticatedUserLid = null;
    this.reconnectTimer = null;
    this.reconnectAttempts = 0;
    this.lastRestartTriggerTime = 0;
    this.outboundDispatchTimestamps = [];
    this.contactNamesMap = new Map();
    this.groupSubjectsMap = new Map();
    this.activeChatsMap = new Map();
    this.lidToPhoneMap = new Map();
    this.phoneToLidMap = new Map();
    this.sessionBackupDebounce = null;
    this.createdAt = new Date();
  }

  /**
   * Returns true only if this tenant's Baileys socket is actively open and authenticated.
   */
  isGenuinelyConnected() {
    return Boolean(
      this.sock &&
      this.sock.user &&
      this.sock.user.id &&
      this.isConnected &&
      (this.sock.ws?.isOpen === true || this.sock.ws?.readyState === 1)
    );
  }

  /**
   * Returns the clean international phone number linked to this tenant's session.
   */
  getPhone() {
    if (this.sock?.user?.id) {
      return this.sock.user.id.split(':')[0].replace(/\D/g, '');
    }
    return this.authenticatedUserPhone || null;
  }

  /**
   * Safely terminates this tenant's socket connection and event listeners without affecting others.
   */
  destroySocket() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.sock) {
      try {
        if (this.sock.ev && typeof this.sock.ev.removeAllListeners === 'function') {
          this.sock.ev.removeAllListeners();
        }
        if (this.sock.ws && typeof this.sock.ws.close === 'function') {
          this.sock.ws.close();
        }
        if (typeof this.sock.end === 'function') {
          this.sock.end(undefined);
        }
      } catch (_) {}
      this.sock = null;
    }
    this.isConnected = false;
    this.isStarting = false;
  }

  /**
   * Diagnostic summary representation for API consumers.
   */
  getStatus() {
    const genuinelyConnected = this.isGenuinelyConnected();
    return {
      tenant_id: this.tenantId,
      connected: this.isConnected || Boolean(this.sock?.user),
      genuinelyConnected: genuinelyConnected,
      isConnecting: this.isStarting && !this.isConnected,
      hasQr: Boolean(this.latestQrDataUrl || this.currentQr),
      qr: this.latestQrDataUrl || this.currentQrUrl || null,
      phone: this.getPhone(),
      user: genuinelyConnected ? (this.sock?.user || null) : null,
      reconnectAttempts: this.reconnectAttempts,
      authDir: this.authDir
    };
  }
}

/**
 * Multi-Tenant WhatsApp Session Connection Pool
 */
class SessionPool {
  constructor(baseAuthDir = null) {
    this.baseAuthDir = baseAuthDir || resolveBaseAuthDir();
    this.sessions = new Map(); // tenantId -> TenantSession
  }

  /**
   * Resolves auth dir path for a tenant.
   */
  resolveAuthDir(tenantId) {
    return resolveTenantAuthDir(this.baseAuthDir, tenantId);
  }

  /**
   * Retrieves an existing session or provisions a new isolated TenantSession.
   */
  getOrCreateSession(tenantId) {
    const cleanTenant = (tenantId || 'default').toString().trim();
    if (!this.sessions.has(cleanTenant)) {
      const authDir = this.resolveAuthDir(cleanTenant);
      const session = new TenantSession(cleanTenant, authDir);
      this.sessions.set(cleanTenant, session);
    }
    return this.sessions.get(cleanTenant);
  }

  /**
   * Gets an existing tenant session, or null if none registered.
   */
  getSession(tenantId) {
    const cleanTenant = (tenantId || 'default').toString().trim();
    return this.sessions.get(cleanTenant) || null;
  }

  /**
   * Checks if a tenant session is registered in the pool.
   */
  hasSession(tenantId) {
    const cleanTenant = (tenantId || 'default').toString().trim();
    return this.sessions.has(cleanTenant);
  }

  /**
   * Returns status summaries of all active sessions in the pool.
   */
  getAllSessions() {
    return Array.from(this.sessions.values()).map(s => s.getStatus());
  }

  /**
   * Terminates and removes a specific tenant session from the pool.
   */
  destroySession(tenantId) {
    const cleanTenant = (tenantId || 'default').toString().trim();
    const session = this.sessions.get(cleanTenant);
    if (session) {
      session.destroySocket();
      this.sessions.delete(cleanTenant);
      return true;
    }
    return false;
  }

  /**
   * Helper to extract tenant_id / organization_id from an incoming Express request.
   */
  extractTenantId(req) {
    if (!req) return 'default';
    const candidate =
      req.query?.tenant_id ||
      req.query?.tenantId ||
      req.query?.sessionId ||
      req.query?.org_id ||
      req.headers?.['x-tenant-id'] ||
      req.headers?.['x-organization-id'] ||
      req.body?.tenant_id ||
      req.body?.tenantId ||
      req.body?.sessionId ||
      req.body?.organization_id ||
      process.env.TENANT_ID ||
      'default';
    return String(candidate).trim() || 'default';
  }
}

// Singleton pool instance export
const sessionPool = new SessionPool();

module.exports = {
  TenantSession,
  SessionPool,
  sessionPool,
  resolveBaseAuthDir,
  resolveTenantAuthDir,
  isAuthenticatedCreds
};
