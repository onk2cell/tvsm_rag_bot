"""Generate a RAG-optimised PDF: loan document requirements for TVS passenger
three-wheelers (auto rickshaws).

Source: TVS Credit three-wheeler loan page (www.tvscredit.com/loans/three-wheeler-loans).
Figures (processing fee, tenure, etc.) are indicative and change; always confirm with
the financier. Design: real text, self-contained sections, Label: Value lines, FAQ.

Usage:  python build_loan_docs_kb.py   ->  writes tvs_3w_loan_documents_kb.pdf
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, ListFlowable, ListItem, PageBreak

OUT = "tvs_3w_loan_documents_kb.pdf"

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=18, spaceAfter=6, spaceBefore=10)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13.5, spaceAfter=4, spaceBefore=12)
H3 = ParagraphStyle("H3", parent=styles["Heading3"], fontSize=11.5, spaceAfter=3, spaceBefore=8)
BODY = ParagraphStyle("BODY", parent=styles["BodyText"], fontSize=10.5, leading=15, alignment=TA_LEFT, spaceAfter=4)
Q = ParagraphStyle("Q", parent=BODY, fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=2)


def P(t):
    return Paragraph(t, BODY)


def kv(label, value):
    return Paragraph(f"<b>{label}:</b> {value}", BODY)


def bullets(items):
    return ListFlowable([ListItem(P(i)) for i in items], bulletType="bullet", leftIndent=12)


def build():
    doc = SimpleDocTemplate(
        OUT, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title="TVS Passenger Three-Wheeler Loan - Documents Required",
    )
    s = []

    s.append(Paragraph("TVS Passenger Three-Wheeler Loan - Documents Required", H1))
    s.append(P(
        "This document explains the documents required and eligibility to finance (take a loan for) a TVS "
        "passenger three-wheeler / auto rickshaw, such as the TVS King EV MAX, TVS King Deluxe or "
        "TVS King Duramax Plus. Information is based on TVS Credit's three-wheeler loan process. Exact "
        "requirements, fees and rates vary by applicant profile, location and lender, and may change over "
        "time - always confirm the current list with TVS Credit or your dealer before applying."))

    # Quick summary
    s.append(Paragraph("Quick summary", H2))
    s.append(bullets([
        "Core documents for everyone: ID & signature proof, age proof, address proof, income proof (where applicable), and a bank statement.",
        "A 'No income document' scheme is available - in some cases you can get a three-wheeler loan without income proof.",
        "Eligibility: Indian national, age 18 to 65 years, active employment/business for at least 1 year.",
        "Approval is usually given within one working day after all documents are submitted.",
        "Maximum loan tenure is up to 4 years (48 months).",
    ]))

    # Documents by applicant type
    s.append(Paragraph("Documents required - by applicant type", H2))

    s.append(Paragraph("A) Salaried or Self-Employed Individuals", H3))
    s.append(bullets([
        "ID & Signature Proof (any one): Voter's ID, Driving Licence, Aadhaar Card, PAN Card or Passport.",
        "Age Proof: PAN Card.",
        "Address Proof (any one): Passport or Electricity Bill.",
        "Income Proof: Salary Slip, Form 16, or ITR with Computation of Income.",
        "Bank Statement.",
    ]))

    s.append(Paragraph("B) Proprietorship or Partnership Firms", H3))
    s.append(bullets([
        "ID & Signature Proof, Age Proof, and Address Proof: same as individuals (above).",
        "Income Proof: same as individuals (Salary Slip / Form 16 / ITR with Computation of Income).",
        "Vehicle Documents: photocopy of the Vehicle RC Book and Insurance Certificate.",
        "Bank Statement or Passbook.",
        "Partnership Deed along with a declaration (for partnership firms).",
    ]))

    s.append(Paragraph("C) Private or Public Limited Companies", H3))
    s.append(bullets([
        "ID & Signature Proof, Age Proof, and Address Proof: same as individuals (above).",
        "Income Proof: same as individuals.",
        "Bank Statement.",
        "MOA / AOA (Memorandum and Articles of Association) along with a Board Resolution.",
    ]))

    # Eligibility
    s.append(Paragraph("Eligibility criteria", H2))
    s.append(kv("Nationality", "Indian"))
    s.append(kv("Age", "18 years to 65 years"))
    s.append(kv("Employment status", "Active (salaried, self-employed or business)"))
    s.append(kv("Employment / business stability", "Minimum 1 year"))

    # Loan features
    s.append(Paragraph("Loan features (indicative)", H2))
    s.append(kv("Approval timeline", "Usually within one working day of submitting all documents"))
    s.append(kv("Maximum tenure", "Up to 4 years (48 months)"))
    s.append(kv("No-income-document scheme", "Available - finance possible without income proof in eligible cases"))
    s.append(kv("Interest rate", "Depends on customer location, profile and tenure"))
    s.append(kv("Processing fee", "Up to 5.9% (inclusive of GST)"))
    s.append(kv("Foreclosure charges", "3% to 5%, depending on the remaining tenure"))

    # Application process
    s.append(Paragraph("Application process", H2))
    s.append(bullets([
        "Step 1: Select the TVS three-wheeler you want to buy.",
        "Step 2: Submit / upload the required documents to obtain approval.",
        "Step 3: Receive the loan sanction and disbursement.",
    ]))

    # FAQ
    s.append(PageBreak())
    s.append(Paragraph("Frequently Asked Questions", H2))
    faqs = [
        ("What documents are required for a TVS three-wheeler loan?",
         "For an individual you need: ID & signature proof (Voter's ID / Driving Licence / Aadhaar / PAN / Passport), "
         "age proof (PAN Card), address proof (Passport or Electricity Bill), income proof (Salary Slip / Form 16 / "
         "ITR with Computation of Income), and a bank statement."),
        ("Can I get a three-wheeler loan without income proof?",
         "Yes. TVS Credit offers a 'No income document' scheme, so in eligible cases you can get a three-wheeler "
         "loan without submitting income documents. Confirm eligibility with the lender."),
        ("What is the age limit for a three-wheeler loan?",
         "The applicant must be between 18 and 65 years of age and an Indian national."),
        ("How long does loan approval take?",
         "Approval is usually given within one working day after all required documents are submitted."),
        ("What is the maximum loan tenure for a three-wheeler?",
         "The maximum tenure is up to 4 years (48 months)."),
        ("What documents does a partnership firm need?",
         "In addition to the standard ID, age, address and income proofs and bank statement, a partnership firm "
         "must provide the Vehicle RC Book and Insurance Certificate (photocopy) and the Partnership Deed with a declaration."),
        ("What extra documents does a company need?",
         "A private or public limited company must additionally provide its MOA/AOA (Memorandum and Articles of "
         "Association) along with a Board Resolution, plus a bank statement."),
        ("What are the processing and foreclosure charges?",
         "The processing fee is up to 5.9% (inclusive of GST), and foreclosure charges range from 3% to 5% "
         "depending on the remaining tenure. These are indicative - confirm current figures with the lender."),
        ("Whom do I contact for a TVS three-wheeler loan?",
         "Contact TVS Credit (www.tvscredit.com, helpdesk@tvscredit.com) or your nearest authorised TVS dealer "
         "for the current document list, eligibility and rates."),
    ]
    for question, answer in faqs:
        s.append(Paragraph(f"Q: {question}", Q))
        s.append(P(f"A: {answer}"))

    # Disclaimer
    s.append(Paragraph("Important note", H2))
    s.append(P(
        "The documents, eligibility, fees and rates above are indicative and based on TVS Credit's published "
        "three-wheeler loan information. They can vary by applicant, location and lender and may change. Always "
        "confirm the current requirements with TVS Credit or your authorised TVS dealer before applying."))

    doc.build(s)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
