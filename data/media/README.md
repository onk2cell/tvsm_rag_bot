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
- `products/` — product photos (`documents.<product>.images`). **JPEG/PNG only** —
  WhatsApp drops `.webp` image messages (sticker format) while the send API
  still reports success. The `.jpg` files here are the JAM CDN `.webp` photos
  re-encoded, ready to be hosted at `https://1.jamoutsourcing.com/i/<name>.jpg`
  next to the brochures; the config then points at those.

JPEG/PNG/PDF binaries are gitignored; keep placeholders and this README in git.
Upload binaries to the server under `~/tvsm_rag_bot/data/media/`.
