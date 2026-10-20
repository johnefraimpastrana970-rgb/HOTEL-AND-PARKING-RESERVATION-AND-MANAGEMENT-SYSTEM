

(() => {
  const SESSION_KEYS = {
    customer: {
      token: "central-channel-user-session",
      refresh: "central-channel-user-refresh-session",
    },
    admin: {
      token: "central-channel-admin-session",
      refresh: "central-channel-admin-refresh-session",
    },
  };
  const path = decodeURIComponent(location.pathname).toLowerCase();
  let activeScope = path.endsWith("/central channel/admin.html") ||
    new URLSearchParams(location.search).get("portal") === "admin"
    ? "admin"
    : "customer";
  const configuredBase = window.CENTRAL_API_BASE || window.APP_CONFIG?.apiBase;
  const localHosts = new Set(["localhost", "127.0.0.1", "[::1]", "::1"]);
  const localFrontend = location.protocol === "file:" ||
    (localHosts.has(location.hostname) && location.port !== "8000");
  const defaultBase = localFrontend ? "http://127.0.0.1:8000" : location.origin;
  const base = (configuredBase || defaultBase).replace(/\/$/, "");
  const encode = encodeURIComponent;
  let lastFailedRequestId = "";
  const activeKeys = () => SESSION_KEYS[activeScope];

  async function refreshSession() {
    const refreshToken = localStorage.getItem(activeKeys().refresh);
    if (!refreshToken) return false;
    try {
      const response = await fetch(`${base}/api/auth/refresh`, {
        method: "POST",
        headers: { "Accept": "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ refreshToken }),
      });
      const result = await response.json().catch(() => null);
      if (!response.ok || !result?.token) return false;
      localStorage.setItem(activeKeys().token, result.token);
      if (result.refreshToken) localStorage.setItem(activeKeys().refresh, result.refreshToken);
      return true;
    } catch {
      return false;
    }
  }

  async function request(path, options = {}, canRefresh = true) {
    const headers = new Headers(options.headers || {});
    headers.set("Accept", "application/json");
    if (options.body !== undefined) headers.set("Content-Type", "application/json");
    const token = localStorage.getItem(activeKeys().token);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    let response;
    try {
      response = await fetch(`${base}${path}`, {
        ...options, headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
      });
    } catch {
      const help = localFrontend
        ? " Start the backend with RUN_RESERVATION_SITE.bat and check its API URL."
        : " Check that the API server is running at this address.";
      throw new Error(`Cannot reach the reservation API at ${base}.${help}`);
    }
    const requestId = response.headers.get("X-Request-ID") || "";
    if (!response.ok) lastFailedRequestId = requestId;
    if (response.status === 401 && canRefresh && path !== "/api/auth/refresh" && await refreshSession()) {
      return request(path, options, false);
    }
    const payload = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401) {
        localStorage.removeItem(activeKeys().token);
        localStorage.removeItem(activeKeys().refresh);
      }
      throw new Error(payload?.error || `Request failed (${response.status}).`);
    }
    return payload;
  }

  async function authenticate(path, credentials, options = {}) {
    const result = await request(path, { method: "POST", body: credentials });
    if (options.adminOnly && result.user?.role !== "Admin") {
      throw new Error("This account does not have administrator access.");
    }
    if (!result.token) {
      const scope = result.user?.role === "User" ? "customer" : "admin";
      localStorage.removeItem(SESSION_KEYS[scope].token);
      localStorage.removeItem(SESSION_KEYS[scope].refresh);
      if (result.requiresEmailConfirmation) {
        throw new Error("Account created. Check your email to confirm it, then log in.");
      }
      throw new Error("Authentication succeeded without a session. Please try logging in.");
    }
    activeScope = result.user?.role === "User" ? "customer" : "admin";
    localStorage.setItem(activeKeys().token, result.token);
    if (result.refreshToken) localStorage.setItem(activeKeys().refresh, result.refreshToken);
    return result.user;
  }

  window.ReservationAPI = {
    base,
    get tokenKey() { return activeKeys().token; },
    get refreshTokenKey() { return activeKeys().refresh; },
    clearSession: () => {
      localStorage.removeItem(activeKeys().token);
      localStorage.removeItem(activeKeys().refresh);
    },
    login: (credentials, options) => authenticate("/api/auth/login", credentials, options),
    register: async (details) => {
      const result = await request("/api/auth/register", { method: "POST", body: details });
      if (result.token) {
        if (!result.user) throw new Error("Account creation returned an incomplete session. Please contact support.");
        activeScope = result.user.role === "User" ? "customer" : "admin";
        localStorage.setItem(activeKeys().token, result.token);
        if (result.refreshToken) localStorage.setItem(activeKeys().refresh, result.refreshToken);
        else localStorage.removeItem(activeKeys().refresh);
      }
      return result;
    },
    verifyEmail: (credentials) => authenticate("/api/auth/verify-email", credentials),
    resendEmailConfirmation: (email) => request("/api/auth/resend-confirmation", {
      method: "POST",
      body: { email },
    }),
    me: async () => (await request("/api/auth/me")).user,
    reservationStatus: () => request("/api/admin/reservations/status"),
    setReservationsEnabled: (enabled) => request("/api/admin/reservations/status", { method: "PUT", body: { enabled } }),
    logout: async () => {
      try { await request("/api/auth/logout", { method: "POST" }); }
      finally {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(REFRESH_TOKEN_KEY);
      }
    },
    bookings: () => request("/api/bookings"),
    hotelBookings: () => request("/api/hotel/bookings"),
    parkingBookings: () => request("/api/parking/bookings"),
    createBooking: (type, details) => request(`/api/${type.toLowerCase()}/bookings`, { method: "POST", body: details }),
    createCombinedBooking: (details) => request("/api/combined/bookings", { method: "POST", body: details }),
    updateBooking: (id, details) => request(`/api/bookings/${encode(id)}`, { method: "PATCH", body: details }),
    action: (id, action, details = {}) => request(`/api/bookings/${encode(id)}/${encode(action)}`, { method: "PUT", body: details }),
    rooms: (checkIn, checkOut, bookingId = "") => request(`/api/rooms?checkIn=${encode(checkIn)}&checkOut=${encode(checkOut)}&bookingId=${encode(bookingId)}`),
    parkingSlots: (startAt, endAt, bookingId = "") => request(`/api/parking/slots?startAt=${encode(startAt)}&endAt=${encode(endAt)}&bookingId=${encode(bookingId)}`),
    demoInventory: () => Promise.all([
      request("/api/rooms"),
      request("/api/parking/slots"),
    ]).then(([rooms, parkingSlots]) => ({ rooms, parkingSlots })),
    notifications: () => request("/api/notifications"),
    markNotificationRead: (id) => request(`/api/notifications/${encode(id)}/read`, { method: "PUT", body: {} }),
    history: (id, type) => request(`/api/history?bookingId=${encode(id)}&type=${encode(type)}`),
    personnel: () => request("/api/personnel"),
    users: () => request("/api/users"),
    qrPasses: () => request("/api/qr/passes"),
    verifyQrPass: (receiptCode) => request(`/api/qr/verify/${encode(receiptCode)}`),
    createAdmin: (details) => request("/api/admin/users", { method: "POST", body: details }),
    addPersonnel: (userId, department) => request("/api/personnel", { method: "POST", body: { userId, department } }),
    serviceStatus: () => request("/api/health/ready"),
    reportProblem: async (details) => {
      const result = await request("/api/support/reports", {
        method: "POST",
        body: { ...details, requestId: lastFailedRequestId },
      });
      lastFailedRequestId = "";
      return result;
    },
    supportReports: () => request("/api/admin/support/reports"),
    replyToSupportReport: (reportId, message) => request(
      `/api/admin/support/reports/${encode(reportId)}/replies`,
      { method: "POST", body: { message } },
    ),
    auditLog: () => request("/api/admin/audit-log"),
  };
})();