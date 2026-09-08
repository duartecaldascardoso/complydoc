"""Rebuild the committed test fixtures.

Run with: uv run python tests/fixtures/generate_fixtures.py

The generated PDFs are committed to the repository so the test suite does not
depend on this script or on any system font. Everything here uses the Vera font
bundled inside reportlab, so regeneration produces the same files on any machine.

Every value that looks like personal data in these fixtures is synthetic: the
card number is the standard Visa test PAN, the IBAN is the example from the ISO
13616 specification, the phone number is in Ofcom's reserved fiction range, and
the names are invented.
"""

from __future__ import annotations

import io
from pathlib import Path

import pypdf
import reportlab
from PIL import Image
from reportlab.lib.pagesizes import A4, A5, letter
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

HERE = Path(__file__).parent / "fixtures"
VERA = Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"
FONT = "Vera"


def _register_font() -> None:
    if FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT, str(VERA)))


# --------------------------------------------------------------------------


def native_text(path: Path) -> None:
    """A well-behaved single-column document with an embedded font."""
    _register_font()
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont(FONT, 11)
    y = A4[1] - 40 * mm
    lines = [
        "NORTHWIND SUPPLIES LIMITED",
        "Invoice INV-2026-0417",
        "",
        "Invoice date: 12/03/2026",
        "Payment due: 26/03/2026",
        "",
        "Consultancy services rendered in February 2026, as agreed under the",
        "master services agreement dated 04/01/2026. All amounts are stated",
        "in pounds sterling and exclude value added tax.",
        "",
        "Subtotal          4,250.00",
        "VAT at 20%          850.00",
        "Total due         5,100.00",
        "",
        "Registered in England and Wales. Payment within 14 days please.",
    ]
    for line in lines:
        c.drawString(25 * mm, y, line)
        y -= 6 * mm
    c.showPage()

    c.setFont(FONT, 11)
    y = A4[1] - 40 * mm
    for line in [
        "Page two continues the same single-column layout so that page size",
        "variance and column count both stay clean for this fixture.",
        "",
        "Remittance advice should be emailed on the day of payment.",
    ]:
        c.drawString(25 * mm, y, line)
        y -= 6 * mm
    c.showPage()
    c.save()


def two_column(path: Path) -> None:
    """Two clearly separated text columns with a gutter down the middle."""
    _register_font()
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont(FONT, 9)

    left = [
        "TERMS AND CONDITIONS",
        "",
        "1. The supplier shall provide the",
        "services described in the order",
        "with reasonable skill and care.",
        "",
        "2. Invoices are payable within",
        "fourteen days of the invoice date",
        "unless otherwise agreed between",
        "the parties in writing.",
        "",
        "3. Title in any goods supplied",
        "passes on receipt of payment in",
        "full and not before.",
    ]
    right = [
        "4. Neither party is liable for",
        "indirect or consequential loss",
        "however arising.",
        "",
        "5. This agreement is governed by",
        "the law of England and Wales and",
        "the parties submit to the",
        "exclusive jurisdiction of the",
        "English courts.",
        "",
        "6. Notices must be given in",
        "writing to the registered office",
        "of the receiving party.",
    ]

    y = A4[1] - 30 * mm
    for line in left:
        c.drawString(20 * mm, y, line)
        y -= 5 * mm

    y = A4[1] - 30 * mm
    for line in right:
        c.drawString(115 * mm, y, line)
        y -= 5 * mm

    c.showPage()
    c.save()


