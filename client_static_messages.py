"""Localized static WhatsApp replies (dealer card, location, place redirect).

English / Hindi / Marathi are fully localized. Other supported languages fall
back to English for these mechanical cards until translations are filled in.
"""
from __future__ import annotations

_DEALER_INTRO = {
    "English": "Please check this dealership details:",
    "Hindi": "कृपया इस डीलरशिप का विवरण देखें:",
    "Marathi": "कृपया ही डीलरशिप तपशील तपासा:",
}

_DEALER_ASK = {
    "English": "Is this dealership near you / OK for you? Reply Yes or No.",
    "Hindi": "क्या यह डीलरशिप आपके पास / आपके लिए ठीक है? हाँ या नहीं में जवाब दें।",
    "Marathi": "ही डीलरशिप तुमच्या जवळ आहे का / ठीक आहे का? होय किंवा नाही उत्तर द्या.",
}

_WRAP_UP_DEALER_CONFIRM_INTRO = {
    "English": "It was great chatting with you! Just one more thing before we wrap up:",
    "Hindi": "आपसे बात करके अच्छा लगा! खत्म करने से पहले बस एक आखिरी बात:",
    "Marathi": "तुमच्याशी बोलून छान वाटलं! संपवण्याआधी फक्त एक शेवटची गोष्ट:",
}

_LABELS = {
    "English": {
        "name": "Name",
        "address": "Address",
        "phone": "Phone",
        "map": "Map",
        "fallback_address": "(ask dealership for full address)",
        "default_dealer": "TVS dealership",
    },
    "Hindi": {
        "name": "नाम",
        "address": "पता",
        "phone": "फोन",
        "map": "मैप",
        "fallback_address": "(पूरा पता डीलरशिप से पूछें)",
        "default_dealer": "TVS डीलरशिप",
    },
    "Marathi": {
        "name": "नाव",
        "address": "पत्ता",
        "phone": "फोन",
        "map": "नकाशा",
        "fallback_address": "(पूर्ण पत्ता डीलरशिपला विचारा)",
        "default_dealer": "TVS डीलरशिप",
    },
}

_PLACE_REDIRECT = {
    "English": (
        "Please share your current WhatsApp location using the steps in the image, "
        "or type your 6-digit pincode. "
        "I do not use city/area names to find dealerships."
    ),
    "Hindi": (
        "कृपया इमेज में दिए स्टेप्स से अपनी WhatsApp करेंट लोकेशन शेयर करें, "
        "या अपना 6-अंकों का पिनकोड टाइप करें। "
        "मैं शहर/एरिया नाम से डीलरशिप नहीं ढूँढता।"
    ),
    "Marathi": (
        "कृपया इमेजमधील स्टेप्सनुसार तुमचे WhatsApp करंट लोकेशन शेअर करा, "
        "किंवा तुमचा ६-अंकी पिनकोड टाइप करा. "
        "मी शहर/एरिया नावाने डीलरशिप शोधत नाही."
    ),
}

_INVALID_PINCODE_ASK = {
    "English": (
        "That does not look like a valid 6-digit pincode. "
        "Please enter a valid 6-digit pincode (for example 411001)."
    ),
    "Hindi": (
        "यह मान्य 6-अंकों का पिनकोड नहीं लगता। "
        "कृपया सही 6-अंकों का पिनकोड टाइप करें (जैसे 411001)।"
    ),
    "Marathi": (
        "हे वैध ६-अंकी पिनकोड वाटत नाही. "
        "कृपया योग्य ६-अंकी पिनकोड टाइप करा (उदा. 411001)."
    ),
}

_INVALID_PINCODE_LOCATION = {
    "English": (
        "No problem — please share your current WhatsApp location using the steps "
        "in the image, or type a valid 6-digit pincode."
    ),
    "Hindi": (
        "कोई बात नहीं — कृपया इमेज में दिए स्टेप्स से अपनी WhatsApp करेंट लोकेशन "
        "शेयर करें, या सही 6-अंकों का पिनकोड टाइप करें।"
    ),
    "Marathi": (
        "चालेल — कृपया इमेजमधील स्टेप्सनुसार तुमचे WhatsApp करंट लोकेशन शेअर करा, "
        "किंवा योग्य ६-अंकी पिनकोड टाइप करा."
    ),
}

