

(() => {
  const TOKEN_KEY = "central-channel-session";
  const REFRESH_TOKEN_KEY = "central-channel-refresh-session";
  const configuredBase = window.CENTRAL_API_BASE || window.APP_CONFIG?.apiBase;
  const defaultBase = location.protocol === "file:" ? "http://127.0.0.1:8000" : location.origin;
  const base = (configuredBase || defaultBase).replace(/\/$/, "");
  const encode = encodeURIComponent;

  async function refreshSession() {
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
    if (!refreshToken) return false;
    try {
      const response = await fetch(`${base}/api/auth/refresh`, {
        method: "POST",
        headers: { "Accept": "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ refreshToken }),
      });
      const result = await response.json().catch(() => null);
      if (!response.ok || !result?.token) return false;
      localStorage.setItem(TOKEN_KEY, result.token);
      if (result.refreshToken) localStorage.setItem(REFRESH_TOKEN_KEY, result.refreshToken);
      return true;
    } catch {
      return false;
    }
  }

  async function request(path, options = {}, canRefresh = true) {
    const headers = new Headers(options.headers || {});
    headers.set("Accept", "application/json");
    if (options.body !== undefined) headers.set("Content-Type", "application/json");
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    let response;
    try {
      response = await fetch(`${base}${path}`, {
        ...options, headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
      });
    } catch {
      throw new Error(`Cannot reach the reservation API at ${base}. Start the backend or check its API URL.`);
    }
    if (response.status === 401 && canRefresh && path !== "/api/auth/refresh" && await refreshSession()) {
      return request(path, options, false);
    }
    const payload = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401) {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(REFRESH_TOKEN_KEY);
      }
      throw new Error(payload?.error || `Request failed (${response.status}).`);
    }
    return payload;
  }

  async function authenticate(path, credentials) {
    const result = await request(path, { method: "POST", body: credentials });
    if (!result.token) {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(REFRESH_TOKEN_KEY);
      if (result.requiresEmailConfirmation) {
        throw new Error("Account created. Check your email to confirm it, then log in.");
      }
      throw new Error("Authentication succeeded without a session. Please try logging in.");
    }
    localStorage.setItem(TOKEN_KEY, result.token);
    if (result.refreshToken) localStorage.setItem(REFRESH_TOKEN_KEY, result.refreshToken);
    return result.user;
  }

  window.ReservationAPI = {
    base,
    tokenKey: TOKEN_KEY,
    login: (credentials) => authenticate("/api/auth/login", credentials),
    register: (details) => authenticate("/api/auth/register", details),
    me: async () => (await request("/api/auth/me")).user,
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
    updateBooking: (id, details) => request(`/api/bookings/${encode(id)}`, { method: "PATCH", body: details }),
    action: (id, action, details = {}) => request(`/api/bookings/${encode(id)}/${encode(action)}`, { method: "PUT", body: details }),
    rooms: (checkIn, checkOut, bookingId = "") => request(`/api/rooms?checkIn=${encode(checkIn)}&checkOut=${encode(checkOut)}&bookingId=${encode(bookingId)}`),
    parkingSlots: (startAt, endAt, bookingId = "") => request(`/api/parking/slots?startAt=${encode(startAt)}&endAt=${encode(endAt)}&bookingId=${encode(bookingId)}`),
    notifications: () => request("/api/notifications"),
    markNotificationRead: (id) => request(`/api/notifications/${encode(id)}/read`, { method: "PUT", body: {} }),
    history: (id, type) => request(`/api/history?bookingId=${encode(id)}&type=${encode(type)}`),
    personnel: () => request("/api/personnel"),
    users: () => request("/api/users"),
    qrPasses: () => request("/api/qr/passes"),
    verifyQrPass: (receiptCode) => request(`/api/qr/verify/${encode(receiptCode)}`),
    createAdmin: (details) => request("/api/admin/users", { method: "POST", body: details }),
    addPersonnel: (userId, department) => request("/api/personnel", { method: "POST", body: { userId, department } }),
  };
})();