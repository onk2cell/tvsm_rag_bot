"""Generate a RAG-optimised knowledge PDF for the TVS King EV MAX.

Design goals (why this beats the marketing brochure as a retrieval source):
  - Real, selectable text (not images) so File Search can extract it.
  - Every section restates "TVS King EV MAX" so each retrieved chunk stands alone.
  - Specs written as "Label: Value" lines instead of a visual table.
  - A large FAQ written the way customers actually ask questions.

Usage:  python build_kb_pdf.py   ->  writes tvs_king_ev_max_kb.pdf
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem,
)

OUT = "tvs_king_ev_max_kb.pdf"

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=18, spaceAfter=6, spaceBefore=12)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13, spaceAfter=4, spaceBefore=10)
BODY = ParagraphStyle("BODY", parent=styles["BodyText"], fontSize=10.5, leading=15, alignment=TA_LEFT, spaceAfter=4)
Q = ParagraphStyle("Q", parent=BODY, fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=2)


def kv(label, value):
    return Paragraph(f"<b>{label}:</b> {value}", BODY)


def faq(question, answer):
    return [Paragraph(f"Q: {question}", Q), Paragraph(f"A: {answer}", BODY)]


def build():
    doc = SimpleDocTemplate(
        OUT, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
        title="TVS King EV MAX - Product Knowledge Base",
    )
    s = []

    s.append(Paragraph("TVS King EV MAX - Product Knowledge Base", H1))
    s.append(Paragraph(
        "This document contains the official specifications, features, charging, warranty and "
        "support information for the TVS King EV MAX electric three-wheeler (electric auto rickshaw) "
        "from TVS Motor Company. Tagline: \"Mushkil Raaste Ab Bane Aasaan\" / \"Aage Badho. Aaram Se.\"",
        BODY))

    # Overview
    s.append(Paragraph("Overview", H2))
    s.append(Paragraph(
        "The TVS King EV MAX is an electric three-wheeler (e-auto / electric passenger rickshaw). "
        "It offers a certified range of 179 km on a full charge, a best-in-class top speed of 60 km/h, "
        "and fast charging from 0 to 80 percent in 2 hours 15 minutes. It is India's first connected "
        "three-wheeler, featuring TVS SmartXonnect with Bluetooth connectivity. The TVS King EV MAX "
        "comes with a comprehensive 6-year / 150,000 km warranty.", BODY))

    # Highlights
    s.append(Paragraph("Key Highlights of the TVS King EV MAX", H2))
    highlights = [
        "Certified range of 179 km per full charge.",
        "Best-in-class pickup and top speed of 60 km/h.",
        "Fast charging: 0 to 80 percent in 2 hours 15 minutes; 0 to 100 percent in 3 hours 30 minutes.",
        "India's first connected three-wheeler with TVS SmartXonnect (Bluetooth).",
        "LED headlamp and LED lights as standard.",
        "Comprehensive 6-year / 150,000 km warranty.",
        "Three drive modes: Eco, City and Power.",
        "Water-wading capability of 500 mm.",
    ]
    s.append(ListFlowable([ListItem(Paragraph(h, BODY)) for h in highlights], bulletType="bullet"))

    # Powertrain
    s.append(Paragraph("Powertrain and Motor (TVS King EV MAX)", H2))
    s.append(kv("Motor type", "Permanent Magnet Synchronous Motor (PMSM)"))
    s.append(kv("Maximum power", "11 kW"))
    s.append(kv("Maximum torque", "40 Nm"))
    s.append(kv("Transmission", "1 forward speed and 1 reverse speed"))
    s.append(kv("Drive modes", "3 modes - Eco, City and Power"))

    # Battery & charging
    s.append(Paragraph("Battery and Charging (TVS King EV MAX)", H2))
    s.append(kv("Battery type", "51.2 V Lithium-Ion LFP (Lithium Iron Phosphate)"))
    s.append(kv("Battery capacity", "9.2 kWh"))
    s.append(kv("Charger type", "Off-board charger with theft-proof protection"))
    s.append(kv("Charger capacity", "3 kW"))
    s.append(kv("Charging time (0 to 100 percent)", "3 hours 30 minutes"))
    s.append(kv("Charging time (0 to 80 percent)", "2 hours 15 minutes"))

    # Performance
    s.append(Paragraph("Performance and Range (TVS King EV MAX)", H2))
    s.append(kv("Certified range", "179 km on a full charge"))
    s.append(kv("Maximum speed", "60 km/h"))
    s.append(kv("Top speed in Eco mode", "40 km/h"))
    s.append(kv("Top speed in City mode", "50 km/h"))
    s.append(kv("Top speed in Power mode", "60 km/h"))
    s.append(kv("Gradeability", "31 percent"))
    s.append(kv("Water-wading capability", "500 mm"))

    # Brakes, suspension, wheels
    s.append(Paragraph("Brakes, Suspension, Wheels and Tyres (TVS King EV MAX)", H2))
    s.append(kv("Brakes (front and rear)", "Drum brakes, individually controlled on each wheel, foot operated"))
    s.append(kv("Front suspension", "Leading arm with coil spring"))
    s.append(kv("Rear suspension", "Hydraulic damper trailing arm with coil spring"))
    s.append(kv("Rim size (front and rear)", "3.5B x 12"))
    s.append(kv("Tyre size (front and rear)", "120/80 R12 6 PR, radial tubeless"))

    # Dimensions
    s.append(Paragraph("Dimensions and Capacity (TVS King EV MAX)", H2))
    s.append(kv("Wheelbase", "2,000 mm"))
    s.append(kv("Wheel track", "1,160 mm"))
    s.append(kv("Overall length", "2,780 mm"))
    s.append(kv("Overall width", "1,320 mm"))
    s.append(kv("Overall height", "1,800 mm"))
    s.append(kv("Kerb weight", "457 kg"))
    s.append(kv("Ground clearance (unladen)", "185 mm"))

    # Colours
    s.append(Paragraph("Colour Options (TVS King EV MAX)", H2))
    s.append(Paragraph("The TVS King EV MAX is available in two colours: Pristine White and Neptune Blue.", BODY))

    # Connectivity
    s.append(Paragraph("Connectivity - TVS SmartXonnect (TVS King EV MAX)", H2))
    s.append(Paragraph(
        "The TVS King EV MAX is India's first connected three-wheeler. It features TVS SmartXonnect "
        "with Bluetooth, allowing it to connect to the Apnaa TVS mobile app. The Apnaa TVS app can be "
        "downloaded from the Google Play Store and the Apple App Store.", BODY))

    # Warranty & support
    s.append(Paragraph("Warranty, Roadside Assistance and Support (TVS King EV MAX)", H2))
    s.append(kv("Warranty", "Comprehensive 6-year / 150,000 km warranty"))
    s.append(kv("Roadside assistance", "24x7 Roadside Assistance, free for 3 years"))
    s.append(kv("Roadside assistance toll-free number", "1800 258 7444"))
    s.append(kv("Manufacturer", "TVS Motor Company Limited, P.B. No. 4, Harita, Hosur - 635109, Tamil Nadu, India"))
    s.append(kv("Website", "www.tvsmotor.com (three-wheelers: www.tvsmotor.com/three-wheelers)"))

    # Pricing note (no fabricated number)
    s.append(Paragraph("Pricing (TVS King EV MAX)", H2))
    s.append(Paragraph(
        "The on-road price of the TVS King EV MAX varies by city, state subsidies and dealer. "
        "For an exact current price and offers, please contact your nearest authorised TVS dealer "
        "or visit www.tvsmotor.com/three-wheelers. (Price figures are not specified in this document.)",
        BODY))

    # FAQ
    s.append(Paragraph("Frequently Asked Questions (TVS King EV MAX)", H2))
    faqs = [
        ("What is the range of the TVS King EV MAX?",
         "The TVS King EV MAX has a certified range of 179 km on a full charge."),
        ("What is the top speed of the TVS King EV MAX?",
         "The maximum speed is 60 km/h. In Eco mode the top speed is 40 km/h, in City mode 50 km/h, and in Power mode 60 km/h."),
        ("How long does the TVS King EV MAX take to charge?",
         "It charges from 0 to 80 percent in 2 hours 15 minutes, and from 0 to 100 percent in 3 hours 30 minutes, using the 3 kW off-board charger."),
        ("What battery does the TVS King EV MAX use?",
         "It uses a 51.2 V Lithium-Ion LFP battery with a capacity of 9.2 kWh."),
        ("What is the motor power and torque of the TVS King EV MAX?",
         "It uses a Permanent Magnet Synchronous Motor (PMSM) with maximum power of 11 kW and maximum torque of 40 Nm."),
        ("What are the drive modes of the TVS King EV MAX?",
         "There are three drive modes: Eco, City and Power."),
        ("What is the warranty on the TVS King EV MAX?",
         "It comes with a comprehensive 6-year / 150,000 km warranty, plus free 24x7 roadside assistance for 3 years."),
        ("What colours is the TVS King EV MAX available in?",
         "It is available in Pristine White and Neptune Blue."),
        ("Can the TVS King EV MAX go through water?",
         "Yes. The TVS King EV MAX has a water-wading capability of 500 mm."),
        ("How much can the TVS King EV MAX climb (gradeability)?",
         "The TVS King EV MAX has a gradeability of 31 percent."),
        ("What is the kerb weight and ground clearance of the TVS King EV MAX?",
         "The kerb weight is 457 kg and the unladen ground clearance is 185 mm."),
        ("Does the TVS King EV MAX have connectivity features?",
         "Yes. It is India's first connected three-wheeler, with TVS SmartXonnect Bluetooth and the Apnaa TVS app."),
        ("What is the price of the TVS King EV MAX?",
         "The on-road price varies by city and dealer. Please contact your nearest authorised TVS dealer or visit www.tvsmotor.com/three-wheelers for the current price."),
    ]
    for question, answer in faqs:
        s.extend(faq(question, answer))

    doc.build(s)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