_SHARE_LOCATION_ASK = {
    "English": (
        "Please share your current WhatsApp location using the steps in the image, "
        "or type your 6-digit pincode."
    ),
    "Hindi": (
        "कृपया इमेज में दिए स्टेप्स से अपनी WhatsApp करेंट लोकेशन शेयर करें, "
        "या अपना 6-अंकों का पिनकोड टाइप करें।"
    ),
    "Marathi": (
        "कृपया इमेजमधील स्टेप्सनुसार तुमचे WhatsApp करंट लोकेशन शेअर करा, "
        "किंवा तुमचा ६-अंकी पिनकोड टाइप करा."
    ),
}

_LOCATION_THANKS = {
    "English": "Thanks for sharing your location.",
    "Hindi": "लोकेशन शेयर करने के लिए धन्यवाद।",
    "Marathi": "लोकेशन शेअर केल्याबद्दल धन्यवाद.",
}

_LOCATION_UNREADABLE = {
    "English": (
        "I could not read your location pin. "
        "Please type your 6-digit pincode, or share live location again."
    ),
    "Hindi": (
        "मैं आपका लोकेशन पिन नहीं पढ़ सका। "
        "कृपया अपना 6-अंकों का पिनकोड टाइप करें, या लाइव लोकेशन फिर से शेयर करें।"
    ),
    "Marathi": (
        "मी तुमचा लोकेशन पिन वाचू शकलो नाही. "
        "कृपया तुमचा ६-अंकी पिनकोड टाइप करा, किंवा लाईव्ह लोकेशन पुन्हा शेअर करा."
    ),
}

_LOCATION_NEED_PIN = {
    "English": (
        "Thanks for sharing your location. "
        "Please also type your 6-digit pincode so we can find a nearby dealer."
    ),
    "Hindi": (
        "लोकेशन शेयर करने के लिए धन्यवाद। "
        "कृपया अपना 6-अंकों का पिनकोड भी टाइप करें ताकि हम पास की डीलरशिप ढूँढ सकें।"
    ),
    "Marathi": (
        "लोकेशन शेअर केल्याबद्दल धन्यवाद. "
        "कृपया तुमचा ६-अंकी पिनकोडही टाइप करा जेणेकरून आम्ही जवळची डीलरशिप शोधू शकू."
    ),
}

_LOCATION_NO_DEALER = {
    "English": (
        "I could not find a nearby dealership for that location. "
        "Please type your 6-digit pincode, or share live location again."
    ),
    "Hindi": (
        "उस लोकेशन के लिए पास की डीलरशिप नहीं मिली। "
        "कृपया अपना 6-अंकों का पिनकोड टाइप करें, या लाइव लोकेशन फिर से शेयर करें।"
    ),
    "Marathi": (
        "त्या लोकेशनसाठी जवळची डीलरशिप सापडली नाही. "
        "कृपया तुमचा ६-अंकी पिनकोड टाइप करा, किंवा लाईव्ह लोकेशन पुन्हा शेअर करा."
    ),
}

_BROCHURE_CAPTION = {
    "English": "{product} brochure",
    "Hindi": "{product} ब्रोशर",
    "Marathi": "{product} ब्रॉशर",
}

_STILL_INTERESTED_WITH_NAME = {
    "English": (
        "{name}. Last time, you enquired about {product}. "
        "Are you still planning to purchase this vehicle?\n\n"
        "Press 1 for Yes\n"
        "Press 2 for No"
    ),
    "Hindi": (
        "{name}. पिछली बार आपने {product} के बारे में पूछा था। "
        "क्या आप अभी भी यह वाहन खरीदने की योजना बना रहे हैं?\n\n"
        "हाँ के लिए 1 दबाएँ\n"
        "नहीं के लिए 2 दबाएँ"
    ),
    "Marathi": (
        "{name}. गेल्या वेळी तुम्ही {product} बद्दल चौकशी केली होती. "
        "तुम्ही अजूनही हे वाहन खरेदी करण्याचा विचार करत आहात का?\n\n"
        "होय साठी 1 दाबा\n"
        "नाही साठी 2 दाबा"
    ),
}

