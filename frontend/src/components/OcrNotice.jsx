// Shown on every prescription screen. OCR is a convenience; it never approves anything.
export default function OcrNotice() {
  return (
    <div className="alert alert-info small">
      <strong>Please check carefully.</strong> The text below is read automatically from your image and can be wrong or incomplete.
      It is only a suggestion to save you typing. A pharmacist checks your original prescription, and only a pharmacist can approve it.
      Nothing is approved automatically.
    </div>
  );
}
