# Public media for WhatsApp outbound images/documents

Served in production at `https://aichatbot.jamoutsourcing.com/media/...`
(config: `CLIENT_MEDIA_BASE_URL`).

## Layout

- `share_location/how_to.jpg` — Android/iOS steps to share current WhatsApp location
  (sent when customer doesn't know pincode, or says No to a dealer)
- `brochures/` — unused for product PDFs now; WhatsApp sends JAM CDN links:
  - `https://1.jamoutsourcing.com/f/King_EV_MAX-English.pdf`
  - `https://1.jamoutsourcing.com/f/King_Deluxe_Petrol-English.pdf` (CNG/LPG variants when named)
  - `https://1.jamoutsourcing.com/f/King_Duramax_Plus_Petrol-English.pdf` (CNG when named)
- `products/` — other product assets

JPEG/PNG/PDF binaries are gitignored; keep placeholders and this README in git.
Upload binaries to the server under `~/tvsm_rag_bot/data/media/`.