_STILL_INTERESTED_NO_NAME = {
    "English": (
        "Last time, you enquired about {product}. "
        "Are you still planning to purchase this vehicle?\n\n"
        "Press 1 for Yes\n"
        "Press 2 for No"
    ),
    "Hindi": (
        "पिछली बार आपने {product} के बारे में पूछा था। "
        "क्या आप अभी भी यह वाहन खरीदने की योजना बना रहे हैं?\n\n"
        "हाँ के लिए 1 दबाएँ\n"
        "नहीं के लिए 2 दबाएँ"
    ),
    "Marathi": (
        "गेल्या वेळी तुम्ही {product} बद्दल चौकशी केली होती. "
        "तुम्ही अजूनही हे वाहन खरेदी करण्याचा विचार करत आहात का?\n\n"
        "होय साठी 1 दाबा\n"
        "नाही साठी 2 दाबा"
    ),
}

_STILL_INTERESTED_NO_THANKS = {
    "English": (
        "Thank you for letting us know. "
        "If you need any help later, feel free to message us."
    ),
    "Hindi": (
        "बताने के लिए धन्यवाद। "
        "अगर बाद में मदद चाहिए तो हमें मैसेज करें।"
    ),
    "Marathi": (
        "कळवल्याबद्दल धन्यवाद. "
        "नंतर मदत हवी असल्यास आम्हाला मेसेज करा."
    ),
}

# Consent gate: dealership details are never volunteered. The customer used
# to get a full name/address/phone/map card dropped into a reply about
# something else entirely, alongside a second question.
_DEALER_SHARE_ASK = {
    "English": "Would you like me to share your nearest dealership details?",
    "Hindi": "क्या मैं आपको आपकी नज़दीकी डीलरशिप की जानकारी भेजूं?",
    "Marathi": "मी तुम्हाला तुमच्या जवळच्या डीलरशिपची माहिती पाठवू का?",
}

# Last resort only: the model returned an empty reply twice in a row. Better
# an open question than silence — the customer used to get nothing back and
# had to type "hello" to restart the bot (bug 240711).
_ACKNOWLEDGEMENT_FALLBACK = {
    "English": "Is there anything else I can help you with?",
    "Hindi": "क्या मैं आपकी और कोई मदद कर सकता हूँ?",
    "Marathi": "मी तुम्हाला आणखी काही मदत करू शकतो का?",
}

_BROCHURE_OFFER_ASK = {
    "English": "Would you like me to send you the brochure for more details?",
    "Hindi": "क्या आप चाहेंगे कि मैं आपको अधिक जानकारी के लिए ब्रोशर भेजूं?",
    "Marathi": "अधिक माहितीसाठी मी तुम्हाला ब्रोशर पाठवू का?",
}

_BROCHURE_WHICH_PRODUCT_ASK = {
    "English": (
        "Which model's brochure should I send — "
        "King EV MAX, King Deluxe, or King Duramax Plus?"
    ),
    "Hindi": (
        "किस मॉडल का ब्रोशर भेजूं — "
        "King EV MAX, King Deluxe, या King Duramax Plus?"
    ),
    "Marathi": (
        "कोणत्या मॉडेलचा ब्रोशर पाठवावा — "
        "King EV MAX, King Deluxe, किंवा King Duramax Plus?"
    ),
}

_WARRANTY_CAPTION = {
    "English": "{product} warranty policy",
    "Hindi": "{product} वारंटी पॉलिसी",
    "Marathi": "{product} वॉरंटी धोरण",
}

_PMS_CAPTION = {
    "English": "{product} PMS schedule",
    "Hindi": "{product} PMS शेड्यूल",
    "Marathi": "{product} PMS शेड्यूल",
}


