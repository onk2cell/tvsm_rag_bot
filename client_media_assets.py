"""Public HTTPS media URLs for WhatsApp outbound images/documents."""
from __future__ import annotations

import re

import config
from dispose import normalize_product_name

SHARE_LOCATION_CAPTIONS = {
    "English": (
        "No problem if you don't know the pincode. "
        "Please share your current location using the steps in the image "
        "(Android or iPhone)."
    ),
    "Hindi": (
        "कोई बात नहीं अगर पिनकोड नहीं पता। कृपया इमेज में दिए स्टेप्स से "
        "अपनी करेंट लोकेशन शेयर करें (Android या iPhone)।"
    ),
    "Marathi": (
        "पिनकोड माहित नसल्यास चालेल. कृपया इमेजमधील स्टेप्सनुसार "
        "तुमचे करंट लोकेशन शेअर करा (Android किंवा iPhone)."
    ),
    "Telugu": (
        "పిన్‌కోడ్ తెలియకపోతే సమస్య లేదు. దయచేసి ఇమేజ్‌లోని స్టెప్స్‌తో "
        "మీ కరెంట్ లొకేషన్ షేర్ చేయండి (Android లేదా iPhone)."
    ),
    "Tamil": (
        "பின்கோடு தெரியாவிட்டால் பரவாயில்லை. படத்தில் உள்ள படிகளின்படி "
        "உங்கள் தற்போதைய இருப்பிடத்தை பகிரவும் (Android அல்லது iPhone)."
    ),
    "Kannada": (
        "ಪಿನ್‌ಕೋಡ್ ತಿಳಿದಿಲ್ಲವಾದರೆ ಚಿಂತೆಯಿಲ್ಲ. ದಯವಿಟ್ಟು ಚಿತ್ರದ ಸ್ಟೆಪ್‌ಗಳಂತೆ "
        "ನಿಮ್ಮ ಪ್ರಸ್ತುತ ಲೊಕೇಶನ್ ಹಂಚಿಕೊಳ್ಳಿ (Android ಅಥವಾ iPhone)."
    ),
    "Malayalam": (
        "പിൻകോഡ് അറിയില്ലെങ്കിൽ കുഴപ്പമില്ല. ദയവായി ഇമയിലെ സ്റ്റെപ്പുകൾ പോലെ "
        "നിങ്ങളുടെ കറന്റ് ലൊക്കേഷൻ ഷെയർ ചെയ്യുക (Android അല്ലെങ്കിൽ iPhone)."
    ),
}

# Canonical product → public brochure PDF on JAM CDN (not Cloudflare/local media).
_JAM_PDF_BASE = "https://1.jamoutsourcing.com/f"

PRODUCT_BROCHURE_URLS = {
    "King EV MAX": f"{_JAM_PDF_BASE}/King_EV_MAX-English.pdf",
    "King Deluxe": f"{_JAM_PDF_BASE}/King_Deluxe_Petrol-English.pdf",
    "King Duramax Plus": f"{_JAM_PDF_BASE}/King_Duramax_Plus_Petrol-English.pdf",
}

# Fuel-specific brochures when the customer names CNG / LPG / Petrol.
PRODUCT_BROCHURE_FUEL_URLS = {
    "King Deluxe": {
        "cng": f"{_JAM_PDF_BASE}/King_Deluxe_CNG-English.pdf",
        "lpg": f"{_JAM_PDF_BASE}/King_Deluxe_LPG-English.pdf",
        "petrol": f"{_JAM_PDF_BASE}/King_Deluxe_Petrol-English.pdf",
    },
    "King Duramax Plus": {
        "cng": f"{_JAM_PDF_BASE}/King_Duramax_Plus_CNG-English.pdf",
        "petrol": f"{_JAM_PDF_BASE}/King_Duramax_Plus_Petrol-English.pdf",
    },
}

# Extra PDFs sent with the product brochure (warranty / PMS schedule).
PRODUCT_SUPPORT_DOC_URLS = {
    "King EV MAX": [
        (f"{_JAM_PDF_BASE}/TVS_King_EV_MAX_Warranty_Policy.pdf", "warranty"),
    ],
    "King Deluxe": [
        (f"{_JAM_PDF_BASE}/Deluxe-PMS-Schedule.pdf", "pms"),
        (f"{_JAM_PDF_BASE}/Deluxe-Warranty-Policy-new.pdf", "warranty"),
    ],
    "King Duramax Plus": [
        (f"{_JAM_PDF_BASE}/Duramaxplus-PMS-Schedule.pdf", "pms"),
        (f"{_JAM_PDF_BASE}/Duramaxplus-Warranty-Policy.pdf", "warranty"),
    ],
}