def merged_header_table(path: Path) -> None:
    """A table whose header is three stacked rows of merged cells."""
    _register_font()
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont(FONT, 8)

    x0, y0 = 20 * mm, A4[1] - 40 * mm
    col_w = 34 * mm
    row_h = 8 * mm
    n_cols = 4

    def line(xa: float, ya: float, xb: float, yb: float) -> None:
        c.line(xa, ya, xb, yb)

    # Header row 1: one cell spanning all four columns.
    line(x0, y0, x0 + n_cols * col_w, y0)
    line(x0, y0 - row_h, x0 + n_cols * col_w, y0 - row_h)
    line(x0, y0, x0, y0 - row_h)
    line(x0 + n_cols * col_w, y0, x0 + n_cols * col_w, y0 - row_h)
    c.drawString(x0 + 2 * mm, y0 - 5.5 * mm, "FINANCIAL YEAR 2026 - CONSOLIDATED")

    # Header row 2: two cells, each spanning two columns.
    y1 = y0 - row_h
    line(x0, y1 - row_h, x0 + n_cols * col_w, y1 - row_h)
    for x in (x0, x0 + 2 * col_w, x0 + 4 * col_w):
        line(x, y1, x, y1 - row_h)
    c.drawString(x0 + 2 * mm, y1 - 5.5 * mm, "First half")
    c.drawString(x0 + 2 * col_w + 2 * mm, y1 - 5.5 * mm, "Second half")

    # Header row 3: four single-column cells.
    y2 = y1 - row_h
    line(x0, y2 - row_h, x0 + n_cols * col_w, y2 - row_h)
    for i in range(n_cols + 1):
        line(x0 + i * col_w, y2, x0 + i * col_w, y2 - row_h)
    for i, label in enumerate(["Q1", "Q2", "Q3", "Q4"]):
        c.drawString(x0 + i * col_w + 2 * mm, y2 - 5.5 * mm, label)

    # Body rows: plain four-column grid.
    y = y2 - row_h
    for values in [
        ("120,400", "138,900", "141,250", "155,700"),
        ("98,100", "101,300", "119,880", "126,040"),
        ("22,300", "37,600", "21,370", "29,660"),
    ]:
        line(x0, y - row_h, x0 + n_cols * col_w, y - row_h)
        for i in range(n_cols + 1):
            line(x0 + i * col_w, y, x0 + i * col_w, y - row_h)
        for i, value in enumerate(values):
            c.drawString(x0 + i * col_w + 2 * mm, y - 5.5 * mm, value)
        y -= row_h

    c.showPage()
    c.save()


def mixed_page_sizes(path: Path) -> None:
    """Three pages, three different page sizes."""
    _register_font()
    c = canvas.Canvas(str(path), pagesize=A4)
    for size, label in ((A4, "A4 page"), (A5, "A5 page"), (letter, "US Letter page")):
        c.setPageSize(size)
        c.setFont(FONT, 12)
        c.drawString(20 * mm, size[1] - 30 * mm, label)
        c.drawString(20 * mm, size[1] - 40 * mm, "Page size changes between pages here.")
        c.showPage()
    c.save()


def acroform(path: Path) -> None:
    """A fillable form. Named fields are a positive signal for extraction."""
    _register_font()
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont(FONT, 11)
    c.drawString(20 * mm, A4[1] - 30 * mm, "SUPPLIER ONBOARDING FORM")

    form = c.acroForm
    fields = [
        ("supplier_name", "Supplier name"),
        ("contact_email", "Contact email"),
        ("vat_number", "VAT number"),
        ("bank_sort_code", "Sort code"),
        ("bank_account", "Account number"),
    ]
    y = A4[1] - 50 * mm
    for name, label in fields:
        c.setFont(FONT, 9)
        c.drawString(20 * mm, y + 1.5 * mm, label)
        form.textfield(
            name=name,
            x=70 * mm,
            y=y - 1 * mm,
            width=80 * mm,
            height=6 * mm,
            borderWidth=0.5,
            forceBorder=True,
        )
        y -= 12 * mm
    c.showPage()
    c.save()


def sensitive_sample(path: Path) -> None:
    """Synthetic UK identifiers. Every value here is fake or a published example."""
    _register_font()
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont(FONT, 10)
    lines = [
        "EMPLOYEE RECORD - CONFIDENTIAL",
        "",
        "Name: Jane Doe",
        "Employer: Acme Holdings Ltd",
        "Date of birth: 14/03/1985",
        "National Insurance number: AB123456C",
        "Email: jane.doe@example.com",
        "Telephone: 020 7946 0958",
        "Address: 42 Example Road",
        "Postcode: EC1A 1BB",
        "",
        "PAYMENT DETAILS",
        "Sort code: 12-34-56",
        "Account number: 12345678",
        "IBAN: GB82 WEST 1234 5698 7654 32",
        "Card on file: 4111 1111 1111 1111",
        "",
        "TAX",
        "VAT number: GB123456782",
        "UTR: 1234567890",
        "",
        "Approved by John Smith, Finance Director.",
    ]
    y = A4[1] - 30 * mm
    for line in lines:
        c.drawString(20 * mm, y, line)
        y -= 6 * mm
    c.showPage()
    c.save()