def _lang(language: str | None) -> str:
    key = (language or "English").strip()
    return key if key in _DEALER_INTRO else "English"


def dealer_confirm_ask(
    *,
    name: str,
    address: str = "",
    phone: str = "",
    spoc_name: str = "",
    map_url: str = "",
    city: str = "",
    language: str = "English",
) -> str:
    lang = _lang(language)
    labels = _LABELS[lang]
    lines = [
        _DEALER_INTRO[lang],
        "",
        f"{labels['name']}: {name or labels['default_dealer']}",
    ]
    if address:
        lines.append(f"{labels['address']}: {address}")
    elif city:
        lines.append(f"{labels['address']}: {city}")
    else:
        lines.append(f"{labels['address']}: {labels['fallback_address']}")
    if phone:
        contact = f"{spoc_name} - {phone}" if spoc_name else phone
        lines.append(f"{labels['phone']}: {contact}")
    if map_url:
        lines.append(f"{labels['map']}: {map_url}")
    lines.extend(["", _DEALER_ASK[lang]])
    return "\n".join(lines)


def wrap_up_dealer_confirm_intro(language: str = "English") -> str:
    return _WRAP_UP_DEALER_CONFIRM_INTRO[_lang(language)]


def place_redirect_message(language: str = "English") -> str:
    return _PLACE_REDIRECT[_lang(language)]


def invalid_pincode_ask(language: str = "English") -> str:
    return _INVALID_PINCODE_ASK[_lang(language)]


def invalid_pincode_location_fallback(language: str = "English") -> str:
    return _INVALID_PINCODE_LOCATION[_lang(language)]


def share_location_ask(language: str = "English") -> str:
    return _SHARE_LOCATION_ASK[_lang(language)]


def location_thanks(language: str = "English") -> str:
    return _LOCATION_THANKS[_lang(language)]


def location_unreadable(language: str = "English") -> str:
    return _LOCATION_UNREADABLE[_lang(language)]


def location_need_pincode(language: str = "English") -> str:
    return _LOCATION_NEED_PIN[_lang(language)]


def location_no_dealer(language: str = "English") -> str:
    return _LOCATION_NO_DEALER[_lang(language)]


def brochure_caption(product: str, language: str = "English") -> str:
    template = _BROCHURE_CAPTION[_lang(language)]
    return template.format(product=product)


def welcome_back_still_interested(
    *,
    name: str = "",
    product: str,
    language: str = "English",
) -> str:
    """Mandatory returning-customer Yes/No ask in the selected language."""
    lang = _lang(language)
    product = (product or "").strip() or "TVS King"
    clean_name = (name or "").strip()
    if clean_name:
        return _STILL_INTERESTED_WITH_NAME[lang].format(
            name=clean_name, product=product
        )
    return _STILL_INTERESTED_NO_NAME[lang].format(product=product)


def still_interested_no_thanks(language: str = "English") -> str:
    return _STILL_INTERESTED_NO_THANKS[_lang(language)]


def dealer_share_ask(language: str = "English") -> str:
    return _DEALER_SHARE_ASK[_lang(language)]


def acknowledgement_fallback(language: str = "English") -> str:
    return _ACKNOWLEDGEMENT_FALLBACK[_lang(language)]


def brochure_offer_ask(language: str = "English") -> str:
    return _BROCHURE_OFFER_ASK[_lang(language)]


def brochure_which_product_ask(language: str = "English") -> str:
    return _BROCHURE_WHICH_PRODUCT_ASK[_lang(language)]


def product_doc_caption(
    product: str, kind: str = "brochure", language: str = "English"
) -> str:
    """Caption for brochure / warranty / PMS document sends."""
    lang = _lang(language)
    if kind == "warranty":
        template = _WARRANTY_CAPTION[lang]
    elif kind == "pms":
        template = _PMS_CAPTION[lang]
    else:
        template = _BROCHURE_CAPTION[lang]
    return template.format(product=product)
