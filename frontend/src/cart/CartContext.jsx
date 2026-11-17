import { createContext, useCallback, useContext, useEffect, useState } from "react";
import api from "../api/client";
import { useAuth } from "../auth/AuthContext";

const CartContext = createContext(null);
export const useCart = () => useContext(CartContext);

// The cart lives on the server; this keeps a local copy in sync for the navbar and pages.
export function CartProvider({ children }) {
  const { user } = useAuth();
  const [cart, setCart] = useState(null);

  const refresh = useCallback(async () => {
    if (!user) { setCart(null); return; }
    try { setCart((await api.get("/cart/")).data); } catch { /* shown on the cart page */ }
  }, [user]);
  useEffect(() => { refresh(); }, [refresh]);

  const add = useCallback(async (product_id, quantity) => {
    setCart((await api.post("/cart/items/", { product_id, quantity })).data);
  }, []);
  const setQuantity = useCallback(async (product_id, quantity) => {
    setCart((await api.patch(`/cart/items/${product_id}/`, { quantity })).data);
  }, []);
  const remove = useCallback(async (product_id) => {
    setCart((await api.delete(`/cart/items/${product_id}/`)).data);
  }, []);

  return (
    <CartContext.Provider value={{ cart, refresh, add, setQuantity, remove }}>
      {children}
    </CartContext.Provider>
  );
}
