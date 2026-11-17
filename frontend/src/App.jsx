import { Navigate, Route, Routes } from "react-router-dom";
import ProtectedRoute from "./auth/ProtectedRoute.jsx";
import RoleRoute from "./auth/RoleRoute.jsx";
import InventoryPage from "./pages/InventoryPage.jsx";
import CartPage from "./pages/CartPage.jsx";
import CheckoutPage from "./pages/CheckoutPage.jsx";
import OrderPage from "./pages/OrderPage.jsx";
import OrdersPage from "./pages/OrdersPage.jsx";
import StaffPrescriptionPage from "./pages/StaffPrescriptionPage.jsx";
import StaffPrescriptionsPage from "./pages/StaffPrescriptionsPage.jsx";
import PrescriptionPage from "./pages/PrescriptionPage.jsx";
import PrescriptionsPage from "./pages/PrescriptionsPage.jsx";
import PrescriptionUploadPage from "./pages/PrescriptionUploadPage.jsx";
import NavBar from "./components/NavBar.jsx";
import Footer from "./components/Footer.jsx";
import HomePage from "./pages/HomePage.jsx";
import ProductPage from "./pages/ProductPage.jsx";
import ShopPage from "./pages/ShopPage.jsx";
import CustomerDashboardPage from "./pages/CustomerDashboardPage.jsx";
import AccountPage from "./pages/AccountPage.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import RegisterPage from "./pages/RegisterPage.jsx";
import AdminDashboardPage from "./pages/AdminDashboardPage.jsx";
import NotificationsPage from "./pages/NotificationsPage.jsx";
import RiderPage from "./pages/RiderPage.jsx";
import StaffFulfilmentPage from "./pages/StaffFulfilmentPage.jsx";
import StatusPage from "./pages/StatusPage.jsx";

export default function App() {
  return (
    <>
      <NavBar />
      <div className="mq-page">
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/shop" element={<ShopPage />} />
        <Route path="/product/:slug" element={<ProductPage />} />
        <Route path="/status" element={<StatusPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/account" element={<ProtectedRoute><AccountPage /></ProtectedRoute>} />
        <Route path="/dashboard" element={<RoleRoute roles={["customer"]}><CustomerDashboardPage /></RoleRoute>} />
        <Route path="/cart" element={<ProtectedRoute><CartPage /></ProtectedRoute>} />
        <Route path="/checkout" element={<ProtectedRoute><CheckoutPage /></ProtectedRoute>} />
        <Route path="/orders" element={<ProtectedRoute><OrdersPage /></ProtectedRoute>} />
        <Route path="/orders/:id" element={<ProtectedRoute><OrderPage /></ProtectedRoute>} />
        <Route path="/prescriptions" element={<ProtectedRoute><PrescriptionsPage /></ProtectedRoute>} />
        <Route path="/prescriptions/new" element={<ProtectedRoute><PrescriptionUploadPage /></ProtectedRoute>} />
        <Route path="/prescriptions/:id" element={<ProtectedRoute><PrescriptionPage /></ProtectedRoute>} />
        <Route path="/staff/prescriptions" element={
          <RoleRoute roles={["pharmacist", "pharmacy_manager", "admin"]}><StaffPrescriptionsPage /></RoleRoute>
        } />
        <Route path="/staff/prescriptions/:id" element={
          <RoleRoute roles={["pharmacist", "pharmacy_manager", "admin"]}><StaffPrescriptionPage /></RoleRoute>
        } />
        <Route path="/staff/inventory" element={
          <RoleRoute roles={["inventory_staff", "pharmacy_manager", "admin", "pharmacist"]}><InventoryPage /></RoleRoute>
        } />
        <Route path="/staff/fulfilment" element={
          <RoleRoute roles={["support_agent", "pharmacy_manager", "admin"]}><StaffFulfilmentPage /></RoleRoute>
        } />
        <Route path="/notifications" element={<ProtectedRoute><NotificationsPage /></ProtectedRoute>} />
        <Route path="/admin" element={
          <RoleRoute roles={["admin", "pharmacy_manager"]}><AdminDashboardPage /></RoleRoute>
        } />
        <Route path="/rider" element={
          <RoleRoute roles={["delivery_partner"]}><RiderPage /></RoleRoute>
        } />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </div>
      <Footer />
    </>
  );
}
