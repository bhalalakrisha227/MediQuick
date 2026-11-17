export const RX_STATUS = {
  processing: ["info", "Reading your prescription..."],
  needs_customer_review: ["warning", "Please review"],
  submitted: ["primary", "Waiting for a pharmacist"],
  in_review: ["primary", "A pharmacist is reviewing"],
  clarification_requested: ["warning", "Pharmacist has a question"],
  approved: ["success", "Approved by a pharmacist"],
  rejected: ["danger", "Not approved"],
  withdrawn: ["secondary", "Withdrawn"],
};
