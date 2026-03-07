"use client";

import { useEffect, useMemo, useState } from "react";

const RAW_API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";
const DEFAULT_API_BASE = "https://deck-check.onrender.com";
const AUTH_CSRF_STORAGE_KEY = "deckcheck.csrf";

function sanitizeApiBase(raw: string): string {
  const trimmed = raw.trim().replace(/^[\s'"]+|[\s'"]+$/g, "");
  const match = trimmed.match(/https?:\/\/[^\s'"]+/i);
  return (match ? match[0] : trimmed).replace(/\/+$/g, "");
}

const API_BASE = sanitizeApiBase(RAW_API_BASE);

function apiUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const base =
    API_BASE ||
    (typeof window !== "undefined" && window.location.hostname.endsWith("netlify.app")
      ? DEFAULT_API_BASE
      : "");
  if (!base) return normalized;
  return `${base}${normalized}`;
}

type SessionUser = {
  id: number;
  email: string;
  is_admin?: boolean;
  role?: string;
  status?: string;
  plan?: string;
};

type SessionResponse = {
  authenticated: boolean;
  user: SessionUser | null;
  csrf_token?: string | null;
};

type AdminProblem = {
  id: number;
  level: string;
  source: string;
  category: string;
  message: string;
  detail?: string | null;
  path?: string | null;
  request_id?: string | null;
  user_id?: number | null;
  user_email?: string | null;
  context?: Record<string, unknown>;
  created_at: string;
  copy_blob: string;
};

type AdminSystemCheck = {
  key: string;
  label: string;
  status: string;
  message: string;
  latency_ms?: number | null;
  detail?: string | null;
  meta?: Record<string, unknown>;
};

type AdminUser = {
  id: number;
  email: string;
  role: string;
  status: string;
  plan: string;
  admin_notes?: string | null;
  is_protected_admin: boolean;
  created_at: string;
  updated_at: string;
  last_login_at?: string | null;
  project_count: number;
  version_count: number;
  active_session_count: number;
};

type UserDraft = {
  role: string;
  status: string;
  plan: string;
  admin_notes: string;
};

const ADMIN_TABS = [
  { key: "problems", label: "Problems" },
  { key: "systems", label: "API & Systems" },
  { key: "users", label: "User Management" },
] as const;

export default function AdminPage() {
  const [authChecked, setAuthChecked] = useState(false);
  const [authUser, setAuthUser] = useState<SessionUser | null>(null);
  const [csrfToken, setCsrfToken] = useState("");
  const [tab, setTab] = useState<(typeof ADMIN_TABS)[number]["key"]>("problems");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const [problems, setProblems] = useState<AdminProblem[]>([]);
  const [problemsLoading, setProblemsLoading] = useState(false);

  const [systemChecks, setSystemChecks] = useState<AdminSystemCheck[]>([]);
  const [systemsCheckedAt, setSystemsCheckedAt] = useState("");
  const [systemsLoading, setSystemsLoading] = useState(false);

  const [users, setUsers] = useState<AdminUser[]>([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [userDraft, setUserDraft] = useState<UserDraft>({ role: "user", status: "active", plan: "free", admin_notes: "" });
  const [savingUser, setSavingUser] = useState(false);

  const selectedUser = useMemo(
    () => users.find((row) => row.id === selectedUserId) || null,
    [users, selectedUserId],
  );

  function persistCsrfToken(next: string) {
    setCsrfToken(next || "");
    if (typeof window === "undefined") return;
    if (next) window.localStorage.setItem(AUTH_CSRF_STORAGE_KEY, next);
    else window.localStorage.removeItem(AUTH_CSRF_STORAGE_KEY);
  }

  async function requestJson(path: string, init?: RequestInit, label?: string) {
    const response = await fetch(apiUrl(path), {
      credentials: "include",
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.headers || {}),
      },
    });
    const text = await response.text();
    let payload: any = {};
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      payload = text ? { detail: text } : {};
    }
    if (!response.ok) {
      throw new Error(payload?.detail || payload?.message || `${label || "Request"} failed (${response.status})`);
    }
    return payload;
  }

  async function loadSession() {
    setError("");
    try {
      const payload = (await requestJson("/api/auth/session", { method: "GET" }, "Session")) as SessionResponse;
      persistCsrfToken(payload.csrf_token || "");
      setAuthUser(payload.user || null);
    } catch (exc: any) {
      setError(String(exc?.message || exc));
    } finally {
      setAuthChecked(true);
    }
  }

  async function loadProblems() {
    if (!authUser?.is_admin) return;
    setProblemsLoading(true);
    setError("");
    try {
      const payload = await requestJson("/api/admin/problems?limit=150", { method: "GET" }, "Problems");
      setProblems(payload.problems || []);
    } catch (exc: any) {
      setError(String(exc?.message || exc));
    } finally {
      setProblemsLoading(false);
    }
  }

  async function loadSystems() {
    if (!authUser?.is_admin) return;
    setSystemsLoading(true);
    setError("");
    try {
      const payload = await requestJson("/api/admin/systems", { method: "GET" }, "Systems");
      setSystemChecks(payload.checks || []);
      setSystemsCheckedAt(payload.checked_at || "");
    } catch (exc: any) {
      setError(String(exc?.message || exc));
    } finally {
      setSystemsLoading(false);
    }
  }

  async function loadUsers() {
    if (!authUser?.is_admin) return;
    setUsersLoading(true);
    setError("");
    try {
      const payload = await requestJson("/api/admin/users", { method: "GET" }, "Users");
      const nextUsers = payload.users || [];
      setUsers(nextUsers);
      setSelectedUserId((current) => current ?? nextUsers[0]?.id ?? null);
    } catch (exc: any) {
      setError(String(exc?.message || exc));
    } finally {
      setUsersLoading(false);
    }
  }

  async function runUpdateData() {
    setNotice("");
    setError("");
    try {
      await requestJson(
        "/api/admin/update-data",
        {
          method: "POST",
          headers: {
            "X-CSRF-Token": csrfToken || (typeof window !== "undefined" ? window.localStorage.getItem(AUTH_CSRF_STORAGE_KEY) || "" : ""),
          },
        },
        "Data refresh",
      );
      setNotice("Data refresh triggered.");
      await loadSystems();
    } catch (exc: any) {
      setError(String(exc?.message || exc));
    }
  }

  async function saveUser() {
    if (!selectedUser) return;
    setSavingUser(true);
    setNotice("");
    setError("");
    try {
      const payload = await requestJson(
        `/api/admin/users/${selectedUser.id}`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken || (typeof window !== "undefined" ? window.localStorage.getItem(AUTH_CSRF_STORAGE_KEY) || "" : ""),
          },
          body: JSON.stringify(userDraft),
        },
        "User update",
      );
      setUsers((current) => current.map((row) => (row.id === payload.id ? payload : row)));
      setNotice(`Updated ${payload.email}.`);
    } catch (exc: any) {
      setError(String(exc?.message || exc));
    } finally {
      setSavingUser(false);
    }
  }

  async function copyProblem(entry: AdminProblem) {
    try {
      await navigator.clipboard.writeText(entry.copy_blob || "");
      setNotice(`Copied problem ${entry.id}.`);
      setError("");
    } catch {
      setError("Copy failed.");
    }
  }

  useEffect(() => {
    void loadSession();
  }, []);

  useEffect(() => {
    if (!authUser?.is_admin) return;
    if (tab === "problems" && !problems.length && !problemsLoading) void loadProblems();
    if (tab === "systems" && !systemChecks.length && !systemsLoading) void loadSystems();
    if (tab === "users" && !users.length && !usersLoading) void loadUsers();
  }, [authUser, tab]);

  useEffect(() => {
    if (!selectedUser) return;
    setUserDraft({
      role: selectedUser.role || "user",
      status: selectedUser.status || "active",
      plan: selectedUser.plan || "free",
      admin_notes: selectedUser.admin_notes || "",
    });
  }, [selectedUser]);

  if (!authChecked) {
    return (
      <main className="admin-shell">
        <div className="admin-empty">Checking admin session…</div>
      </main>
    );
  }

  if (!authUser?.is_admin) {
    return (
      <main className="admin-shell">
        <header className="admin-header">
          <div>
            <div className="panel-kicker">Admin</div>
            <h1>Restricted</h1>
            <p className="control-help">This console is available only to configured admin accounts.</p>
          </div>
          <a className="btn" href="/">Back to Deck.Check</a>
        </header>
      </main>
    );
  }

  return (
    <main className="admin-shell">
      <header className="admin-header">
        <div>
          <div className="panel-kicker">Admin</div>
          <h1>Operations Console</h1>
          <p className="control-help">Protected admin access for problem review, system checks, and account control.</p>
        </div>
        <div className="admin-header-actions">
          <span className="saved-project-pill is-current">{authUser.email}</span>
          <a className="btn" href="/">Back to Deck.Check</a>
        </div>
      </header>

      <div className="admin-tabs" role="tablist" aria-label="Admin sections">
        {ADMIN_TABS.map((tabOption) => (
          <button
            key={tabOption.key}
            type="button"
            className={`btn tab-btn ${tab === tabOption.key ? "active" : ""}`}
            onClick={() => setTab(tabOption.key)}
            aria-pressed={tab === tabOption.key}
          >
            {tabOption.label}
          </button>
        ))}
      </div>

      {notice ? <p className="import-notice" data-tone="success">{notice}</p> : null}
      {error ? <p className="import-notice" data-tone="danger">{error}</p> : null}

      {tab === "problems" ? (
        <section className="admin-panel">
          <div className="admin-panel-header">
            <div>
              <h2>Problems</h2>
              <p className="control-help">Unhandled exceptions, validation failures, and worker task crashes across all users.</p>
            </div>
            <button type="button" className="btn" onClick={() => void loadProblems()} disabled={problemsLoading}>
              {problemsLoading ? "Refreshing…" : "Refresh"}
            </button>
          </div>
          <div className="admin-problems-list">
            {problems.map((entry) => (
              <article key={entry.id} className="admin-problem-entry">
                <div className="admin-problem-topline">
                  <div className="admin-problem-meta">
                    <strong>#{entry.id}</strong>
                    <span>{new Date(entry.created_at).toLocaleString()}</span>
                    <span className={`saved-project-pill admin-status-pill tone-${entry.level}`}>{entry.level}</span>
                    <span>{entry.source}/{entry.category}</span>
                    {entry.user_email ? <span>{entry.user_email}</span> : null}
                    {entry.path ? <span>{entry.path}</span> : null}
                  </div>
                  <button type="button" className="btn" onClick={() => void copyProblem(entry)}>Copy entry</button>
                </div>
                <div className="admin-problem-message">{entry.message}</div>
                <textarea className="admin-problem-copyblob" readOnly value={entry.copy_blob} />
              </article>
            ))}
            {!problems.length && !problemsLoading ? <p className="control-help">No captured problems yet.</p> : null}
          </div>
        </section>
      ) : null}

      {tab === "systems" ? (
        <section className="admin-panel">
          <div className="admin-panel-header">
            <div>
              <h2>API & Systems</h2>
              <p className="control-help">Live reachability checks across the connected services Deck.Check depends on.</p>
            </div>
            <div className="admin-header-actions">
              <button type="button" className="btn" onClick={() => void runUpdateData()}>Refresh data sources</button>
              <button type="button" className="btn" onClick={() => void loadSystems()} disabled={systemsLoading}>
                {systemsLoading ? "Checking…" : "Run checks"}
              </button>
            </div>
          </div>
          {systemsCheckedAt ? <p className="control-help">Last checked {new Date(systemsCheckedAt).toLocaleString()}.</p> : null}
          <div className="admin-systems-grid">
            {systemChecks.map((check) => (
              <article key={check.key} className="admin-system-card">
                <div className="admin-system-topline">
                  <strong>{check.label}</strong>
                  <span className={`saved-project-pill admin-status-pill tone-${check.status}`}>{check.status}</span>
                </div>
                <div className="admin-system-message">{check.message}</div>
                {typeof check.latency_ms === "number" ? <div className="control-help">Latency: {check.latency_ms} ms</div> : null}
                {check.detail ? <pre className="admin-pre">{check.detail}</pre> : null}
                {check.meta && Object.keys(check.meta).length ? <pre className="admin-pre">{JSON.stringify(check.meta, null, 2)}</pre> : null}
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {tab === "users" ? (
        <section className="admin-panel">
          <div className="admin-panel-header">
            <div>
              <h2>User Management</h2>
              <p className="control-help">Lightweight account control with room for future plan and token administration.</p>
            </div>
            <button type="button" className="btn" onClick={() => void loadUsers()} disabled={usersLoading}>
              {usersLoading ? "Refreshing…" : "Refresh"}
            </button>
          </div>
          <div className="admin-users-layout">
            <div className="admin-user-list">
              {users.map((user) => (
                <button
                  key={user.id}
                  type="button"
                  className={`admin-user-row ${selectedUserId === user.id ? "active" : ""}`}
                  onClick={() => setSelectedUserId(user.id)}
                >
                  <div className="admin-user-row-top">
                    <strong>{user.email}</strong>
                    {user.is_protected_admin ? <span className="saved-project-pill is-current">Protected admin</span> : null}
                  </div>
                  <div className="saved-project-pills">
                    <span className="saved-project-pill">{user.role}</span>
                    <span className="saved-project-pill">{user.status}</span>
                    <span className="saved-project-pill">{user.plan}</span>
                    <span className="saved-project-pill">{user.project_count} decks</span>
                    <span className="saved-project-pill">{user.version_count} versions</span>
                  </div>
                </button>
              ))}
            </div>
            <div className="admin-user-editor">
              {selectedUser ? (
                <>
                  <div className="account-section-intro">
                    <strong>{selectedUser.email}</strong>
                    <span>Created {new Date(selectedUser.created_at).toLocaleString()} · last login {selectedUser.last_login_at ? new Date(selectedUser.last_login_at).toLocaleString() : "never"}.</span>
                  </div>
                  <div className="admin-form-grid">
                    <label>
                      Role
                      <select className="select" value={userDraft.role} onChange={(e) => setUserDraft((current) => ({ ...current, role: e.target.value }))}>
                        <option value="user">user</option>
                        <option value="moderator">moderator</option>
                        <option value="admin">admin</option>
                      </select>
                    </label>
                    <label>
                      Status
                      <select
                        className="select"
                        value={userDraft.status}
                        onChange={(e) => setUserDraft((current) => ({ ...current, status: e.target.value }))}
                        disabled={selectedUser.is_protected_admin}
                      >
                        <option value="active">active</option>
                        <option value="suspended">suspended</option>
                        <option value="inactive">inactive</option>
                      </select>
                    </label>
                    <label>
                      Plan
                      <select className="select" value={userDraft.plan} onChange={(e) => setUserDraft((current) => ({ ...current, plan: e.target.value }))}>
                        <option value="free">free</option>
                        <option value="pro">pro</option>
                        <option value="internal">internal</option>
                      </select>
                    </label>
                  </div>
                  <label>
                    Admin notes
                    <textarea
                      className="textarea admin-user-notes"
                      value={userDraft.admin_notes}
                      onChange={(e) => setUserDraft((current) => ({ ...current, admin_notes: e.target.value }))}
                      placeholder="Internal notes for account handling."
                    />
                  </label>
                  <div className="saved-project-pills">
                    <span className="saved-project-pill">{selectedUser.active_session_count} active sessions</span>
                    <span className="saved-project-pill">{selectedUser.project_count} decks</span>
                    <span className="saved-project-pill">{selectedUser.version_count} versions</span>
                  </div>
                  {selectedUser.is_protected_admin ? <p className="control-help">Protected admin accounts cannot be suspended or deactivated from this panel.</p> : null}
                  <div className="account-primary-actions">
                    <button type="button" className="btn btn-primary" onClick={() => void saveUser()} disabled={savingUser}>
                      {savingUser ? "Saving…" : "Save changes"}
                    </button>
                  </div>
                </>
              ) : (
                <p className="control-help">Select a user to edit account controls.</p>
              )}
            </div>
          </div>
        </section>
      ) : null}
    </main>
  );
}
