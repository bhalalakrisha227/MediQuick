import { createContext, useCallback, useContext, useEffect, useState } from "react";
import api, { refreshSession, tokens } from "../api/client";

const AuthContext = createContext(null);
export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    tokens.setOnSessionExpired(() => setUser(null));
    if (!tokens.hasRefresh()) {
      setLoading(false);
      return;
    }
    // Restore the session after a page reload.
    refreshSession()
      .then((data) => setUser(data.user))
      .catch(() => tokens.clear())
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email, password) => {
    const res = await api.post("/auth/login/", { email, password });
    tokens.set(res.data);
    setUser(res.data.user);
  }, []);

  const register = useCallback(async (form) => {
    const res = await api.post("/auth/register/", form);
    tokens.set(res.data);
    setUser(res.data.user);
  }, []);

  const logout = useCallback(async () => {
    try {
      const refresh_token = sessionStorage.getItem("mq_refresh");
      if (refresh_token) await api.post("/auth/logout/", { refresh_token });
    } catch { /* ignore: we clear local state regardless */ }
    tokens.clear();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, setUser, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