def garbled(path: Path) -> None:
    """Broken ligatures, run-together words and a corrupted ToUnicode mapping.

    All three are produced the way they occur in the wild: the text is drawn
    normally, then the font's ToUnicode CMap is rewritten so two glyphs no longer
    map to the codepoints they display. "X" is remapped to U+FFFD, the
    replacement character, and "Z" to U+FB01, the fi ligature that should have
    been decomposed to two letters. Extraction then yields exactly the garbling a
    badly generated PDF produces.

    Writing the ligature directly does not work: reportlab helpfully decomposes
    it on the way in, which is the correct behaviour and the opposite of what
    this fixture needs to exercise.
    """
    _register_font()
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setFont(FONT, 11)
    lines = [
        "ConZdential Znancial Zle - Zrst draft",
        "TotalAmountDueOnReceiptOfThisInvoice",
        "PleaseRemitPaymentToTheAccountBelow",
        "The Xgure quoted above is provisional.",
        "Xnal reconciliation follows next month.",
        "Xreconciled balances carried forward.",
    ]
    y = A4[1] - 40 * mm
    for line in lines:
        c.drawString(20 * mm, y, line)
        y -= 8 * mm
    c.showPage()
    c.save()

    buffer.seek(0)
    reader = pypdf.PdfReader(buffer)
    writer = pypdf.PdfWriter()
    writer.append(reader)

    # "X" becomes the replacement character, "Z" becomes the fi ligature.
    remappings = ((b"<0058>", b"<FFFD>"), (b"<005A>", b"<FB01>"))
    patched: set[bytes] = set()
    for obj in writer._objects:
        if not isinstance(obj, pypdf.generic.DictionaryObject):
            continue
        if obj.get("/Type") != "/Font":
            continue
        to_unicode = obj.get("/ToUnicode")
        if to_unicode is None:
            continue
        stream = to_unicode.get_object()
        try:
            data = stream.get_data()
        except Exception:
            continue
        changed = data
        for source, target in remappings:
            if source in changed:
                changed = changed.replace(source, target)
                patched.add(source)
        if changed != data:
            stream.set_data(changed)

    missing = [s.decode() for s, _ in remappings if s not in patched]
    if missing:
        raise RuntimeError(
            f"could not patch the ToUnicode CMap for {missing}; the fixture would not "
            f"actually be garbled and the tests using it would be meaningless"
        )

    with path.open("wb") as handle:
        writer.write(handle)


def _render_first_page(source: Path, dpi: int = 200) -> Image.Image:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(source))
    try:
        return pdf[0].render(scale=dpi / 72.0).to_pil().convert("L")
    finally:
        pdf.close()


def _image_to_pdf(image: Image.Image, path: Path, page_size: tuple[float, float]) -> None:
    from reportlab.lib.utils import ImageReader

    c = canvas.Canvas(str(path), pagesize=page_size)
    c.drawImage(
        ImageReader(image), 0, 0, width=page_size[0], height=page_size[1], preserveAspectRatio=False
    )
    c.showPage()
    c.save()


def scanned_page(path: Path, source: Path) -> None:
    """A page that is one big image with no text layer at all."""
    _image_to_pdf(_render_first_page(source), path, A4)


def rotated_scan(path: Path, source: Path) -> None:
    """A skewed scan on a page that also carries a 90 degree rotation flag."""
    image = _render_first_page(source)
    skewed = image.rotate(-3.5, expand=True, fillcolor=255, resample=Image.BICUBIC)
    _image_to_pdf(skewed, path, A4)

    reader = pypdf.PdfReader(str(path))
    writer = pypdf.PdfWriter()
    for page in reader.pages:
        page.rotate(90)
        writer.add_page(page)
    with path.open("wb") as handle:
        writer.write(handle)


