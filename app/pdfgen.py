"""Synthetic Commercial Lease PDF Generator.

Produces multi-page (5-page) synthetic commercial lease agreements with page numbers,
clause headings, and specific covenant figures for in-window leases.
Includes bilingual English/Arabic generation for designated leases using Arabic reshaper and python-bidi.
"""

import os
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    PageBreak,
    Table,
    TableStyle,
    HRFlowable,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.config import settings

# Register Arabic-capable TrueType font if available
ARABIC_FONT_NAME = "Helvetica"
HAS_ARABIC_FONT = False

for font_path in [
    "C:/Windows/Fonts/tahoma.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]:
    if os.path.exists(font_path):
        try:
            pdfmetrics.registerFont(TTFont("ArabicCapableFont", font_path))
            ARABIC_FONT_NAME = "ArabicCapableFont"
            HAS_ARABIC_FONT = True
            break
        except Exception:
            pass


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and stamp 'Page X of Y' footers and headers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count: int):
        self.saveState()
        width, height = A4

        # Header (Pages 2+)
        if self._pageNumber > 1:
            self.setFont("Helvetica-Bold", 8)
            self.setFillColor(colors.HexColor("#4A5568"))
            self.drawString(54, height - 36, "SYNTHETIC COMMERCIAL LEASE AGREEMENT — OFFICIAL REGISTER COPY")
            self.setFont("Helvetica", 8)
            self.drawRightString(width - 54, height - 36, f"LEAD REF: IN-WINDOW MONITORING")
            self.setStrokeColor(colors.HexColor("#CBD5E0"))
            self.setLineWidth(0.5)
            self.line(54, height - 42, width - 54, height - 42)

        # Footer (All pages)
        self.setStrokeColor(colors.HexColor("#CBD5E0"))
        self.setLineWidth(0.5)
        self.line(54, 48, width - 54, 48)

        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#718096"))
        self.drawString(54, 34, "GENERIC SYNTHETIC DEMISE • FOR AGENT MONITORING ONLY • NO REAL ENTITIES")
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(width - 54, 34, page_str)

        self.restoreState()


def format_arabic_text(text: str) -> str:
    """Reshape and reorder Arabic text for proper RTL display in ReportLab."""
    if not HAS_ARABIC_FONT or not text:
        return text
    try:
        reshaped = arabic_reshaper.reshape(text)
        bidi_text = get_display(reshaped)
        return bidi_text
    except Exception:
        return text


