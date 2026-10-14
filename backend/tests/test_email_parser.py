from datetime import UTC, datetime

from app.pipeline.email_parser import decode_text, html_to_text, parse_email, sniff_content_type
from tests.fake_imap import make_email

PDF = b"%PDF-1.4\n%fake pdf\n"


def test_simple_email_with_pdf() -> None:
    raw = make_email(
        subject='RFQ: 4" WNRF #150',
        sender="Suresh Patil <Suresh@Customer.com>",
        when=datetime(2026, 10, 14, 5, 0, tzinfo=UTC),
        message_id="<abc123@customer.com>",
        attachments=[("RFQ-2291.pdf", "application/pdf", PDF)],
    )
    parsed = parse_email(raw)
    assert parsed.subject == 'RFQ: 4" WNRF #150'
    assert parsed.from_ is not None and parsed.from_.address == "suresh@customer.com"
    assert parsed.from_.name == "Suresh Patil"
    assert parsed.message_id == "abc123@customer.com"
    assert parsed.date == datetime(2026, 10, 14, 5, 0, tzinfo=UTC)
    assert "Please quote" in parsed.body_text
    assert [(a.filename, a.content_type, a.data) for a in parsed.attachments] == [
        ("RFQ-2291.pdf", "application/pdf", PDF)
    ]
    assert parsed.warnings == []


def test_encoded_headers_and_hindi_body() -> None:
    raw = (
        b"From: =?UTF-8?B?4KSw4KS+4KSc4KWH4KS2?= <rajesh@example.in>\r\n"
        b"To: sales@dc.in\r\n"
        b"Subject: =?UTF-8?Q?Enquiry_=E2=80=93_SS316_flanges?=\r\n"
        b"Message-ID: <x1@example.in>\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"Content-Transfer-Encoding: 8bit\r\n\r\n" + "नमस्ते, कृपया 50 नग का भाव भेजें।".encode() + b"\r\n"
    )
    parsed = parse_email(raw)
    assert parsed.subject == "Enquiry – SS316 flanges"
    assert parsed.from_ is not None and parsed.from_.name == "राजेश"
    assert "कृपया 50 नग" in parsed.body_text


def test_wrong_and_unknown_charsets_do_not_break_parsing() -> None:
    latin_body = "Price in ₹ please – urgent".encode("cp1252", errors="replace")
    raw = (
        b"From: a@b.com\r\nSubject: test\r\nContent-Type: text/plain; charset=iso-8859-1\r\n\r\n" + latin_body
    )
    assert "urgent" in parse_email(raw).body_text

    raw = b"From: a@b.com\r\nSubject: t\r\nContent-Type: text/plain; charset=x-made-up\r\n\r\nhello there"
    parsed = parse_email(raw)
    assert parsed.body_text == "hello there"
    assert any("x-made-up" in w for w in parsed.warnings)


def test_decode_text_fallbacks() -> None:
    assert decode_text("₹500".encode(), None, []) == "₹500"
    assert decode_text("café".encode("cp1252"), "unknown-8bit", []) == "café"
    assert decode_text("Rs. 500 – urgent".encode("cp1252"), None, []) == "Rs. 500 – urgent"
    warnings: list[str] = []
    assert decode_text(b"\xff\xfe broken", "utf-8", warnings)
    assert warnings


def test_html_only_email_gets_text_body() -> None:
    raw = (
        b"From: a@b.com\r\nSubject: t\r\nMIME-Version: 1.0\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        b"<html><head><style>p{color:red}</style></head><body><p>Dear Sir,</p><p>Need <b>200</b> pcs"
        b"</p><table><tr><td>Size</td><td>2&quot;</td></tr></table><script>alert(1)</script></body></html>"
    )
    parsed = parse_email(raw)
    assert parsed.body_html and "<b>200</b>" in parsed.body_html
    assert "Dear Sir," in parsed.body_text and "Need 200 pcs" in parsed.body_text
    assert 'Size\t2"' in parsed.body_text
    assert "alert" not in parsed.body_text and "color" not in parsed.body_text


def test_octet_stream_pdf_is_sniffed_and_forwarded_email_kept_whole() -> None:
    inner = make_email(subject="Original enquiry", sender="buyer@customer.com")
    outer = (
        b"From: Sales <sales@dc.in>\r\nTo: owner@dc.in\r\nSubject: Fwd: Original enquiry\r\n"
        b"MIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=XYZ\r\n\r\n"
        b"--XYZ\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nsee below\r\n"
        b"--XYZ\r\nContent-Type: application/octet-stream\r\nContent-Transfer-Encoding: base64\r\n"
        b'Content-Disposition: attachment; filename="drawing"\r\n\r\nJVBERi0xLjQKJWZha2UgcGRmCg==\r\n'
        b"--XYZ\r\nContent-Type: message/rfc822\r\n\r\n" + inner + b"\r\n--XYZ--\r\n"
    )
    parsed = parse_email(outer)
    assert parsed.body_text == "see below"
    kinds = [(a.filename, a.content_type) for a in parsed.attachments]
    assert kinds[0] == ("drawing", "application/pdf")
    assert kinds[1][1] == "message/rfc822" and kinds[1][0].endswith(".eml")
    assert b"Original enquiry" in parsed.attachments[1].data


def test_threading_headers() -> None:
    raw = make_email(message_id="<reply@dc.in>", in_reply_to="<orig@customer.com>")
    parsed = parse_email(raw)
    assert parsed.in_reply_to == "orig@customer.com"
    assert parsed.references == ["orig@customer.com"]


def test_garbage_input_never_raises() -> None:
    for raw in [
        b"",
        b"\x00\x01\x02",
        b"From: \r\nSubject: =?bogus?Q?x?=\r\n\r\n",
        b"Date: not a date\r\n\r\nx",
    ]:
        parse_email(raw)


def test_attachment_filenames_are_sanitised() -> None:
    raw = make_email(attachments=[("../../etc/passwd", "application/pdf", PDF)])
    name = parse_email(raw).attachments[0].filename
    assert "/" not in name and not name.startswith(".")


def test_sniff_content_type() -> None:
    assert sniff_content_type(PDF, "application/octet-stream", "x") == "application/pdf"
    assert sniff_content_type(b"PK\x03\x04...", "application/octet-stream", "rfq.xlsx").endswith(
        "spreadsheetml.sheet"
    )
    assert sniff_content_type(b"\xff\xd8\xff\xe0", "application/octet-stream", "scan") == "image/jpeg"
    assert sniff_content_type(b"anything", "image/png", "x.png") == "image/png"


def test_html_to_text_keeps_structure() -> None:
    text = html_to_text("<div>Line 1</div><div>Line&nbsp;2<br>Line 3</div><ul><li>a</li><li>b</li></ul>")
    assert text.split("\n")[0] == "Line 1"
    assert "Line 2" in text and "Line 3" in text
