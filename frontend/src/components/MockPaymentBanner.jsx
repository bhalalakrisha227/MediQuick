export default function MockPaymentBanner() {
  return (
    <div className="alert alert-warning">
      <strong>MOCK PAYMENT (development build).</strong> No real payment gateway is connected and no money is charged.
    </div>
  );
}
