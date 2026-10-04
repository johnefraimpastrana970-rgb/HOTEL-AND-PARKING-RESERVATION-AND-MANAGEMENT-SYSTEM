W(() => {
  const TOKEN_KEY = "central-channel-session";
  const configuredBase = window.CENTRAL_API_BASE || window.APP_CONFIG?.apiBase;
  const defaultBase = location.protocol === "file:" ? "http://127.0.0.1:8000" : location.origin;
  const base = (configuredBase || defaultBase).replace(/\/$/, "");

  async function request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set("Accept", "application/json");
    if (options.body !== undefined) headers.set("Content-Type", "application/json");
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    let response;
    try {
      response = await fetch(`${base}${path}`, {
        ...options,
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
      });
    } catch {
      throw new Error(`Cannot reach the reservation API at ${base}. Start the backend or check its API URL.`);
    }
    const payload = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401) localStorage.removeItem(TOKEN_KEY);
      throw new Error(payload?.error || `Request failed (${response.status}).`);
    }
    return payload;
  }

  async function authenticate(path, credentials) {
    const result = await request(path, { method: "POST", body: credentials });
    localStorage.setItem(TOKEN_KEY, result.token);
    return result.user;
  }

  const encode = encodeURIComponent;
  window.ReservationAPI = {
    base,
    tokenKey: TOKEN_KEY,
    login: (credentials) => authenticate("/api/auth/login", credentials),
    register: (details) => authenticate("/api/auth/register", details),
    me: async () => (await request("/api/auth/me")).user,
    logout: async () => {
      try { await request("/api/auth/logout", { method: "POST" }); }
      finally { localStorage.removeItem(TOKEN_KEY); }
    },
    bookings: () => request("/api/bookings"),
    hotelBookings: () => request("/api/hotel/bookings"),
    parkingBookings: () => request("/api/parking/bookings"),
    createBooking: (type, details) => request(`/api/${type.toLowerCase()}/bookings`, { method: "POST", body: details }),
    updateBooking: (id, details) => request(`/api/bookings/${encode(id)}`, { method: "PATCH", body: details }),
    action: (id, action, details = {}) => request(`/api/bookings/${encode(id)}/${encode(action)}`, { method: "PUT", body: details }),
    rooms: (checkIn, checkOut) => request(`/api/rooms?checkIn=${encode(checkIn)}&checkOut=${encode(checkOut)}`),
    parkingSlots: (startAt, endAt) => request(`/api/parking/slots?startAt=${encode(startAt)}&endAt=${encode(endAt)}`),
    notifications: () => request("/api/notifications"),
    markNotificationRead: (id) => request(`/api/notifications/${encode(id)}/read`, { method: "PUT", body: {} }),
    history: (id, type) => request(`/api/history?bookingId=${encode(id)}&type=${encode(type)}`),
    personnel: () => request("/api/personnel"),
    addPersonnel: (userId, department) => request("/api/personnel", { method: "POST", body: { userId, department } }),
  };
})();