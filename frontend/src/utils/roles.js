// One place that says which navigation each role gets. This only decides what the UI shows:
// the server still enforces every permission.
export const isCustomer = (user) => user?.role === "customer";
export const isStaff = (user) => !!user && user.role !== "customer";
// Visitors who are not logged in and customers can shop; staff accounts cannot.
export const canShop = (user) => !user || isCustomer(user);

const REVIEW_ROLES = ["pharmacist", "pharmacy_manager", "admin"];
const FULFILMENT_ROLES = ["support_agent", "pharmacy_manager", "admin"];
const ADMIN_ROLES = ["admin", "pharmacy_manager"];
const RIDER_ROLES = ["delivery_partner"];
const INVENTORY_ROLES = ["inventory_staff", "pharmacy_manager", "admin", "pharmacist"];

// label = full name (menus, footer), short = what fits in the top bar.
export function workspaceLinks(role) {
  const links = [];
  if (REVIEW_ROLES.includes(role)) links.push({ to: "/staff/prescriptions", label: "Prescription review", short: "Review", icon: "clipboard" });
  if (FULFILMENT_ROLES.includes(role)) links.push({ to: "/staff/fulfilment", label: "Fulfilment", short: "Fulfilment", icon: "truck" });
  if (INVENTORY_ROLES.includes(role)) links.push({ to: "/staff/inventory", label: "Inventory", short: "Inventory", icon: "box" });
  if (RIDER_ROLES.includes(role)) links.push({ to: "/rider", label: "My deliveries", short: "Deliveries", icon: "truck" });
  if (ADMIN_ROLES.includes(role)) links.push({ to: "/admin", label: role === "admin" ? "Admin dashboard" : "Manager dashboard", short: role === "admin" ? "Admin" : "Dashboard", icon: "chart" });
  return links;
}