def encrypted(path: Path, source: Path) -> None:
    """Password protected with a non-empty user password."""
    reader = pypdf.PdfReader(str(source))
    writer = pypdf.PdfWriter()
    writer.append(reader)
    writer.encrypt("complydoc-test", algorithm="AES-256")
    with path.open("wb") as handle:
        writer.write(handle)


def scan_image(path: Path, source: Path) -> None:
    """A standalone PNG scan, saved with an explicit 200 DPI tag."""
    _render_first_page(source).save(path, dpi=(200, 200))


def sample_docx(path: Path) -> None:
    import docx
    from docx.shared import Pt

    document = docx.Document()
    document.add_heading("Supplier Agreement", level=1)
    document.add_paragraph(
        "This agreement is made between Acme Holdings Ltd and Northwind Supplies Limited "
        "on 04/01/2026. The contact for invoicing is jane.doe@example.com."
    )
    table = document.add_table(rows=4, cols=3)
    table.cell(0, 0).merge(table.cell(0, 2)).text = "Charges for 2026"
    headers = ["Quarter", "Net", "VAT"]
    for i, header in enumerate(headers):
        table.cell(1, i).text = header
    for row, values in enumerate([("Q1", "4,250.00", "850.00"), ("Q2", "4,410.00", "882.00")], 2):
        for i, value in enumerate(values):
            table.cell(row, i).text = value
    for paragraph in document.paragraphs:
        for run in paragraph.runs:
            run.font.size = Pt(11)
    document.save(str(path))


def sample_xlsx(path: Path) -> None:
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Payments"
    sheet["A1"] = "Supplier payment run - March 2026"
    sheet.merge_cells("A1:D1")
    for i, header in enumerate(["Supplier", "Sort code", "Account", "Amount"], start=1):
        sheet.cell(row=2, column=i, value=header)
    rows = [
        ("Northwind Supplies Limited", "12-34-56", "12345678", 5100.00),
        ("Acme Holdings Ltd", "40-11-22", "87654321", 2340.50),
    ]
    for r, values in enumerate(rows, start=3):
        for ci, value in enumerate(values, start=1):
            sheet.cell(row=r, column=ci, value=value)

    second = workbook.create_sheet("Contacts")
    second["A1"] = "Name"
    second["B1"] = "Email"
    second["A2"] = "Jane Doe"
    second["B2"] = "jane.doe@example.com"
    workbook.save(str(path))


def broken_pdf(path: Path) -> None:
    """Not a readable PDF. Exercises the skip-and-report path."""
    path.write_bytes(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\nthis is not a pdf body at all\n")


def unsupported_file(path: Path) -> None:
    path.write_text("complydoc does not read plain text files.\n", encoding="utf-8")


def main() -> None:
    HERE.mkdir(parents=True, exist_ok=True)
    native = HERE / "native_text.pdf"

    native_text(native)
    two_column(HERE / "two_column.pdf")
    merged_header_table(HERE / "merged_header_table.pdf")
    mixed_page_sizes(HERE / "mixed_page_sizes.pdf")
    acroform(HERE / "acroform.pdf")
    sensitive_sample(HERE / "sensitive_sample.pdf")
    garbled(HERE / "garbled.pdf")
    scanned_page(HERE / "scanned_page.pdf", native)
    rotated_scan(HERE / "rotated_scan.pdf", native)
    encrypted(HERE / "encrypted.pdf", native)
    scan_image(HERE / "scan_page.png", native)
    sample_docx(HERE / "sample.docx")
    sample_xlsx(HERE / "sample.xlsx")
    broken_pdf(HERE / "broken.pdf")
    unsupported_file(HERE / "notes.txt")

    print(f"wrote fixtures to {HERE}")
    for item in sorted(HERE.iterdir()):
        print(f"  {item.name:28s} {item.stat().st_size:>8,d} bytes")


if __name__ == "__main__":
    main()