# Kept for callers/tests that still check configured products.
PRODUCT_BROCHURE_SLUG = {
    "King EV MAX": "King_EV_MAX-English",
    "King Deluxe": "King_Deluxe_Petrol-English",
    "King Duramax Plus": "King_Duramax_Plus_Petrol-English",
}

# Literal document requests only — these get the PDF/document sent
# immediately. General info questions (PRODUCT_INFO_ASK_RE below) get a text
# answer and an offer to send the brochure instead, not an automatic send.
PRODUCT_DOCUMENT_ASK_RE = re.compile(
    r"(?i)("
    r"\b(brochure|brocher|brochar|borcher|broucher|broshar|broshure|"
    r"pdf|catalogue|catalog|pamphlet|leaflet|"
    r"send\s+(me\s+)?(the\s+)?(pdf|brochure|brocher|brochar|borcher))\b|"
    r"ब्रोशर|पीडीएफ|कैटलॉग|"
    r"ब्रॉशर|कॅटलॉग"
    r")"
)

# General product-info questions — answered in text, then the customer is
# asked (separately, deterministically) whether they'd like the brochure
# too. Not gated to an automatic document send.
PRODUCT_INFO_ASK_RE = re.compile(
    r"(?i)("
    r"\b(specs?|features?|specification|details?|full\s+details|"
    r"info(?:rmation)?|"
    r"tell\s+me\s+about|give\s+me\s+(info|information|details)|"
    r"send\s+(me\s+)?(the\s+)?(details|info(?:rmation)?))\b|"
    r"जानकारी|विवरण|"
    r"माहिती|तपशील|"
    r"సమాచారం|వివరాలు|"
    r"விவரங்கள்|தகவல்|"
    r"ವಿವರ|ಮಾಹಿತಿ|"
    r"വിവരം|വിശദാംശങ്ങൾ"
    r")"
)

UNKNOWN_PINCODE_RE = re.compile(
    r"(?i)("
    r"don'?t\s+know.{0,40}(pin|pincode|postal\s*code)|"
    r"do\s+not\s+know.{0,40}(pin|pincode|postal\s*code)|"
    r"no\s+(idea|clue).{0,20}(pin|pincode)|"
    r"(pin|pincode|postal\s*code).{0,20}(don'?t\s+know|unknown|not\s+know)|"
    r"\bno\s+pincode\b|"
    r"pincode\s+nahi|pin\s*code\s+nahi|pin\s+nahi|"
    r"(pin|pincode|pin\s*code).{0,25}(mahit|mahiti|malum|maloom|pata)\s*(nahi|nay|nahin)|"
    r"(mahit|mahiti|malum|maloom|pata)\s*(nahi|nay|nahin).{0,25}(pin|pincode)|"
    r"पिन\s*(कोड)?\s*(नहीं|नही|नाही)|"
    r"पिनकोड\s*(नहीं|नही|नाही)|"
    r"(पिन|पिनकोड).{0,20}(माहित\s*नाही|महत्व\s*नाही)|"
    r"माहित\s*नाही.{0,20}(पिन|पिनकोड)|"
    r"पिनकोड\s*तெரியదు|పిన్.?కోడ్\s*తెలియదు|"
    r"பின்கோடு\s*தெரியவில்லை|ಪಿನ್.?ಕೋಡ್\s*ಗೊತ್ತಿಲ್ಲ|"
    r"പിൻകോഡ്\s*അറിയില്ല"
    r")"
)


# Short generic "I don't know" replies (any language). Used when the bot has
# just asked for a pincode and the customer answers without naming it.
BARE_DONT_KNOW_RE = re.compile(
    r"(?i)^\s*(i\s+)?(really\s+)?("
    r"don'?t\s+know|do\s+not\s+know|dunno|idk|no\s+idea|not\s+sure|"
    r"nahi\s*(pata|malum|maloom|mahit|mahiti)|"
    r"(pata|malum|maloom|mahit|mahiti)\s*(nahi|nay|nahin)|"
    r"नहीं\s*पता|पता\s*नहीं|मालूम\s*नहीं|नहीं\s*मालूम|"
    r"माहित\s*नाही|माहिती\s*नाही|माहीत\s*नाही|ठाऊक\s*नाही|"
    r"తెలియదు|தெரியாது|ಗೊತ್ತಿಲ್ಲ|അറിയില്ല"
    r")\s*(hai|आहे|है)?\s*[!.।]*\s*$"
)


