"""Generate a RAG-optimised knowledge PDF for the FULL TVS three-wheeler lineup.

Data sourced from www.tvsmotor.com/three-wheelers (official product pages).
Design: real text, every section restates the model name (self-contained chunks),
specs as "Label: Value" lines, plus a cross-model FAQ.

Usage:  python build_tvs_3w_kb.py   ->  writes tvs_three_wheelers_kb.pdf
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem, PageBreak

OUT = "tvs_three_wheelers_kb.pdf"

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=18, spaceAfter=6, spaceBefore=10)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=14, spaceAfter=4, spaceBefore=12)
H3 = ParagraphStyle("H3", parent=styles["Heading3"], fontSize=11.5, spaceAfter=3, spaceBefore=8)
BODY = ParagraphStyle("BODY", parent=styles["BodyText"], fontSize=10, leading=14, alignment=TA_LEFT, spaceAfter=3)
Q = ParagraphStyle("Q", parent=BODY, fontName="Helvetica-Bold", spaceBefore=7, spaceAfter=2)


def P(t):
    return Paragraph(t, BODY)


def kv(label, value):
    return Paragraph(f"<b>{label}:</b> {value}", BODY)


def bullets(items):
    return ListFlowable([ListItem(P(i)) for i in items], bulletType="bullet", leftIndent=12)


# ----------------------------------------------------------------------------
# Model data (from official TVS product pages)
# ----------------------------------------------------------------------------
MODELS = [
    {
        "name": "TVS King EV MAX",
        "tag": "Electric passenger three-wheeler (e-auto / electric rickshaw)",
        "overview": (
            "The TVS King EV MAX is an electric passenger three-wheeler. It offers a certified range "
            "of 179 km, a top speed of 60 km/h, fast charging (0-80% in 2 hours 15 minutes), and is "
            "India's first Bluetooth-connected three-wheeler with TVS SmartXonnect. Tagline: "
            "\"Mushkil Raaste Ab Bane Aasaan\"."
        ),
        "specs": [
            ("Vehicle type", "Electric passenger three-wheeler"),
            ("Motor type", "Permanent Magnet Synchronous Motor (PMSM)"),
            ("Maximum power", "11 kW"),
            ("Maximum torque", "40 Nm"),
            ("Battery", "51.2 V Lithium-Ion LFP, 9.2 kWh"),
            ("Certified range", "179 km on a single charge"),
            ("Top speed", "60 km/h (Eco 40, City 50, Power 60 km/h)"),
            ("Acceleration", "0-30 km/h in 3.7 s; 20-40 km/h in 4.3 s"),
            ("Gradeability", "31%"),
            ("Charger", "Off-board charger, 3 kW, with theft-proof protection"),
            ("Charging time", "0-80% in 2 hours 15 minutes; 0-100% in 3 hours 30 minutes"),
            ("Regenerative braking", "Yes"),
            ("Transmission", "1 forward and 1 reverse speed"),
            ("Drive modes", "Eco, City, Power"),
            ("Front suspension", "Leading arm with coil spring"),
            ("Rear suspension", "Hydraulic damper trailing arm with coil spring"),
            ("Brakes", "Drum brakes, individually controlled per wheel, foot operated"),
            ("Rim size", "3.5B x 12"),
            ("Tyres", "120/80 R12 6 PR radial tubeless"),
            ("Overall length", "2,780 mm"),
            ("Overall height", "1,800 mm"),
            ("Wheelbase", "2,000 mm"),
            ("Wheel track", "1,160 mm"),
            ("Kerb weight", "457 kg"),
            ("Ground clearance (unladen)", "185 mm"),
            ("Water-wading capacity", "500 mm"),
            ("Warranty", "6 years / 1,50,000 km, plus 3 years free maintenance and roadside assistance"),
            ("Colours", "Pristine White, Neptune Blue"),
        ],
        "features": [
            "India's first connected three-wheeler with TVS SmartXonnect and the Apnaa TVS app (26 connected features).",
            "Hill Hold Assist prevents rollback on inclines.",
            "LED headlight and tail lamp; large ORVMs to reduce blind spots.",
            "Twin lockable glove boxes, foldable tumble seat, USB charging port, openable rear boot.",
        ],
    },
    {
        "name": "TVS King Deluxe",
        "tag": "Petrol / CNG / LPG passenger three-wheeler (200cc)",
        "overview": (
            "The TVS King Deluxe is a 200cc passenger three-wheeler (auto rickshaw) available in Petrol, "
            "CNG and LPG. Known as the \"Mileage Maharaja\", it delivers up to 50 km/l on CNG and features "
            "a 4-forward-gear transmission with reverse, a car-like dashboard and twin headlamps."
        ),
        "specs": [
            ("Vehicle type", "Petrol / CNG / LPG passenger three-wheeler"),
            ("Engine", "4-stroke, single-cylinder, air-cooled SI engine, 199.26 cc"),
            ("Max power", "Petrol 7.8 kW; CNG 6.7 kW; LPG 7.1 kW (all @ 5500 rpm)"),
            ("Max torque", "Petrol 15.5 Nm @ 3750 rpm; CNG 13.0 Nm @ 3000 rpm; LPG 14.5 Nm @ 3500 rpm"),
            ("Mileage", "CNG 50 +/- 5 km/l; Petrol 38 +/- 3 km/l; LPG 25 +/- 3 km/l"),
            ("Top speed", "Petrol 63; CNG 60; LPG 61 km/h (+/- 2)"),
            ("Transmission", "4 forward and 1 reverse, constant mesh"),
            ("Fuel tank", "Petrol 8.5 L; CNG 28 L water-equiv + 3 L petrol; LPG 20.6 L water-equiv + 3 L petrol"),
            ("Chassis", "Semi monocoque"),
            ("Suspension (front & rear)", "Swing arm with hydraulic damper and coil spring"),
            ("Gradeability", "10 degrees"),
            ("Brakes", "Drum, hydraulic (front and rear)"),
            ("Rim / tyre", "3.00 D x 8 inch; 4.00-8, 76F/76E 6 PR"),
            ("Dimensions (L x W x H)", "2,647 x 1,329 x 1,740 mm"),
            ("Wheelbase / track", "1,990 mm / 1,150 mm"),
            ("Ground clearance", "169 mm"),
            ("Kerb weight", "Petrol 356 kg; LPG 386 kg; CNG 408 kg"),
            ("Electricals", "12 V 32 Ah battery; twin 35/35 W DC headlamps; integrated starter generator + hand start"),
            ("Warranty", "18 months / 72,000 km"),
            ("Colours", "Glossy Black, Eco Space Green, Neptune Blue, Golden Yellow"),
        ],
        "features": [
            "Advanced fuel injection; strong BHS body and chassis; chassis-mounted rear bumper.",
            "Dual utility storage with charging socket; dual-tone seats with wider backrest.",
        ],
    },
    {
        "name": "TVS King Duramax Plus",
        "tag": "Petrol / CNG passenger three-wheeler (225cc, liquid-cooled)",
        "overview": (
            "The TVS King Duramax Plus is a 225cc liquid-cooled passenger three-wheeler available in "
            "Petrol and CNG (bi-fuel). It offers an all-gear start, LED lamps, tubeless tyres and a long "
            "10,000 km service interval for low maintenance."
        ),
        "specs": [
            ("Vehicle type", "Petrol / CNG passenger three-wheeler"),
            ("Engine", "4-stroke, single-cylinder, liquid-cooled SI engine, 225.8 cc"),
            ("Max power", "Petrol 7.9 kW @ 4750 rpm; CNG 6.7 kW @ 5000 rpm"),
            ("Max torque", "Petrol 18.5 Nm @ 3000 rpm; CNG 15.5 Nm @ 3000 rpm"),
            ("Top speed", "Petrol 65 km/h; CNG 60 +/- 2 km/h"),
            ("Transmission", "4 forward and 1 reverse, constant mesh"),
            ("Fuel tank", "Petrol 8.5 L; CNG 30 L water-equiv + 3 L petrol"),
            ("Brakes", "Hydraulic ribbed drum (front and rear)"),
            ("Suspension (front & rear)", "Trailing arm with coil spring"),
            ("Tyres", "4.00-8 inch 6 PR"),
            ("Dimensions (L x W x H)", "2,647 x 1,329 x 1,740 mm"),
            ("Wheelbase / track", "1,990 mm / 1,150 mm"),
            ("Ground clearance", "169 mm"),
            ("Kerb weight", "Petrol 366 kg; CNG 411 kg"),
            ("Gradeability", "12 degrees"),
            ("Service interval", "10,000 km"),
            ("Electricals", "12 V 32 Ah; 35/35 W LED headlamp; LED reverse/tail/stop lamps; ISG + hand start"),
            ("Colours", "Glossy Black, Eco Green, Golden Yellow"),
        ],
        "features": [
            "Smart tell-tale cluster; twin lockable dashboard storage; driver foot rest.",
            "Integrated starter generator with single start/stop switch; semi-monocoque chassis.",
        ],
    },
    {
        "name": "TVS King Kargo HD EV",
        "tag": "Electric cargo three-wheeler (heavy duty)",
        "overview": (
            "The TVS King Kargo HD EV is a heavy-duty electric cargo three-wheeler and India's first "
            "Bluetooth-connected cargo three-wheeler. It offers a 156 km certified range, a 6.6 ft deck, "
            "first-in-segment LED lights and a power gear, with a 6-year / 1.5 lakh km warranty."
        ),
        "specs": [
            ("Vehicle type", "Electric cargo (goods) three-wheeler"),
            ("Maximum power", "11.2 kW"),
            ("Maximum torque", "40 Nm"),
            ("Battery", "Lithium-Ion LFP, 8.9 kWh"),
            ("Certified range", "156 km"),
            ("Top speed", "60 km/h"),
            ("Acceleration", "0-30 km/h in 5.9 s"),
            ("Gradeability", "28.7%"),
            ("Charging", "0-100% in 3 hours 10 minutes; off-board 3 kW charger"),
            ("Regenerative braking", "Yes"),
            ("Transmission", "Twin speed; drive modes Eco, City, Power"),
            ("Front suspension", "Single fork leading link coil spring"),
            ("Rear suspension", "Leaf spring with hydraulic damper"),
            ("Brakes", "200 mm drum brakes"),
            ("Tyres", "130/80 R12 90F tubeless (12 inch)"),
            ("Dimensions (L x W x H)", "3,565 x 1,530 x 1,860 mm (unladen height)"),
            ("Wheelbase", "2,310 mm"),
            ("Ground clearance (unladen)", "235 mm"),
            ("Water-wading capacity", "500 mm"),
            ("Kerb weight", "541 kg"),
            ("Gross vehicle weight (GVW)", "998 kg"),
            ("Deck length", "6.6 feet; ~192 cubic feet container volume"),
            ("Variants", "Fixed Side Deck (FSD), Platform (PF), Cab Chassis Container (CBC)"),
            ("Warranty", "6 years / 1,50,000 km"),
            ("Colours", "White, Blue"),
        ],
        "features": [
            "India's first Bluetooth-connected cargo three-wheeler; Apnaa TVS app with tracking, SOC, "
            "distance-to-empty, fleet management and cost-per-km analysis.",
            "First-in-segment LED head/tail lights; full rolling windows; roof trim cuts cabin temp by up to 6 C.",
            "Twin-axis ORVMs, zero-position wipers, USB charging port, lockable glove box, tripod drive shaft.",
        ],
    },
    {
        "name": "TVS King Kargo",
        "tag": "CNG cargo three-wheeler (225cc, bi-fuel)",
        "overview": (
            "The TVS King Kargo is a 225cc liquid-cooled CNG cargo three-wheeler with a bi-fuel "
            "(CNG/Petrol) option. It offers around 43 km/l on CNG, a top speed of 60 km/h, a three-side "
            "openable load deck and large lockable storage."
        ),
        "specs": [
            ("Vehicle type", "CNG cargo (goods) three-wheeler"),
            ("Engine", "4-stroke, single-cylinder, liquid-cooled EFi SI engine, 225.8 cc"),
            ("Max power", "6.91 kW @ 5000 rpm (Fi); 6.7 kW @ 5500 rpm (PF)"),
            ("Max torque", "15.5 Nm @ 3000 rpm"),
            ("Top speed (unladen)", "60 +/- 2 km/h"),
            ("Mileage", "43 +/- 5 km/l (CNG)"),
            ("Fuel", "CNG/Petrol bi-fuel; CNG 28 or 33 L water-equiv + 3 L petrol"),
            ("Transmission", "4 forward and 1 reverse, constant mesh"),
            ("Brakes", "Drum, hydraulic (front and rear)"),
            ("Suspension", "Swing arm with hydraulic damper and coil spring"),
            ("Rim / tyre", "3.00 D x 8 inch; 4.00-8, 76F/76E 6 PR"),
            ("Dimensions (L x W x H)", "ZK Fi: 3,010 x 1,350 x 1,720 mm; PF: 2,647 x 1,329 x 1,740 mm"),
            ("Wheelbase / track", "1,990 mm / 1,150 mm"),
            ("Ground clearance", "169 mm"),
            ("Cargo box (L x W x H)", "1,500 x 1,300 x 280 mm"),
            ("Gradeability", "10 degrees"),
            ("Kerb weight", "464 kg (ZK Fi); 438 kg (PF)"),
            ("Gross vehicle weight (GVW)", "864 kg"),
            ("Electricals", "12 V 32 Ah; integrated starter generator + hand start"),
            ("Warranty", "36 months / 1,00,000 km; service every 105 days"),
            ("Colours", "Neptune Blue, Eco Green, Glossy Red, Golden Yellow"),
        ],
        "features": [
            "Three-side openable load deck; driver cabin heat shield; EFi spark ignition with ECU.",
        ],
    },
    {
        "name": "TVS King Kargo HD CNG",
        "tag": "CNG cargo three-wheeler (heavy duty, 300cc)",
        "overview": (
            "The TVS King Kargo HD CNG is a heavy-duty 301cc CNG cargo three-wheeler with an "
            "industry-first power gear for superior gradeability and mileage. It offers a 6.6 ft deck, "
            "a top speed of 62 km/h and a fully rolling window cabin."
        ),
        "specs": [
            ("Vehicle type", "CNG cargo (goods) three-wheeler, heavy duty"),
            ("Engine", "4-stroke, spark ignition, liquid-cooled, 301.1 cc"),
            ("Fuel", "CNG and Petrol (limp-home); CNG 40 L + 3 L petrol"),
            ("Max power", "9.1 kW @ 4750 rpm"),
            ("Max torque", "22.4 Nm @ 3000 rpm"),
            ("Top speed", "62 km/h"),
            ("Acceleration", "0-30 km/h in 8.5 s"),
            ("Fuel economy", "36 km/kg"),
            ("Gradeability", "24.93%"),
            ("Clutch / gears", "Assisted slipper clutch; (4 forward + 1 reverse) x 2; tripod drive shaft"),
            ("Front suspension", "Single fork leading link coil spring"),
            ("Rear suspension", "Leaf spring with hydraulic damper (parabolic type)"),
            ("Brakes", "Hydraulic drum brake, 200 mm diameter"),
            ("Tyres", "130/80 R12 90F radial tubeless (12 inch)"),
            ("Dimensions (L x W x H)", "3,565 x 1,530 x 1,860 mm (unladen height)"),
            ("Wheelbase", "2,310 mm"),
            ("Ground clearance (kerb)", "235 mm"),
            ("Turning radius", "3,420 mm"),
            ("Deck size", "6 ft 7.2 in x 4 ft 10.8 in x 1 ft 1.7 in; ~192 cubic feet"),
            ("Loading height (lowest)", "703 mm"),
            ("Gross vehicle weight (GVW)", "998 kg"),
            ("Variants", "Fixed Side Deck (FSD), Platform (PF), Cab Chassis Container (CBC)"),
            ("Warranty", "3 years / 1,50,000 km"),
            ("Colours", "Golden Yellow, Eco Green"),
        ],
        "features": [
            "Industry-first power gear; dual-rate suspension for smooth rides.",
            "Fully rolling windows, roof trim, USB charging, lockable glove box, twin-axis ORVMs, zero-position wiper.",
        ],
    },
]

FAQS = [
    ("How many three-wheeler models does TVS offer?",
     "TVS offers six three-wheelers: passenger models King EV MAX (electric), King Deluxe (petrol/CNG/LPG) "
     "and King Duramax Plus (petrol/CNG); and cargo models King Kargo HD EV (electric), King Kargo (CNG) "
     "and King Kargo HD CNG (heavy-duty CNG)."),
    ("Which TVS three-wheelers are electric?",
     "The electric models are the TVS King EV MAX (passenger, 179 km range) and the TVS King Kargo HD EV "
     "(cargo, 156 km range)."),
    ("Which TVS three-wheelers are for cargo / goods?",
     "The cargo models are the TVS King Kargo HD EV (electric), TVS King Kargo (CNG) and TVS King Kargo HD CNG "
     "(heavy-duty CNG)."),
    ("Which TVS three-wheelers are for passengers?",
     "The passenger models are the TVS King EV MAX (electric), TVS King Deluxe (petrol/CNG/LPG) and "
     "TVS King Duramax Plus (petrol/CNG)."),
    ("Which TVS three-wheeler has the best mileage?",
     "Among fuel models, the TVS King Deluxe gives the highest CNG mileage at about 50 km/l. The King Duramax "
     "Plus and King Kargo are 225cc CNG options, and the King Kargo HD CNG returns about 36 km/kg."),
    ("Which TVS electric three-wheeler has the longest range?",
     "The TVS King EV MAX has the longest electric range at 179 km; the King Kargo HD EV offers 156 km."),
    ("What is the warranty on TVS three-wheelers?",
     "King EV MAX: 6 years / 1.5 lakh km (plus 3 years free maintenance). King Kargo HD EV: 6 years / 1.5 lakh km. "
     "King Kargo HD CNG: 3 years / 1.5 lakh km. King Kargo (CNG): 3 years / 1 lakh km. King Deluxe: 18 months / 72,000 km."),
    ("Which TVS three-wheelers have Bluetooth / connectivity?",
     "The TVS King EV MAX is India's first connected (Bluetooth) passenger three-wheeler, and the King Kargo HD EV "
     "is India's first Bluetooth-connected cargo three-wheeler. Both work with the Apnaa TVS app."),
    ("What is the price of TVS three-wheelers?",
     "On-road prices vary by city, state subsidies and dealer and are not listed here. Please contact your nearest "
     "authorised TVS dealer or visit www.tvsmotor.com/three-wheelers for current pricing and offers."),
]


def build():
    doc = SimpleDocTemplate(
        OUT, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title="TVS Three-Wheelers - Product Knowledge Base",
    )
    s = []
    s.append(Paragraph("TVS Three-Wheelers - Product Knowledge Base", H1))
    s.append(P(
        "This document contains official specifications, features, warranty and support information for the "
        "complete TVS three-wheeler range from TVS Motor Company. It covers six models across passenger and "
        "cargo categories and across electric, petrol, CNG and LPG. Data sourced from "
        "www.tvsmotor.com/three-wheelers."))

    s.append(Paragraph("Lineup at a glance", H2))
    s.append(bullets([
        "TVS King EV MAX - electric passenger three-wheeler, 179 km range.",
        "TVS King Deluxe - 200cc petrol/CNG/LPG passenger three-wheeler, up to 50 km/l (CNG).",
        "TVS King Duramax Plus - 225cc liquid-cooled petrol/CNG passenger three-wheeler.",
        "TVS King Kargo HD EV - electric heavy-duty cargo three-wheeler, 156 km range.",
        "TVS King Kargo - 225cc CNG cargo three-wheeler (bi-fuel).",
        "TVS King Kargo HD CNG - 301cc heavy-duty CNG cargo three-wheeler.",
    ]))

    for m in MODELS:
        s.append(PageBreak())
        s.append(Paragraph(m["name"], H2))
        s.append(P(f"<i>{m['tag']}</i>"))
        s.append(Paragraph("Overview", H3))
        s.append(P(m["overview"]))
        s.append(Paragraph(f"Specifications - {m['name']}", H3))
        for label, value in m["specs"]:
            s.append(kv(label, value))
        if m.get("features"):
            s.append(Paragraph(f"Key features - {m['name']}", H3))
            s.append(bullets(m["features"]))

    s.append(PageBreak())
    s.append(Paragraph("Frequently Asked Questions - TVS Three-Wheelers", H2))
    for q, a in FAQS:
        s.append(Paragraph(f"Q: {q}", Q))
        s.append(P(f"A: {a}"))

    s.append(Paragraph("Contact and Support", H2))
    s.append(kv("Manufacturer", "TVS Motor Company Limited, P.B. No. 4, Harita, Hosur - 635109, Tamil Nadu, India"))
    s.append(kv("Website", "www.tvsmotor.com/three-wheelers"))
    s.append(kv("Roadside assistance (toll-free)", "1800 258 7444"))
    s.append(kv("App", "Apnaa TVS (Google Play and Apple App Store)"))

    doc.build(s)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
