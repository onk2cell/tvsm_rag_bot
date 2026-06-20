# How to Get a Gemini API Key (and Enable Payment / Billing)

This guide explains how to create a Google Gemini API key, where to enable billing
(payment) so you are not limited by the free tier, and how to add the key to this app.

---

## Part 1 — Create the API key (free, ~3 minutes)

1. Open **Google AI Studio**: <https://aistudio.google.com>
2. **Sign in** with the Google account you want to use for billing.
3. In the left sidebar (or top-right), click **"Get API key"**
   (direct link: <https://aistudio.google.com/app/apikey>).
4. Click **"Create API key"**.
5. When asked for a project, either:
   - **Create a new project** (recommended — keeps this app's usage separate), or
   - Pick an existing Google Cloud project.
6. Your key is generated — it looks like a long string. **Click Copy.**
7. **Store it safely.** Treat it like a password. Do not commit it to GitHub or share it
   publicly. (Anyone with the key can spend money on your account once billing is on.)

> At this point the key already works on the **free tier**, with daily/per-minute
> request limits (e.g. a small number of requests per day per model). Good for testing,
> not enough for a shared team — that's what billing is for.

---

## Part 2 — Enable billing / payment (to remove the free-tier limits)

You pay only for what you use (per token). See current prices:
<https://ai.google.dev/gemini-api/docs/pricing>

### Option A — From Google AI Studio (easiest)

1. Go to the API keys page: <https://aistudio.google.com/app/apikey>
2. Find your project in the list. It will show a plan such as **"Free"**.
3. Click **"Set up Billing"** (or **"Upgrade"**) next to that project.
4. You'll be sent to **Google Cloud Billing**. Follow Option B from step 3 below.

### Option B — From Google Cloud Console (full control)

1. Open the Billing page: <https://console.cloud.google.com/billing>
2. Click **"Add billing account"** (or "Create account") and:
   - Enter your **country** and account type (Individual or Business).
   - Add a **payment method** — a credit/debit card (or other method available in
     your country). You may see a small temporary verification charge.
3. **Link the billing account to your project** — the SAME project your API key belongs to:
   - Go to <https://console.cloud.google.com/billing/projects>
   - Find your project, click the three-dot menu, choose **"Change billing"**,
     and select the billing account you just created.
4. **Enable the API** for the project (if not already):
   - Go to <https://console.cloud.google.com/apis/library/generativelanguage.googleapis.com>
   - Make sure your project is selected (top bar), then click **"Enable"**.

Once billing is linked, your existing API key automatically moves to the **paid tier** —
the same key, just higher limits. You do not need to create a new key.

---

## Part 3 — Set a spending limit (highly recommended)

This protects you from surprise bills (e.g. if the key leaks or usage spikes).

1. Go to **Budgets & alerts**: <https://console.cloud.google.com/billing/budgets>
2. Click **"Create budget"**.
3. Set a monthly amount (e.g. **$10**) and turn on **email alerts** at 50%, 90%, 100%.

> Note: a budget alert *notifies* you; it does not hard-stop spending by itself. For a
> hard cap you can also remove billing or disable the API. For most small teams, an alert
> at a low amount is enough.

---

## Part 4 — Add the key to this app

You have two ways:

### A) In the server `.env` (permanent)
On the server:
```bash
nano .env
# set this line:
GEMINI_API_KEY=YOUR_NEW_KEY_HERE
```
Then restart the app:
```bash
./update.sh
```

### B) On the admin page (no file editing)
1. Open `https://YOUR-URL/admin`
2. Enter the **admin token**.
3. Paste the Gemini API key in the **Gemini API key** box and save.
   (The app validates the key before using it.)

---

## Quick checklist

- [ ] Created API key in Google AI Studio
- [ ] Copied and stored the key safely
- [ ] Added a payment method in Google Cloud Billing
- [ ] Linked the billing account to the key's project
- [ ] Enabled the Generative Language API for the project
- [ ] Set a monthly budget alert
- [ ] Added the key to the app (`.env` or admin page)

---

## Useful links

- Google AI Studio: <https://aistudio.google.com>
- API keys: <https://aistudio.google.com/app/apikey>
- Pricing: <https://ai.google.dev/gemini-api/docs/pricing>
- Cloud Billing: <https://console.cloud.google.com/billing>
- Budgets & alerts: <https://console.cloud.google.com/billing/budgets>
- Rate limits: <https://ai.google.dev/gemini-api/docs/rate-limits>
