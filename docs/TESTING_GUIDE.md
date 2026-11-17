# How to test every feature of MediQuick

Everything below uses **mock payments** and **demo data**. No real money moves. Run from PowerShell with the backend virtual environment active (see `docs/SETUP_WINDOWS.md`). If anything behaves differently from "Expected", copy the exact screen text or error and send it to me: that is a real bug to fix.

## 0. One-time preparation

```powershell
cd backend
python manage.py create_indexes
python manage.py seed_demo_catalogue
python manage.py seed_demo_inventory
```

Create one staff account per role (use your own password, at least 10 characters, not a common one):

```powershell
python manage.py create_staff_user --email admin@test.local     --name "Test Admin"    --role admin
python manage.py create_staff_user --email manager@test.local   --name "Test Manager"  --role pharmacy_manager
python manage.py create_staff_user --email pharmacist@test.local --name "Test Pharmacist" --role pharmacist
python manage.py create_staff_user --email stock@test.local     --name "Test Stock"    --role inventory_staff
python manage.py create_staff_user --email rider@test.local     --name "Ravi Rider"    --role delivery_partner
python manage.py create_staff_user --email support@test.local   --name "Test Support"  --role support_agent
```

Register two **customers** on the website: `cust1@test.local` and `cust2@test.local`.

Start the servers (two windows): `python manage.py runserver` and, in `frontend`, `npm run dev`. Open http://localhost:5173. To keep several logins open at once, use a normal window for one user and private/incognito windows for others.

To read emails without a mail server, set `EMAIL_PROVIDER=console` in `backend\.env` (debug only), restart the backend, and run `python manage.py send_notifications --once` after actions; the emails are printed in that window.

Demo data you will use: 8 over-the-counter products and 5 prescription-only ones. Stock: Paracetamol (one good batch of 120 and one batch too close to expiry that must NOT be sold), Cetirizine (only 6 left), Vitamin C (expires in 45 days), Azithromycin (25), Amoxicillin (90), Digital Thermometer and Pantoprazole (no stock at all).

## 1. Automated tests (fast, no browser)

```powershell
cd backend
python manage.py test
```
These use fake databases. Expected: all pass. The plain-Python suites passed 460 tests in my environment; the Django HTTP tests (`test_*_api.py`) have **never been run**, so a failure there is useful information, not a surprise to hide. Also run:
```powershell
python manage.py doctor
python manage.py check --deploy      # expected to complain while DEBUG=True; that is fine for local testing
```

## 2. Accounts and security

| # | Do | Expected |
|---|---|---|
| 2.1 | Sign up with a short password such as `abc123` | Rejected with a clear message (needs 10+ characters, not common) |
| 2.2 | Sign up with a valid password, then log out and log in | Works; your name shows in the top bar |
| 2.3 | Sign up again with the same email | Refused ("already registered") |
| 2.4 | Log in with the wrong password 5 times | Account locked for 15 minutes; even the right password is refused during the lock |
| 2.5 | Account page: change your name/phone; add two addresses | Saved; PIN code must be 6 digits |
| 2.6 | While logged out, open `/cart`, `/orders`, `/admin` | Sent to the login page |
| 2.7 | Logged in as a customer, open `/admin`, `/rider`, `/staff/fulfilment` | Redirected away; no staff data shown |

## 3. Catalogue and stock

| # | Do | Expected |
|---|---|---|
| 3.1 | Shop page: search "para", filter by a category | Results narrow correctly |
| 3.2 | Open Azithromycin | Marked prescription-only |
| 3.3 | Open Digital Thermometer and Pantoprazole | Shown as out of stock; cannot be added |
| 3.4 | Log in as `stock@test.local`, open Inventory | You see batches, a low-stock flag (Cetirizine), an expiring-soon flag (Vitamin C), and the near-expiry Paracetamol batch flagged as not sellable |
| 3.5 | Receive a new batch for Pantoprazole (future expiry, quantity 20) | It becomes available in the shop |
| 3.6 | Try a batch with a past expiry date or negative quantity | Refused |

## 4. Cart, checkout, mock payment

Log in as `cust1`.

| # | Do | Expected |
|---|---|---|
| 4.1 | Add 1 Paracetamol (₹30) and check out | Delivery fee **₹49** is added (orders under ₹499 pay the fee) |
| 4.2 | Add enough items to pass ₹499 | Delivery shows **Free** |
| 4.3 | Try 11 of one product | Refused (maximum 10 per product) |
| 4.4 | Add 7 Cetirizine | Refused or limited: only 6 are in stock |
| 4.5 | Add an Rx product (Azithromycin) and try to check out | Blocked: needs an approved prescription (see section 5) |
| 4.6 | Check out the OTC cart | An order page with a 15-minute countdown and a MOCK payment banner. Stock is now held |
| 4.7 | Click "Simulate a failed payment" | Order stays unpaid, message says you were not charged; you can pay again |
| 4.8 | Click Pay | Status becomes Confirmed. In Inventory the quantity dropped |
| 4.9 | Make another order, do not pay, wait 15 minutes (or run `python manage.py release_expired_reservations` after the time passes) | Order becomes Expired and the stock returns |
| 4.10 | Log in as `cust2` and open `cust1`'s order URL (`/orders/<id>`) | "Order not found". Never shows another customer's order |

## 5. Prescriptions

Use a clear photo of any handwritten or printed page (a real prescription is not needed for testing; do not upload real patient data).