def media_base_url() -> str:
    return (config.CLIENT_MEDIA_BASE_URL or "").rstrip("/")


def share_location_image_url(language: str = "") -> str:
    """HTTPS URL for the WhatsApp how-to share-location card."""
    del language  # one bilingual Android/iOS card for all languages
    base = media_base_url()
    if not base:
        return ""
    return f"{base}/share_location/how_to.jpg"


def share_location_caption(language: str) -> str:
    return SHARE_LOCATION_CAPTIONS.get(language) or SHARE_LOCATION_CAPTIONS["English"]


def doesnt_know_pincode(message: str | None) -> bool:
    """True when the customer says they don't know / don't have a pincode."""
    return bool(UNKNOWN_PINCODE_RE.search((message or "").strip()))


def is_bare_dont_know(message: str | None) -> bool:
    """True for a short generic "don't know" reply without naming the pincode."""
    return bool(BARE_DONT_KNOW_RE.match((message or "").strip()))


def wants_product_brochure(message: str | None) -> bool:
    """True when the customer explicitly asks for the document itself
    (brochure/PDF/catalog) — gates an immediate document send."""
    return bool(PRODUCT_DOCUMENT_ASK_RE.search((message or "").strip()))


def wants_product_info(message: str | None) -> bool:
    """True for a general product-info question (specs/features/details/
    "tell me about") that is NOT a literal document request — this should
    get a text answer plus an offer to send the brochure, not an automatic
    document send."""
    return bool(PRODUCT_INFO_ASK_RE.search((message or "").strip()))


def brochure_product_from_text(*texts: str | None) -> str:
    """Pick a brochure product from free text (message, profile, CRM hint)."""
    for text in texts:
        product = normalize_product_name(text)
        if product in PRODUCT_BROCHURE_URLS:
            return product
    return ""


def _fuel_from_text(*texts: str | None) -> str:
    """Return cng / lpg / petrol when mentioned, else empty."""
    blob = " ".join(str(text or "") for text in texts).lower()
    if re.search(r"\bcng\b|सीएनजी|सी\s*एन\s*जी", blob):
        return "cng"
    if re.search(r"\blpg\b|एलपीजी|एल\s*पी\s*जी", blob):
        return "lpg"
    if re.search(r"\bpetrol\b|gasoline|पेट्रोल", blob):
        return "petrol"
    return ""


def product_brochure_url(product: str, *hint_texts: str | None) -> str:
    """HTTPS URL for a product brochure PDF on the JAM CDN, or empty."""
    product = (product or "").strip()
    if product not in PRODUCT_BROCHURE_URLS:
        return ""
    fuel = _fuel_from_text(*hint_texts)
    if fuel:
        fuel_map = PRODUCT_BROCHURE_FUEL_URLS.get(product) or {}
        if fuel in fuel_map:
            return fuel_map[fuel]
    return PRODUCT_BROCHURE_URLS[product]


# Customer asked about servicing/maintenance or warranty specifically — only
# then do the PMS schedule / warranty policy PDFs go out alongside the
# brochure. Asking for "the brochure" must deliver one file, not three.
SUPPORT_DOC_ASK_RE = re.compile(
    r"(?i)("
    r"\b(warrant\w*|guarantee|pms|service\s*schedule|servicing|maintenance)\b|"
    r"वारंटी|वॉरंटी|सर्विस|सर्व्हिस|मेंटेनन्स|देखभाल"
    r")"
)


def wants_support_documents(message: str | None) -> bool:
    """True when the customer asked about warranty or service/maintenance,
    which is when the PMS/warranty PDFs are worth sending too."""
    return bool(SUPPORT_DOC_ASK_RE.search((message or "").strip()))


def product_document_pack(
    product: str, *hint_texts: str | None, include_support_docs: bool = False
) -> list[tuple[str, str]]:
    """Return ``(url, kind)`` docs for a product.

    The brochure alone by default — asking for "the brochure" delivered the
    brochure, the PMS schedule AND the warranty policy, three files for one
    request. Pass ``include_support_docs=True`` (see ``wants_support_documents``)
    when the customer actually asked about warranty or servicing.

    ``kind`` is one of ``brochure``, ``warranty``, ``pms``.
    """
    brochure = product_brochure_url(product, *hint_texts)
    if not brochure:
        return []
    pack: list[tuple[str, str]] = [(brochure, "brochure")]
    if include_support_docs:
        for link, kind in PRODUCT_SUPPORT_DOC_URLS.get(product, ()):
            pack.append((link, kind))
    return pack


def product_brochure_caption(product: str) -> str:
    return f"{product} brochure"
