"""Localized static WhatsApp replies (dealer card, location, place redirect).

English / Hindi / Marathi are fully localized. Other supported languages fall
back to English for these mechanical cards until translations are filled in.
"""
from __future__ import annotations

from typing import Any, Sequence

import admin_config

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
    "Telugu": {
        "name": "పేరు",
        "address": "చిరునామా",
        "phone": "ఫోన్",
        "map": "మ్యాప్",
        "fallback_address": "(పూర్తి చిరునామా డీలర్‌షిప్‌ను అడగండి)",
        "default_dealer": "TVS డీలర్‌షిప్",
    },
    "Tamil": {
        "name": "பெயர்",
        "address": "முகவரி",
        "phone": "தொலைபேசி",
        "map": "வரைபடம்",
        "fallback_address": "(முழு முகவரிக்கு டீலர்ஷிப்பைக் கேளுங்கள்)",
        "default_dealer": "TVS டீலர்ஷிப்",
    },
    "Kannada": {
        "name": "ಹೆಸರು",
        "address": "ವಿಳಾಸ",
        "phone": "ಫೋನ್",
        "map": "ನಕ್ಷೆ",
        "fallback_address": "(ಪೂರ್ಣ ವಿಳಾಸಕ್ಕಾಗಿ ಡೀಲರ್‌ಶಿಪ್ ಅನ್ನು ಕೇಳಿ)",
        "default_dealer": "TVS ಡೀಲರ್‌ಶಿಪ್",
    },
    "Malayalam": {
        "name": "പേര്",
        "address": "വിലാസം",
        "phone": "ഫോൺ",
        "map": "മാപ്പ്",
        "fallback_address": "(പൂർണ്ണ വിലാസത്തിന് ഡീലർഷിപ്പിനോട് ചോദിക്കുക)",
        "default_dealer": "TVS ഡീലർഷിപ്പ്",
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

# Declining the vehicle they enquired about last time does not mean they want
# nothing — offer the rest of the range before letting the lead go. Customers
# were being closed out and then coming back a few minutes later asking to see
# something else.
_STILL_INTERESTED_NO_THANKS = {
    "English": (
        "Thank you for letting us know. "
        "Would you like to look at a different TVS passenger model instead?"
    ),
    "Hindi": (
        "बताने के लिए धन्यवाद। "
        "क्या आप कोई दूसरा TVS पैसेंजर मॉडल देखना चाहेंगे?"
    ),
    "Marathi": (
        "कळवल्याबद्दल धन्यवाद. "
        "तुम्हाला दुसरे TVS पॅसेंजर मॉडेल पाहायला आवडेल का?"
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

# Asked once, right after the language menu, before any other bot turn: route
# the customer to the existing vehicle flow or to the locate-nearest-PGM flow.
# Every language is filled in here, not just the three above — the customer has
# just chosen their language and this is the first thing they read in it.
_FLOW_INTENT_ASK = {
    "English": (
        "Are you still interested in the vehicle, or are you looking for the "
        "nearest PGM?\n\n"
        "Press 1 for Vehicle\n"
        "Press 2 for Nearest PGM"
    ),
    "Hindi": (
        "क्या आप अभी भी वाहन में रुचि रखते हैं, या आप नज़दीकी PGM ढूँढ रहे हैं?\n\n"
        "वाहन के लिए 1 दबाएँ\n"
        "नज़दीकी PGM के लिए 2 दबाएँ"
    ),
    "Marathi": (
        "तुम्हाला अजूनही वाहनात रस आहे का, की तुम्ही जवळचे PGM शोधत आहात?\n\n"
        "वाहनासाठी 1 दाबा\n"
        "जवळच्या PGM साठी 2 दाबा"
    ),
    "Telugu": (
        "మీకు ఇంకా వాహనంపై ఆసక్తి ఉందా, లేదా మీరు సమీపంలోని PGM కోసం చూస్తున్నారా?\n\n"
        "వాహనం కోసం 1 నొక్కండి\n"
        "సమీప PGM కోసం 2 నొక్కండి"
    ),
    "Tamil": (
        "நீங்கள் இன்னும் வாகனத்தில் ஆர்வமாக உள்ளீர்களா, அல்லது அருகிலுள்ள PGM-ஐத் "
        "தேடுகிறீர்களா?\n\n"
        "வாகனத்திற்கு 1 ஐ அழுத்தவும்\n"
        "அருகிலுள்ள PGM-க்கு 2 ஐ அழுத்தவும்"
    ),
    "Kannada": (
        "ನೀವು ಇನ್ನೂ ವಾಹನದಲ್ಲಿ ಆಸಕ್ತಿ ಹೊಂದಿದ್ದೀರಾ, ಅಥವಾ ಹತ್ತಿರದ PGM ಅನ್ನು "
        "ಹುಡುಕುತ್ತಿದ್ದೀರಾ?\n\n"
        "ವಾಹನಕ್ಕಾಗಿ 1 ಒತ್ತಿರಿ\n"
        "ಹತ್ತಿರದ PGM ಗಾಗಿ 2 ಒತ್ತಿರಿ"
    ),
    "Malayalam": (
        "നിങ്ങൾക്ക് ഇപ്പോഴും വാഹനത്തിൽ താൽപ്പര്യമുണ്ടോ, അതോ അടുത്തുള്ള PGM "
        "തിരയുകയാണോ?\n\n"
        "വാഹനത്തിന് 1 അമർത്തുക\n"
        "അടുത്തുള്ള PGM-ന് 2 അമർത്തുക"
    ),
}

# First line of the locate-nearest-PGM flow; pgm_location_ask follows it.
_PGM_FLOW_INTRO = {
    "English": "Sure — I'll help you find your nearest PGM.",
    "Hindi": "ज़रूर — मैं आपको नज़दीकी PGM ढूँढने में मदद करूँगा।",
    "Marathi": "नक्की — मी तुम्हाला जवळचे PGM शोधण्यात मदत करेन.",
    "Telugu": "తప్పకుండా — మీకు సమీపంలోని PGM కనుగొనడంలో నేను సహాయం చేస్తాను.",
    "Tamil": "நிச்சயமாக — அருகிலுள்ள PGM-ஐக் கண்டறிய நான் உதவுகிறேன்.",
    "Kannada": "ಖಂಡಿತ — ಹತ್ತಿರದ PGM ಅನ್ನು ಹುಡುಕಲು ನಾನು ಸಹಾಯ ಮಾಡುತ್ತೇನೆ.",
    "Malayalam": "തീർച്ചയായും — അടുത്തുള്ള PGM കണ്ടെത്താൻ ഞാൻ സഹായിക്കാം.",
}

# The PGM flow accepts a third answer the vehicle flow does not: the name of
# the place where the customer wants a service centre, which is resolved to
# a pincode by web search (bot/pgm_graph.py).
_PGM_LOCATION_ASK = {
    "English": (
        "Please share your current WhatsApp location, type your 6-digit pincode, "
        "or type the name of the city/area where you would like to see the "
        "service centre."
    ),
    "Hindi": (
        "कृपया अपनी WhatsApp करेंट लोकेशन शेयर करें, अपना 6-अंकों का पिनकोड टाइप करें, "
        "या उस शहर/एरिया का नाम टाइप करें जहाँ आप सर्विस सेंटर देखना चाहते हैं।"
    ),
    "Marathi": (
        "कृपया तुमचे WhatsApp करंट लोकेशन शेअर करा, तुमचा ६-अंकी पिनकोड टाइप करा, "
        "किंवा ज्या शहर/एरियामध्ये तुम्हाला सर्व्हिस सेंटर पाहायचे आहे त्याचे नाव टाइप करा."
    ),
    "Telugu": (
        "దయచేసి మీ WhatsApp ప్రస్తుత లొకేషన్ షేర్ చేయండి, మీ 6-అంకెల పిన్‌కోడ్ టైప్ చేయండి, "
        "లేదా మీరు సర్వీస్ సెంటర్ చూడాలనుకుంటున్న నగరం/ప్రాంతం పేరు టైప్ చేయండి."
    ),
    "Tamil": (
        "உங்கள் WhatsApp தற்போதைய இருப்பிடத்தைப் பகிரவும், உங்கள் 6-இலக்க பின்கோடை "
        "டைப் செய்யவும், அல்லது சர்வீஸ் சென்டர் பார்க்க விரும்பும் நகரம்/பகுதியின் "
        "பெயரை டைப் செய்யவும்."
    ),
    "Kannada": (
        "ದಯವಿಟ್ಟು ನಿಮ್ಮ WhatsApp ಪ್ರಸ್ತುತ ಲೊಕೇಶನ್ ಹಂಚಿಕೊಳ್ಳಿ, ನಿಮ್ಮ 6-ಅಂಕಿಯ ಪಿನ್‌ಕೋಡ್ "
        "ಟೈಪ್ ಮಾಡಿ, ಅಥವಾ ನೀವು ಸರ್ವಿಸ್ ಸೆಂಟರ್ ನೋಡಲು ಬಯಸುವ ನಗರ/ಪ್ರದೇಶದ ಹೆಸರನ್ನು ಟೈಪ್ ಮಾಡಿ."
    ),
    "Malayalam": (
        "ദയവായി നിങ്ങളുടെ WhatsApp നിലവിലെ ലൊക്കേഷൻ പങ്കിടുക, നിങ്ങളുടെ 6-അക്ക പിൻകോഡ് "
        "ടൈപ്പ് ചെയ്യുക, അല്ലെങ്കിൽ സർവീസ് സെന്റർ കാണാൻ ആഗ്രഹിക്കുന്ന നഗരം/പ്രദേശത്തിന്റെ "
        "പേര് ടൈപ്പ് ചെയ്യുക."
    ),
}

_PGM_PINCODE_NOTED = {
    "English": "Thanks — I have noted pincode {pincode} for your nearest service centre.",
    "Hindi": "धन्यवाद — आपके नज़दीकी सर्विस सेंटर के लिए पिनकोड {pincode} नोट कर लिया है।",
    "Marathi": "धन्यवाद — तुमच्या जवळच्या सर्व्हिस सेंटरसाठी पिनकोड {pincode} नोंदवला आहे.",
    "Telugu": "ధన్యవాదాలు — మీ సమీప సర్వీస్ సెంటర్ కోసం పిన్‌కోడ్ {pincode} నోట్ చేసుకున్నాను.",
    "Tamil": "நன்றி — உங்கள் அருகிலுள்ள சர்வீஸ் சென்டருக்காக பின்கோடு {pincode} குறித்துக்கொண்டேன்.",
    "Kannada": "ಧನ್ಯವಾದಗಳು — ನಿಮ್ಮ ಹತ್ತಿರದ ಸರ್ವಿಸ್ ಸೆಂಟರ್‌ಗಾಗಿ ಪಿನ್‌ಕೋಡ್ {pincode} ನೋಟ್ ಮಾಡಿಕೊಂಡಿದ್ದೇನೆ.",
    "Malayalam": "നന്ദി — നിങ്ങളുടെ അടുത്തുള്ള സർവീസ് സെന്ററിനായി പിൻകോഡ് {pincode} കുറിച്ചു.",
}

# Web search could not pin the place down: ask for something bigger rather
# than looping on the same name.
_PGM_ASK_BIGGER_CITY = {
    "English": (
        "I could not find a pincode for that place. Please type the name of the "
        "nearest big city or town, or your 6-digit pincode."
    ),
    "Hindi": (
        "उस जगह का पिनकोड नहीं मिला। कृपया नज़दीकी बड़े शहर या कस्बे का नाम टाइप करें, "
        "या अपना 6-अंकों का पिनकोड टाइप करें।"
    ),
    "Marathi": (
        "त्या ठिकाणाचा पिनकोड सापडला नाही. कृपया जवळच्या मोठ्या शहराचे किंवा गावाचे "
        "नाव टाइप करा, किंवा तुमचा ६-अंकी पिनकोड टाइप करा."
    ),
    "Telugu": (
        "ఆ ప్రదేశానికి పిన్‌కోడ్ దొరకలేదు. దయచేసి సమీపంలోని పెద్ద నగరం లేదా పట్టణం పేరు "
        "టైప్ చేయండి, లేదా మీ 6-అంకెల పిన్‌కోడ్ టైప్ చేయండి."
    ),
    "Tamil": (
        "அந்த இடத்திற்கான பின்கோடு கிடைக்கவில்லை. அருகிலுள்ள பெரிய நகரம் அல்லது ஊரின் "
        "பெயரை டைப் செய்யவும், அல்லது உங்கள் 6-இலக்க பின்கோடை டைப் செய்யவும்."
    ),
    "Kannada": (
        "ಆ ಸ್ಥಳದ ಪಿನ್‌ಕೋಡ್ ಸಿಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಹತ್ತಿರದ ದೊಡ್ಡ ನಗರ ಅಥವಾ ಪಟ್ಟಣದ ಹೆಸರನ್ನು "
        "ಟೈಪ್ ಮಾಡಿ, ಅಥವಾ ನಿಮ್ಮ 6-ಅಂಕಿಯ ಪಿನ್‌ಕೋಡ್ ಟೈಪ್ ಮಾಡಿ."
    ),
    "Malayalam": (
        "ആ സ്ഥലത്തിന്റെ പിൻകോഡ് കണ്ടെത്താനായില്ല. ദയവായി അടുത്തുള്ള വലിയ നഗരത്തിന്റെയോ "
        "പട്ടണത്തിന്റെയോ പേര് ടൈപ്പ് ചെയ്യുക, അല്ലെങ്കിൽ നിങ്ങളുടെ 6-അക്ക പിൻകോഡ് ടൈപ്പ് ചെയ്യുക."
    ),
}

# The search itself failed (quota, network, key). Distinct from "not found":
# the place may be perfectly real, so do not send the customer hunting for a
# bigger city — a pincode needs no lookup at all.
_PGM_LOOKUP_FAILED = {
    "English": (
        "I could not look that place up right now. Please type your 6-digit "
        "pincode, or share your current WhatsApp location."
    ),
    "Hindi": (
        "अभी उस जगह की जानकारी नहीं मिल पाई। कृपया अपना 6-अंकों का पिनकोड टाइप करें, "
        "या अपनी WhatsApp करेंट लोकेशन शेयर करें।"
    ),
    "Marathi": (
        "सध्या ते ठिकाण शोधता आले नाही. कृपया तुमचा ६-अंकी पिनकोड टाइप करा, "
        "किंवा तुमचे WhatsApp करंट लोकेशन शेअर करा."
    ),
    "Telugu": (
        "ప్రస్తుతం ఆ ప్రదేశాన్ని వెతకలేకపోయాను. దయచేసి మీ 6-అంకెల పిన్‌కోడ్ టైప్ చేయండి, "
        "లేదా మీ WhatsApp ప్రస్తుత లొకేషన్ షేర్ చేయండి."
    ),
    "Tamil": (
        "இப்போது அந்த இடத்தைத் தேட முடியவில்லை. உங்கள் 6-இலக்க பின்கோடை டைப் செய்யவும், "
        "அல்லது உங்கள் WhatsApp தற்போதைய இருப்பிடத்தைப் பகிரவும்."
    ),
    "Kannada": (
        "ಈಗ ಆ ಸ್ಥಳವನ್ನು ಹುಡುಕಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ನಿಮ್ಮ 6-ಅಂಕಿಯ ಪಿನ್‌ಕೋಡ್ ಟೈಪ್ ಮಾಡಿ, "
        "ಅಥವಾ ನಿಮ್ಮ WhatsApp ಪ್ರಸ್ತುತ ಲೊಕೇಶನ್ ಹಂಚಿಕೊಳ್ಳಿ."
    ),
    "Malayalam": (
        "ഇപ്പോൾ ആ സ്ഥലം തിരയാനായില്ല. ദയവായി നിങ്ങളുടെ 6-അക്ക പിൻകോഡ് ടൈപ്പ് ചെയ്യുക, "
        "അല്ലെങ്കിൽ നിങ്ങളുടെ WhatsApp നിലവിലെ ലൊക്കേഷൻ പങ്കിടുക."
    ),
}


# --- admin-editable overrides ----------------------------------------------
#
# Every string above is a default, not the last word: config["messages"] may
# override any of them per language. Overrides are sparse -- config carries
# only what an operator actually changed -- so a message added to this file
# appears everywhere immediately, with nothing to back-fill into configs that
# were written before it existed.
# --- PGM results -------------------------------------------------------------
# Header above the ranked list. Two keys rather than a {where} placeholder:
# "pincode 560097" and "your shared location" decline differently per language.
_PGM_NEAREST_FOR_PINCODE = {
    "English": "Nearest PGMs to pincode {pincode}:",
    "Hindi": "पिनकोड {pincode} के नज़दीकी PGM:",
    "Marathi": "पिनकोड {pincode} जवळचे PGM:",
    "Telugu": "పిన్‌కోడ్ {pincode}కి సమీపంలోని PGMలు:",
    "Tamil": "பின்கோடு {pincode}-க்கு அருகிலுள்ள PGM-கள்:",
    "Kannada": "ಪಿನ್‌ಕೋಡ್ {pincode} ಹತ್ತಿರದ PGMಗಳು:",
    "Malayalam": "പിൻകോഡ് {pincode}-ന് അടുത്തുള്ള PGM-കൾ:",
}

_PGM_NEAREST_FOR_LOCATION = {
    "English": "Nearest PGMs to your shared location:",
    "Hindi": "आपकी शेयर की गई लोकेशन के नज़दीकी PGM:",
    "Marathi": "तुम्ही शेअर केलेल्या लोकेशनजवळचे PGM:",
    "Telugu": "మీరు షేర్ చేసిన లొకేషన్‌కి సమీపంలోని PGMలు:",
    "Tamil": "நீங்கள் பகிர்ந்த இருப்பிடத்திற்கு அருகிலுள்ள PGM-கள்:",
    "Kannada": "ನೀವು ಹಂಚಿಕೊಂಡ ಲೊಕೇಶನ್ ಹತ್ತಿರದ PGMಗಳು:",
    "Malayalam": "നിങ്ങൾ പങ്കിട്ട ലൊക്കേഷന് അടുത്തുള്ള PGM-കൾ:",
}

# Closes the list, and is the whole reply when a customer with a list in
# front of them types something that is neither a pick nor a new place.
_PGM_RESULTS_FOOTER = {
    "English": (
        "Reply 1, 2 or 3 for the address and map link, or share another "
        "location or pincode to search again."
    ),
    "Hindi": (
        "पता और मैप लिंक के लिए 1, 2 या 3 भेजें, या दोबारा खोजने के लिए "
        "दूसरी लोकेशन या पिनकोड भेजें।"
    ),
    "Marathi": (
        "पत्ता आणि नकाशा लिंकसाठी 1, 2 किंवा 3 पाठवा, किंवा पुन्हा शोधण्यासाठी "
        "दुसरे लोकेशन किंवा पिनकोड पाठवा."
    ),
    "Telugu": (
        "చిరునామా మరియు మ్యాప్ లింక్ కోసం 1, 2 లేదా 3 పంపండి, లేదా మళ్ళీ వెతకడానికి "
        "మరో లొకేషన్ లేదా పిన్‌కోడ్ పంపండి."
    ),
    "Tamil": (
        "முகவரி மற்றும் வரைபட இணைப்புக்கு 1, 2 அல்லது 3 அனுப்பவும், அல்லது மீண்டும் "
        "தேட வேறு இருப்பிடம் அல்லது பின்கோடை அனுப்பவும்."
    ),
    "Kannada": (
        "ವಿಳಾಸ ಮತ್ತು ನಕ್ಷೆ ಲಿಂಕ್‌ಗಾಗಿ 1, 2 ಅಥವಾ 3 ಕಳುಹಿಸಿ, ಅಥವಾ ಮತ್ತೆ ಹುಡುಕಲು "
        "ಬೇರೆ ಲೊಕೇಶನ್ ಅಥವಾ ಪಿನ್‌ಕೋಡ್ ಕಳುಹಿಸಿ."
    ),
    "Malayalam": (
        "വിലാസവും മാപ്പ് ലിങ്കും ലഭിക്കാൻ 1, 2 അല്ലെങ്കിൽ 3 അയയ്ക്കുക, അല്ലെങ്കിൽ വീണ്ടും "
        "തിരയാൻ മറ്റൊരു ലൊക്കേഷനോ പിൻകോഡോ അയയ്ക്കുക."
    ),
}

# The location resolved, but no listed PGM lies inside the search radius.
_PGM_NONE_NEARBY = {
    "English": (
        "Sorry, there is no PGM listed within {km} km of that location yet. "
        "You can try another pincode or area name, or share your location."
    ),
    "Hindi": (
        "माफ़ कीजिए, उस जगह से {km} किमी के अंदर अभी कोई PGM सूचीबद्ध नहीं है। "
        "आप दूसरा पिनकोड या एरिया नाम आज़मा सकते हैं, या अपनी लोकेशन शेयर कर सकते हैं।"
    ),
    "Marathi": (
        "माफ करा, त्या ठिकाणापासून {km} किमीच्या आत सध्या कोणतेही PGM नोंदलेले नाही. "
        "तुम्ही दुसरा पिनकोड किंवा एरियाचे नाव पाठवू शकता, किंवा तुमचे लोकेशन शेअर करू शकता."
    ),
    "Telugu": (
        "క్షమించండి, ఆ ప్రదేశానికి {km} కి.మీ. లోపల ప్రస్తుతం ఏ PGM నమోదు కాలేదు. "
        "మీరు మరో పిన్‌కోడ్ లేదా ఏరియా పేరు ప్రయత్నించవచ్చు, లేదా మీ లొకేషన్ షేర్ చేయవచ్చు."
    ),
    "Tamil": (
        "மன்னிக்கவும், அந்த இடத்திலிருந்து {km} கி.மீ.க்குள் தற்போது எந்த PGM-ும் பதிவாகவில்லை. "
        "வேறு பின்கோடு அல்லது பகுதியின் பெயரை முயற்சிக்கலாம், அல்லது உங்கள் இருப்பிடத்தைப் பகிரலாம்."
    ),
    "Kannada": (
        "ಕ್ಷಮಿಸಿ, ಆ ಸ್ಥಳದಿಂದ {km} ಕಿ.ಮೀ. ಒಳಗೆ ಸದ್ಯಕ್ಕೆ ಯಾವುದೇ PGM ಪಟ್ಟಿಯಲ್ಲಿಲ್ಲ. "
        "ನೀವು ಬೇರೆ ಪಿನ್‌ಕೋಡ್ ಅಥವಾ ಏರಿಯಾ ಹೆಸರನ್ನು ಪ್ರಯತ್ನಿಸಬಹುದು, ಅಥವಾ ನಿಮ್ಮ ಲೊಕೇಶನ್ ಹಂಚಿಕೊಳ್ಳಬಹುದು."
    ),
    "Malayalam": (
        "ക്ഷമിക്കണം, ആ സ്ഥലത്തുനിന്ന് {km} കി.മീ.യ്ക്കുള്ളിൽ ഇപ്പോൾ ഒരു PGM-ഉം ലിസ്റ്റിലില്ല. "
        "മറ്റൊരു പിൻകോഡോ പ്രദേശത്തിന്റെ പേരോ ശ്രമിക്കാം, അല്ലെങ്കിൽ നിങ്ങളുടെ ലൊക്കേഷൻ പങ്കിടാം."
    ),
}

# A well-formed pincode the geocoder could not place. A location pin needs
# no geocoding, so it is the first thing offered.
_PGM_PINCODE_UNRESOLVED = {
    "English": (
        "I could not locate pincode {pincode}. Please share your current "
        "WhatsApp location, or type the name of your city or area."
    ),
    "Hindi": (
        "पिनकोड {pincode} की लोकेशन नहीं मिल पाई। कृपया अपनी WhatsApp करेंट लोकेशन "
        "शेयर करें, या अपने शहर या एरिया का नाम टाइप करें।"
    ),
    "Marathi": (
        "पिनकोड {pincode} चे ठिकाण सापडले नाही. कृपया तुमचे WhatsApp करंट लोकेशन "
        "शेअर करा, किंवा तुमच्या शहराचे किंवा एरियाचे नाव टाइप करा."
    ),
    "Telugu": (
        "పిన్‌కోడ్ {pincode} స్థానం కనుగొనలేకపోయాను. దయచేసి మీ WhatsApp ప్రస్తుత లొకేషన్ "
        "షేర్ చేయండి, లేదా మీ నగరం లేదా ఏరియా పేరు టైప్ చేయండి."
    ),
    "Tamil": (
        "பின்கோடு {pincode}-இன் இடத்தைக் கண்டறிய முடியவில்லை. உங்கள் WhatsApp தற்போதைய "
        "இருப்பிடத்தைப் பகிரவும், அல்லது உங்கள் நகரம் அல்லது பகுதியின் பெயரை டைப் செய்யவும்."
    ),
    "Kannada": (
        "ಪಿನ್‌ಕೋಡ್ {pincode} ಸ್ಥಳವನ್ನು ಹುಡುಕಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ನಿಮ್ಮ WhatsApp ಪ್ರಸ್ತುತ "
        "ಲೊಕೇಶನ್ ಹಂಚಿಕೊಳ್ಳಿ, ಅಥವಾ ನಿಮ್ಮ ನಗರ ಅಥವಾ ಏರಿಯಾದ ಹೆಸರನ್ನು ಟೈಪ್ ಮಾಡಿ."
    ),
    "Malayalam": (
        "പിൻകോഡ് {pincode}-ന്റെ സ്ഥാനം കണ്ടെത്താനായില്ല. ദയവായി നിങ്ങളുടെ WhatsApp നിലവിലെ "
        "ലൊക്കേഷൻ പങ്കിടുക, അല്ലെങ്കിൽ നിങ്ങളുടെ നഗരത്തിന്റെയോ പ്രദേശത്തിന്റെയോ പേര് ടൈപ്പ് ചെയ്യുക."
    ),
}


MESSAGE_DEFAULTS: dict[str, dict[str, str]] = {
    "dealer_intro": _DEALER_INTRO,
    "dealer_ask": _DEALER_ASK,
    "wrap_up_dealer_confirm_intro": _WRAP_UP_DEALER_CONFIRM_INTRO,
    "place_redirect": _PLACE_REDIRECT,
    "invalid_pincode_ask": _INVALID_PINCODE_ASK,
    "invalid_pincode_location": _INVALID_PINCODE_LOCATION,
    "share_location_ask": _SHARE_LOCATION_ASK,
    "location_thanks": _LOCATION_THANKS,
    "location_unreadable": _LOCATION_UNREADABLE,
    "location_need_pincode": _LOCATION_NEED_PIN,
    "location_no_dealer": _LOCATION_NO_DEALER,
    "brochure_caption": _BROCHURE_CAPTION,
    "still_interested_with_name": _STILL_INTERESTED_WITH_NAME,
    "still_interested_no_name": _STILL_INTERESTED_NO_NAME,
    "still_interested_no_thanks": _STILL_INTERESTED_NO_THANKS,
    "dealer_share_ask": _DEALER_SHARE_ASK,
    "acknowledgement_fallback": _ACKNOWLEDGEMENT_FALLBACK,
    "brochure_offer_ask": _BROCHURE_OFFER_ASK,
    "brochure_which_product_ask": _BROCHURE_WHICH_PRODUCT_ASK,
    "warranty_caption": _WARRANTY_CAPTION,
    "pms_caption": _PMS_CAPTION,
    "flow_intent_ask": _FLOW_INTENT_ASK,
    "pgm_flow_intro": _PGM_FLOW_INTRO,
    "pgm_location_ask": _PGM_LOCATION_ASK,
    "pgm_pincode_noted": _PGM_PINCODE_NOTED,
    "pgm_ask_bigger_city": _PGM_ASK_BIGGER_CITY,
    "pgm_lookup_failed": _PGM_LOOKUP_FAILED,
    "pgm_nearest_for_pincode": _PGM_NEAREST_FOR_PINCODE,
    "pgm_nearest_for_location": _PGM_NEAREST_FOR_LOCATION,
    "pgm_results_footer": _PGM_RESULTS_FOOTER,
    "pgm_none_nearby": _PGM_NONE_NEARBY,
    "pgm_pincode_unresolved": _PGM_PINCODE_UNRESOLVED,
}

# The dealer card's field labels are one dict of dicts; flattened here so each
# label is editable on its own rather than as an opaque blob.
for _label in ("name", "address", "phone", "map", "fallback_address", "default_dealer"):
    MESSAGE_DEFAULTS[f"dealer_label_{_label}"] = {
        _lang_code: _values[_label] for _lang_code, _values in _LABELS.items()
    }
del _label

# What each message may interpolate. A template naming anything else is
# rejected on write: .format() raises KeyError, and that would surface as a
# failed turn to a customer rather than as an error to the operator.
MESSAGE_PLACEHOLDERS: dict[str, frozenset[str]] = {
    "brochure_caption": frozenset({"product"}),
    "warranty_caption": frozenset({"product"}),
    "pms_caption": frozenset({"product"}),
    "still_interested_with_name": frozenset({"name", "product"}),
    "still_interested_no_name": frozenset({"product"}),
    "pgm_pincode_noted": frozenset({"pincode"}),
    "pgm_nearest_for_pincode": frozenset({"pincode"}),
    "pgm_none_nearby": frozenset({"km"}),
    "pgm_pincode_unresolved": frozenset({"pincode"}),
}


def placeholders_for(key: str) -> frozenset[str]:
    return MESSAGE_PLACEHOLDERS.get(key, frozenset())


def message_keys() -> list[str]:
    return sorted(MESSAGE_DEFAULTS)


def _overrides() -> dict[str, Any]:
    """Admin overrides, read per call — same reload-on-read contract as the
    rest of the bot. A broken config must not silence the bot, so any failure
    reading it falls through to the built-in wording."""
    try:
        messages = admin_config.get_store().get().get("messages")
    except Exception:
        return {}
    return messages if isinstance(messages, dict) else {}


def _pick(source: dict[str, Any], language: str) -> str:
    value = (source or {}).get(language)
    return value if isinstance(value, str) and value.strip() else ""


def message_text(key: str, language: str | None = "English") -> str:
    """The wording for one message: override, then built-in, then English.

    Falling back per language rather than per message is what lets an operator
    translate Telugu without also having to supply every other language.
    """
    lang = (language or "English").strip() or "English"
    override = _overrides().get(key) or {}
    defaults = MESSAGE_DEFAULTS.get(key, {})
    for source in (override, defaults):
        text = _pick(source, lang)
        if text:
            return text
    for source in (override, defaults):
        text = _pick(source, "English")
        if text:
            return text
    return ""


def render_message(key: str, language: str | None = "English", **values: Any) -> str:
    """Interpolate a message, surviving an override with a bad placeholder.

    Validation rejects those on write, but config can also reach disk by hand
    or from a restored backup. A typo must cost the operator their override,
    never cost a customer their reply.
    """
    text = message_text(key, language)
    try:
        return text.format(**values)
    except (KeyError, IndexError, ValueError):
        lang = (language or "English").strip() or "English"
        defaults = MESSAGE_DEFAULTS.get(key, {})
        fallback = _pick(defaults, lang) or _pick(defaults, "English")
        try:
            return fallback.format(**values)
        except (KeyError, IndexError, ValueError):
            return fallback


def _lang(language: str | None) -> str:
    """Kept for callers that still ask which language will actually be used."""
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
    def label(which: str) -> str:
        return message_text(f"dealer_label_{which}", language)

    lines = [
        message_text("dealer_intro", language),
        "",
        f"{label('name')}: {name or label('default_dealer')}",
    ]
    if address:
        lines.append(f"{label('address')}: {address}")
    elif city:
        lines.append(f"{label('address')}: {city}")
    else:
        lines.append(f"{label('address')}: {label('fallback_address')}")
    if phone:
        contact = f"{spoc_name} - {phone}" if spoc_name else phone
        lines.append(f"{label('phone')}: {contact}")
    if map_url:
        lines.append(f"{label('map')}: {map_url}")
    lines.extend(["", message_text("dealer_ask", language)])
    return "\n".join(lines)


def wrap_up_dealer_confirm_intro(language: str = "English") -> str:
    return message_text("wrap_up_dealer_confirm_intro", language)


def place_redirect_message(language: str = "English") -> str:
    return message_text("place_redirect", language)


def invalid_pincode_ask(language: str = "English") -> str:
    return message_text("invalid_pincode_ask", language)


def invalid_pincode_location_fallback(language: str = "English") -> str:
    return message_text("invalid_pincode_location", language)


def share_location_ask(language: str = "English") -> str:
    return message_text("share_location_ask", language)


def location_thanks(language: str = "English") -> str:
    return message_text("location_thanks", language)


def location_unreadable(language: str = "English") -> str:
    return message_text("location_unreadable", language)


def location_need_pincode(language: str = "English") -> str:
    return message_text("location_need_pincode", language)


def location_no_dealer(language: str = "English") -> str:
    return message_text("location_no_dealer", language)


def brochure_caption(product: str, language: str = "English") -> str:
    return render_message("brochure_caption", language, product=product)


def welcome_back_still_interested(
    *,
    name: str = "",
    product: str,
    language: str = "English",
) -> str:
    """Mandatory returning-customer Yes/No ask in the selected language."""
    product = (product or "").strip() or "TVS King"
    clean_name = (name or "").strip()
    if clean_name:
        return render_message(
            "still_interested_with_name", language, name=clean_name, product=product
        )
    return render_message("still_interested_no_name", language, product=product)


def still_interested_no_thanks(language: str = "English") -> str:
    return message_text("still_interested_no_thanks", language)


def dealer_share_ask(language: str = "English") -> str:
    return message_text("dealer_share_ask", language)


def acknowledgement_fallback(language: str = "English") -> str:
    return message_text("acknowledgement_fallback", language)


def brochure_offer_ask(language: str = "English") -> str:
    return message_text("brochure_offer_ask", language)


def brochure_which_product_ask(language: str = "English") -> str:
    return message_text("brochure_which_product_ask", language)


def flow_intent_ask(language: str = "English") -> str:
    """Vehicle-or-nearest-PGM routing question, in the language just chosen."""
    return message_text("flow_intent_ask", language)


def pgm_flow_intro(language: str = "English") -> str:
    return message_text("pgm_flow_intro", language)


def pgm_location_ask(language: str = "English") -> str:
    return message_text("pgm_location_ask", language)


def pgm_pincode_noted(pincode: str, language: str = "English") -> str:
    return render_message("pgm_pincode_noted", language, pincode=pincode)


def pgm_ask_bigger_city(language: str = "English") -> str:
    return message_text("pgm_ask_bigger_city", language)


def pgm_lookup_failed(language: str = "English") -> str:
    return message_text("pgm_lookup_failed", language)


def pgm_none_nearby(max_km: float, language: str = "English") -> str:
    return render_message("pgm_none_nearby", language, km=f"{max_km:g}")


def pgm_pincode_unresolved(pincode: str, language: str = "English") -> str:
    return render_message("pgm_pincode_unresolved", language, pincode=pincode)


def pgm_results_footer(language: str = "English") -> str:
    return message_text("pgm_results_footer", language)


def pgm_results_list(
    pgms: Sequence[Any],
    *,
    pincode: str = "",
    language: str = "English",
) -> str:
    """The ranked list: a numbered line per PGM with its area, distance and
    phone, so most customers need nothing further; the address and map link
    wait behind the pick to keep the message short."""
    if pincode:
        header = render_message("pgm_nearest_for_pincode", language, pincode=pincode)
    else:
        header = message_text("pgm_nearest_for_location", language)
    phone_label = message_text("dealer_label_phone", language)
    lines = [header, ""]
    for number, pgm in enumerate(pgms, start=1):
        title = pgm.name
        if pgm.area and pgm.area.lower() not in pgm.name.lower():
            title = f"{pgm.name} — {pgm.area}"
        if pgm.distance_km is not None:
            title = f"{title} ({pgm.distance_km:.1f} km)"
        lines.append(f"{number}. {title}")
        if pgm.phone:
            lines.append(f"   {phone_label}: {pgm.phone}")
    lines.extend(["", message_text("pgm_results_footer", language)])
    return "\n".join(lines)


def pgm_card(pgm: Any, *, language: str = "English") -> str:
    """One PGM in full, in the dealer card's shape and with its labels."""

    def label(which: str) -> str:
        return message_text(f"dealer_label_{which}", language)

    lines = [f"{label('name')}: {pgm.name}"]
    if pgm.address:
        lines.append(f"{label('address')}: {pgm.address}")
    elif pgm.area:
        lines.append(f"{label('address')}: {pgm.area}")
    if pgm.phone:
        contact = f"{pgm.owner_name} - {pgm.phone}" if pgm.owner_name else pgm.phone
        lines.append(f"{label('phone')}: {contact}")
    if pgm.map_url:
        lines.append(f"{label('map')}: {pgm.map_url}")
    return "\n".join(lines)


def product_doc_caption(
    product: str, kind: str = "brochure", language: str = "English"
) -> str:
    """Caption for brochure / warranty / PMS document sends."""
    key = {
        "warranty": "warranty_caption",
        "pms": "pms_caption",
    }.get(kind, "brochure_caption")
    return render_message(key, language, product=product)