| # | Do | Expected |
|---|---|---|
| 5.1 | As `cust1`: Prescriptions -> upload a JPG/PNG/PDF | Accepted; status "processing" then "waiting for review". Text may be read automatically but is only a hint |
| 5.2 | Upload a `.txt` renamed to `.jpg`, or a file over 5 MB | Refused (type and size are checked by content, not name) |
| 5.3 | As `pharmacist@test.local`: Review -> open it -> **Claim** | Prescription is now yours; others cannot review it |
| 5.4 | Approve with Azithromycin, quantity 1 | Customer sees "approved" with allowed quantities |
| 5.5 | As `cust1`: add 1 Azithromycin and check out. Then try 2 | 1 is allowed; 2 is refused because only 1 was approved |
| 5.6 | Upload another one; as pharmacist choose **Send question** | Customer is asked a question and can reply; it returns to the review queue |
| 5.7 | Upload another; **Reject** with a reason | Customer sees the reason; no medicines can be ordered with it |
| 5.8 | Confirm that OCR never approves anything | Without a pharmacist's action, a prescription never becomes approved |

## 6. Cancel, refund, returns (mock money)

| # | Do | Expected |
|---|---|---|
| 6.1 | Pay for an order, then click **Cancel order and refund** | Cancelled, "refunded (mock: no real money moved)", stock returned |
| 6.2 | Pay for another order, then (section 7) get it delivered | Order page shows a returns section |
| 6.3 | Request a return within 2 days: reasons are wrong item, damaged, expired item or missing item | Request is created ("changed my mind" is not offered) |
| 6.4 | As `support@test.local` or the manager: Fulfilment -> Returns -> approve | Refund is issued for the returned items |
| 6.5 | Request a second return for the same order while one is open | Refused (one open return per order) |

## 7. Fulfilment and delivery

| # | Do | Expected |
|---|---|---|
| 7.1 | As `manager@test.local`: Fulfilment shows the paid order | Visible with a delivery-partner drop-down |
| 7.2 | Assign **Ravi Rider** | Saved |
| 7.3 | As `rider@test.local` (private window): My deliveries | Shows recipient, phone, address, item **count** only: no medicine names or prices. Click "I have picked this up" |
| 7.4 | As `cust1`: open the order | Status "Out for delivery" and a **6-digit code** |
| 7.5 | As the rider: type a wrong code | "Not correct", tries left decreases. After 5 wrong tries it locks, even for the right code |
| 7.6 | Manager reassigns the order | Tries reset |
| 7.7 | Rider types the right code | Status Delivered |
| 7.8 | New order -> assign -> pick up -> rider records "customer not available" 3 times | Order becomes "Delivery failed"; manager can **Redeliver** or **Refund in full** (refund does not restock) |
| 7.9 | Manager's manual "Mark dispatched/delivered" buttons | Work as an override and skip the code |

## 8. Notifications

| # | Do | Expected |
|---|---|---|
| 8.1 | After steps above, look at the Alerts button in the top bar | A number appears; the page lists order confirmed, out for delivery, delivered, refund issued, prescription approved/rejected/question |
| 8.2 | Click one | It opens the order/prescription and is marked read; "Mark all as read" works |
| 8.3 | Read the text of every alert and email | No medicine names, no address, no delivery code |
| 8.4 | Turn off "email me" and trigger another event | In-app alert still appears; no email is printed |

## 9. Admin dashboard

| # | Do | Expected |
|---|---|---|
| 9.1 | As `admin@test.local`: Admin -> Overview | Order counts and paid / refunded / net match what you did; a yellow banner says mock payments are included |
| 9.2 | Change the date range | Numbers change; a bad range (from after to) is refused |
| 9.3 | Needs attention | Shows delivery-failed orders and failed refunds, if any. Flagged orders are rare; to see "Mark as handled" you would need to flag one in the database by hand |
| 9.4 | Accounts tab: switch off `cust2` with a reason | `cust2` is signed out on its next action and cannot log in |
| 9.5 | Try to switch off your own account, or the only admin | Refused |
| 9.6 | Audit log | Lists every switch-off with who, when, why |
| 9.7 | As the manager: Admin | Sees Overview and Needs attention, but no Accounts or Audit tabs |

## 10. Security spot checks

In PowerShell (adjust the order id; the token comes from your browser's local data or by logging in via the API):
```powershell
curl.exe -i http://localhost:8000/api/v1/orders/
```
Expected: 401 and these headers: `Cache-Control: no-store`, `X-Frame-Options: DENY`, `Content-Security-Policy: default-src 'none'...`.
Rate limit: submit the login form wrongly many times quickly; after about 20 attempts a minute you should get "Too many requests".

## 11. Optional: real Razorpay test mode and real email

- Razorpay: follow `docs/PHASE8_PAYMENTS.md`. Use Razorpay's own test cards. This is the first time this code touches real Razorpay, so report anything odd.
- Email: follow `docs/PHASE10_NOTIFICATIONS.md` with a test inbox such as Mailtrap, then run `python manage.py send_notifications`.

## 12. What is NOT testable here

SMS, live tracking, real payments, real pharmacy compliance, and load/performance. See `docs/PRODUCTION_READINESS.md`.

## Keep a bug list

For each failure write: the step number, what you did, what you expected, what happened, and the exact error text (also look at the backend window for a red traceback). Send me the list.