def create_lease_pdf(lease_data: Dict[str, Any], output_path: Path) -> Path:
    """Generate a 5-page synthetic commercial lease PDF document."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    base_styles = getSampleStyleSheet()

    # Base typography styles
    title_style = ParagraphStyle(
        "DocTitle",
        parent=base_styles["Title"],
        fontName=ARABIC_FONT_NAME if HAS_ARABIC_FONT else "Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#1A365D"),
        alignment=0,
    )
    h1_style = ParagraphStyle(
        "Heading1_Custom",
        parent=base_styles["Heading1"],
        fontName=ARABIC_FONT_NAME if HAS_ARABIC_FONT else "Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#2B6CB0"),
        spaceBefore=12,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "Body_Custom",
        parent=base_styles["Normal"],
        fontName=ARABIC_FONT_NAME if HAS_ARABIC_FONT else "Helvetica",
        fontSize=9.5,
        leading=13.5,
        textColor=colors.HexColor("#2D3748"),
    )
    bold_body_style = ParagraphStyle(
        "BoldBody_Custom",
        parent=body_style,
        fontName=ARABIC_FONT_NAME if HAS_ARABIC_FONT else "Helvetica-Bold",
    )
    arabic_style = ParagraphStyle(
        "Arabic_Custom",
        parent=base_styles["Normal"],
        fontName=ARABIC_FONT_NAME,
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor("#4A5568"),
        alignment=2 if HAS_ARABIC_FONT else 0,  # Right-aligned for RTL
    )

    is_bilingual = lease_data.get("bilingual", False)
    story = []

    # ================= PAGE 1 =================
    # Title & Particulars
    story.append(Paragraph("COMMERCIAL LEASE AGREEMENT (SYNTHETIC)", title_style))
    if is_bilingual:
        story.append(Spacer(1, 4))
        story.append(Paragraph(format_arabic_text("عقد إيجار تجاري تركيبي موحد"), arabic_style))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#2B6CB0"), spaceAfter=14))

    meta_table_data = [
        [Paragraph("<b>Lease Reference:</b>", body_style), Paragraph(str(lease_data["lease_id"]), bold_body_style)],
        [Paragraph("<b>Asset Identifier:</b>", body_style), Paragraph(str(lease_data["asset_id"]), body_style)],
        [Paragraph("<b>Asset Name:</b>", body_style), Paragraph(str(lease_data["asset_name"]), body_style)],
        [Paragraph("<b>Holding Entity (Landlord):</b>", body_style), Paragraph(str(lease_data["holding_spv"]), body_style)],
        [Paragraph("<b>Demised Tenant:</b>", body_style), Paragraph(str(lease_data["tenant"]), bold_body_style)],
        [Paragraph("<b>Upcoming Monitored Event:</b>", body_style), Paragraph(f"<b>{lease_data['event_type']}</b>", bold_body_style)],
        [Paragraph("<b>Event Target Date:</b>", body_style), Paragraph(str(lease_data["event_date"]), bold_body_style)],
    ]
    meta_table = Table(meta_table_data, colWidths=[160, 320])
    meta_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAFC")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#EDF2F7")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    story.append(meta_table)
    story.append(Spacer(1, 14))

    story.append(Paragraph("1. DEMISED PREMISES AND TERM PARTICULARS", h1_style))
    if is_bilingual:
        story.append(Paragraph(format_arabic_text("البند الأول: العقار المؤجر وتفاصيل المدة الإيجارية"), arabic_style))
        story.append(Spacer(1, 4))

    story.append(
        Paragraph(
            f"1.1 The Landlord hereby demises unto the Tenant all that commercial property known as "
            f"<b>{lease_data['premises']}</b> (the 'Demised Premises'). The boundary of the Demised Premises is delineated "
            f"in Schedule 1 of this Agreement and comprises an approximate net internal area of {lease_data['sqft']} sq ft.",
            body_style,
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            f"1.2 The Term of this Lease shall be for a contractual period of <b>{lease_data['term_years']} years</b>, "
            f"commencing on the Commencement Date of <b>{lease_data['commencement_date']}</b> and expiring on the Expiry Date "
            f"of <b>{lease_data['contractual_expiry_date']}</b> (subject to earlier determination under Clause 4).",
            body_style,
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "1.3 The Tenant covenants to use the Demised Premises strictly for permitted commercial, warehousing, "
            "and business office activities conforming to Use Class E / B8 and for no other prohibited trade.",
            body_style,
        )
    )
    story.append(PageBreak())

    # ================= PAGE 2 =================
    # Rent, Payment Terms & Service Charge
    story.append(Paragraph("2. PASSING RENT AND SERVICE CHARGE OBLIGATIONS", h1_style))
    if is_bilingual:
        story.append(Paragraph(format_arabic_text("البند الثاني: بدل الإيجار الحالي والتزامات رسوم الخدمات"), arabic_style))
        story.append(Spacer(1, 4))

    story.append(
        Paragraph(
            f"2.1 The Tenant shall yield and pay unto the Landlord a clear annual passing rent of "
            f"<b>{lease_data['currency']} {lease_data['passing_rent']:,.2f}</b> (exclusive of Value Added Tax and outgoings).",
            body_style,
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            f"2.2 Passing rent shall be payable without deduction or set-off by equal quarterly payments in advance on the usual "
            f"quarter days: 25 March, 24 June, 29 September, and 25 December in each year of the Term. All payments shall be made "
            f"via cleared bank automated funds transfer to the Landlord's designated holding account.",
            body_style,
        )
    )
    story.append(Spacer(1, 10))

    story.append(Paragraph("2.3 Service Charge Cap and Outgoings Covenant", bold_body_style))
    story.append(
        Paragraph(
            f"The Tenant shall pay a proportionate service charge contribution in respect of common estate maintenance, security, "
            f"and external landscaping. PROVIDED ALWAYS that the Tenant's annual liability for service charge expenditure "
            f"shall be subject to an express <b>service charge cap of {lease_data['currency']} {lease_data['service_charge_cap']:,.2f} per annum</b>, "
            f"subject to cumulative adjustment restricted to the Consumer Price Index (CPI) over the baseline term.",
            body_style,
        )
    )
    if is_bilingual:
        story.append(Spacer(1, 6))
        story.append(
            Paragraph(
                format_arabic_text(
                    f"يلتزم المستأجر بسداد بدل إيجار سنوي قدره {lease_data['currency']} {lease_data['passing_rent']:,.2f}، "
                    f"وتخضع رسوم الخدمات لسقف سنوي محدد لا يتجاوز {lease_data['currency']} {lease_data['service_charge_cap']:,.2f} سنوياً."
                ),
                arabic_style,
            )
        )
    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "2.4 Any late payment of passing rent or properly demanded service charge shall attract interest at the default "
            "rate of 4% per annum above the base lending rate of Barclays Bank PLC, calculated on a day-to-day basis.",
            body_style,
        )
    )
    story.append(PageBreak())

    # ================= PAGE 3 =================
    # Rent Review Mechanism
    story.append(Paragraph("3. RENT REVIEW MECHANISM AND PROCEDURES", h1_style))
    if is_bilingual:
        story.append(Paragraph(format_arabic_text("البند الثالث: آلية وإجراءات مراجعة الإيجار"), arabic_style))
        story.append(Spacer(1, 4))

    story.append(
        Paragraph(
            f"3.1 <b>Review Date:</b> The passing rent shall be reviewed on <b>{lease_data['rent_review_date']}</b> "
            f"and on every subsequent anniversary specified in the Fifth Schedule hereto.",
            body_style,
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            f"3.2 <b>Review Mechanism:</b> {lease_data['rent_review_mechanism']}",
            body_style,
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "3.3 <b>Assumptions and Disregards:</b> The open market rent shall be determined upon the hypothetical assumptions that "
            "(a) the Demised Premises are fit for immediate commercial occupation and equipped with all required landlord installations; "
            "(b) the Tenant has observed all repairing and decorating covenants; and (c) any goodwill attached to the Tenant's "
            "business or tenant-financed improvements carried out with consent shall be disregarded entirely.",
            body_style,
        )
    )
    if is_bilingual:
        story.append(Spacer(1, 6))
        story.append(
            Paragraph(
                format_arabic_text(
                    "تتم مراجعة الإيجار على أساس القيمة السوقية المفتوحة التصاعدية دون نقصان، وتحدد وفقاً لتقديرات المساح المستقل المعتمد."
                ),
                arabic_style,
            )
        )
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "3.4 In the event that the parties fail to agree upon the revised passing rent within three months following the Review Date, "
            "either party may request the President of the Royal Institution of Chartered Surveyors (RICS) to appoint an independent "
            "Arbitrator or Expert, whose determination shall be final and binding upon both parties.",
            body_style,
        )
    )
    story.append(PageBreak())

    # ================= PAGE 4 =================
    # Break Clause & Break Conditions
    story.append(Paragraph("4. TENANT BREAK CLAUSE AND PRE-CONDITIONS", h1_style))
    if is_bilingual:
        story.append(Paragraph(format_arabic_text("البند الرابع: شرط خيار الإنهاء المبكر والشروط المسبقة"), arabic_style))
        story.append(Spacer(1, 4))

    story.append(
        Paragraph(
            f"4.1 <b>Break Option:</b> {lease_data['break_clause_summary']}",
            body_style,
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "4.2 <b>Mandatory Conditions Precedent:</b> The exercise and validity of any Break Option under this Clause is "
            "strictly conditional upon full compliance with the following cumulative conditions on or before the Break Date:",
            body_style,
        )
    )
    story.append(Spacer(1, 4))

    conditions_table_data = [
        [
            Paragraph("<b>(a) Vacant Possession:</b>", bold_body_style),
            Paragraph(
                "The Tenant must yield up and deliver full vacant possession of the whole Demised Premises, unencumbered by "
                "any occupational sub-leases, licenses, trespassers, or unapproved third-party occupiers.",
                body_style,
            ),
        ],
        [
            Paragraph("<b>(b) Arrears Discharge:</b>", bold_body_style),
            Paragraph(
                f"The Tenant must have paid and cleared all passing rent ({lease_data['currency']} {lease_data['passing_rent']:,.2f} p.a.), "
                "service charge, insurance rent, and interest due under this Lease up to and including the Break Date without any arrears.",
                body_style,
            ),
        ],
        [
            Paragraph("<b>(c) Break Notice Status:</b>", bold_body_style),
            Paragraph(
                f"Formal break notice status: <b>{lease_data['break_notice_served_status']}</b>. "
                f"Any notice must have been served with at least {lease_data['break_notice_months']} months' prior written notice.",
                body_style,
            ),
        ],
    ]
    cond_table = Table(conditions_table_data, colWidths=[150, 330])
    cond_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAFC")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(cond_table)
    story.append(Spacer(1, 10))

    if is_bilingual:
        story.append(
            Paragraph(
                format_arabic_text(
                    "يشترط لصحة الإنهاء المبكر تسليم العقار شاغراً بالكامل، وسداد كافة المستحقات الإيجارية، وتقديم إشعار خطي مسبق قانوني."
                ),
                arabic_style,
            )
        )
        story.append(Spacer(1, 6))

    story.append(
        Paragraph(
            "4.3 If any of the conditions specified in Clause 4.2 fail to be fully satisfied on the Break Date, "
            "the Break Notice shall be null, void, and of no legal effect, and the Lease shall continue in full force.",
            body_style,
        )
    )
    story.append(PageBreak())

    # ================= PAGE 5 =================
    # Reinstatement Obligations & Dilapidations
    story.append(Paragraph("5. REINSTATEMENT OBLIGATIONS AND DILAPIDATIONS", h1_style))
    if is_bilingual:
        story.append(Paragraph(format_arabic_text("البند الخامس: التزامات الإعادة إلى الحالة الأصلية والتعويضات"), arabic_style))
        story.append(Spacer(1, 4))

    story.append(
        Paragraph(
            f"5.1 <b>Reinstatement Covenants:</b> {lease_data['reinstatement_obligation']}",
            body_style,
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            f"5.2 <b>Dilapidations Estimate:</b> The current surveyor terminal dilapidations liability assessment for the demised "
            f"premises is estimated at <b>{lease_data['currency']} {lease_data['dilapidations_estimate']:,.2f}</b>. "
            f"This estimate encompasses essential mechanical services servicing, ceiling suspension overhaul, floor reinstatement, "
            f"and complete redecoration in accordance with the Schedule of Condition.",
            body_style,
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "5.3 The Landlord reserves the absolute right at lease determination to elect either (a) to require the Tenant to physically "
            "carry out all reinstatement works prior to expiry, or (b) to claim cash settlement of the assessed dilapidations figure.",
            body_style,
        )
    )
    if is_bilingual:
        story.append(Spacer(1, 6))
        story.append(
            Paragraph(
                format_arabic_text(
                    f"التزام بإعادة العقار لحالته الأصلية، وتقدر تكاليف أعمال التعويضات والتجديد بمبلغ {lease_data['currency']} {lease_data['dilapidations_estimate']:,.2f}."
                ),
                arabic_style,
            )
        )
        story.append(Spacer(1, 6))

    story.append(Spacer(1, 16))
    story.append(Paragraph("6. EXECUTION AND ATTESTATION", h1_style))
    story.append(
        Paragraph(
            "IN WITNESS WHEREOF the Landlord and Tenant have executed this Agreement as a Deed on the date first written above.",
            body_style,
        )
    )
    story.append(Spacer(1, 14))

    sig_table_data = [
        [Paragraph(f"<b>EXECUTED AS A DEED by:</b><br/>{lease_data['holding_spv']}<br/>(Authorized Signatory)", body_style),
         Paragraph(f"<b>EXECUTED AS A DEED by:</b><br/>{lease_data['tenant']}<br/>(Director / Authorized Attorney)", body_style)],
        [Paragraph("<br/><br/>___________________________<br/>Authorised Signatory", body_style),
         Paragraph("<br/><br/>___________________________<br/>Authorised Signatory", body_style)]
    ]
    sig_table = Table(sig_table_data, colWidths=[240, 240])
    sig_table.setStyle(
        TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAFC")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ])
    )
    story.append(sig_table)

    # Build the document with two-pass NumberedCanvas
    doc.build(story, canvasmaker=NumberedCanvas)
    return output_path


def generate_all_synthetic_pdfs(in_window_leases: list[Dict[str, Any]], data_dir: Optional[Path] = None) -> list[Path]:
    """Generate PDFs for all in-window leases."""
    target_dir = Path(data_dir) if data_dir else settings.DATA_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    generated_paths = []
    for lease in in_window_leases:
        filename = f"{lease['lease_id']}.pdf"
        pdf_path = target_dir / filename
        create_lease_pdf(lease, pdf_path)
        generated_paths.append(pdf_path)

    return generated_paths
