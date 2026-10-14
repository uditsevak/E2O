"""Fill a development IMAP server with realistic sample mail (enquiries, noise, a reply).

Meant for the GreenMail server in docker-compose (profile "dev-imap"), which accepts any
username/password and creates the mailbox on first login. Running it twice adds the mail twice;
restart the imap container for a clean mailbox.

    # full stack in Docker
    docker compose run --rm api python -m scripts.seed_dev_mailbox --host imap
    # backend running on your machine
    uv run python -m scripts.seed_dev_mailbox
"""

import argparse
import imaplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid

# A tiny one-page PDF ("Request for Quotation"). PDF readers rebuild the missing xref table.
_PDF_TEXT = (
    b"BT /F1 18 Tf 60 780 Td (Request for Quotation - RPL/RFQ/2291) Tj "
    b"0 -40 Td /F1 12 Tf (200 nos WNRF 4in #150 A105, ASME B16.5, RF facing) Tj "
    b"0 -20 Td (Test certificate EN 10204 3.1. Delivery: Pune, 3 weeks.) Tj ET"
)
SAMPLE_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R"
    b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length " + str(len(_PDF_TEXT)).encode() + b">>stream\n" + _PDF_TEXT + b"\nendstream endobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)

SAMPLE_CSV = (
    b"Sr,Description,Size,Class,Material,Qty\n"
    b"1,Slip-on flange RF,2 inch,150,SS316,40\n"
    b"2,Blind flange RF,6 inch,300,SS316,50\n"
    b"3,Weld neck flange RF,4 inch,600,A105,24\n"
)


def _message(
    subject: str,
    sender: str,
    body: str,
    when: datetime,
    to: str,
    message_id: str | None = None,
    in_reply_to: str | None = None,
    attachments: list[tuple[str, str, bytes]] | None = None,
    attach_email: bytes | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg["Date"] = format_datetime(when)
    msg["Message-ID"] = message_id or make_msgid(domain=sender.split("@")[-1].strip(">"))
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)
    for filename, ctype, data in attachments or []:
        maintype, subtype = ctype.split("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    if attach_email is not None:
        msg.add_attachment(attach_email, maintype="message", subtype="rfc822")
    return msg


def sample_mail(mailbox: str) -> list[tuple[str, datetime, bytes]]:
    now = datetime.now(UTC)
    rfq_id = "<rfq-2291@reliablepumps.in>"
    forwarded = _message(
        "Enquiry: Flanges for refinery shutdown job",
        "Vikram Desai <vikram.desai@westcoastprojects.in>",
        "Dear Team,\n\nWe have a shutdown job at Jamnagar. Please quote for:\n"
        '- WNRF 8" #300 A105 - 16 nos\n- Blind flange 8" #300 A105 - 4 nos\n\n'
        "Delivery at site within 10 days. Please send your offer by Friday.\n\nRegards,\nVikram",
        now - timedelta(days=4, hours=2),
        to="suresh@dcengineering.in",
    )
    mail = [
        _message(
            'RFQ: WNRF Flanges 4" #150 A105 - 200 Nos',
            "Anil Mehta <anil.mehta@reliablepumps.in>",
            "Dear Sir,\n\nKindly quote your best price for the items in the attached RFQ "
            '(200 nos WNRF 4" #150 A105 as per ASME B16.5, RF facing).\n'
            "Test certificate as per EN 10204 3.1 required. Delivery at Pune within 3 weeks.\n"
            "Please send your offer by 20th of this month.\n\nRegards,\nAnil Mehta\n"
            "Purchase Dept., Reliable Pumps Pvt Ltd\n+91 98220 00000",
            now - timedelta(days=1, hours=3),
            to=mailbox,
            message_id=rfq_id,
            attachments=[("RPL-RFQ-2291.pdf", "application/pdf", SAMPLE_PDF)],
        ),
        _message(
            "Enquiry for SS316 flanges - BOQ attached",
            "Priya Nair <priya.nair@kochichem.co.in>",
            "Hello,\n\nPlease find the BOQ attached for our new plant expansion. "
            "Kindly send your best price and delivery period. We need mill TCs for all items.\n\n"
            "Thanks,\nPriya Nair\nKochi Chemicals Ltd",
            now - timedelta(hours=5),
            to=mailbox,
            attachments=[("BOQ-flanges.csv", "text/csv", SAMPLE_CSV)],
        ),
        _message(
            "flange ka rate bhejiye",
            "Ramesh Patel <rameshpatel.traders@gmail.com>",
            'Namaste ji,\n\nHumein 25 nos slip-on flange 3" #150 MS chahiye. '
            "कृपया आज ही रेट और डिलीवरी बताइए। Ahmedabad delivery.\n\nRamesh Patel\nPatel Traders",
            now - timedelta(hours=2),
            to=mailbox,
        ),
        _message(
            "Steel Price Watch - Week 41",
            "SteelWatch India <newsletter@steelwatch.example>",
            "This week: HR coil prices up 2%, scrap stable. Read the full report on our website.\n\n"
            "Unsubscribe | Manage preferences",
            now - timedelta(days=2),
            to=mailbox,
        ),
        _message(
            "Invoice INV/24-25/0871 - forgings dispatched",
            "Accounts <accounts@shreeforgings.in>",
            "Dear Sir,\n\nPlease find our invoice for 2 MT A105 forgings dispatched today via "
            "VRL Logistics, LR no. 554120. Kindly arrange payment as per terms.\n\nShree Forgings",
            now - timedelta(days=3),
            to=mailbox,
        ),
        _message(
            "PO 4512 - dispatch status?",
            "Kiran Joshi <kiran@aquaflowvalves.com>",
            "Hi,\n\nAny update on dispatch for our PO 4512 (blind flanges)? Site is waiting.\n\nKiran",
            now - timedelta(days=1),
            to=mailbox,
        ),
        _message(
            "Fwd: Enquiry: Flanges for refinery shutdown job",
            "Suresh Iyer <suresh@dcengineering.in>",
            "Forwarding this enquiry that came to my mailbox. Please check and quote.\n\nSuresh",
            now - timedelta(days=4),
            to=mailbox,
            attach_email=forwarded.as_bytes(),
        ),
    ]
    inbox = [("INBOX", m["Date"].datetime, m.as_bytes()) for m in mail]  # type: ignore[union-attr]
    reply = _message(
        'Re: RFQ: WNRF Flanges 4" #150 A105 - 200 Nos',
        f"DC Engineering Sales <{mailbox}>",
        "Dear Anil ji,\n\nThank you for your enquiry. Please find our offer attached.\n\n"
        "Regards,\nSales, DC Engineering",
        now - timedelta(hours=20),
        to="Anil Mehta <anil.mehta@reliablepumps.in>",
        in_reply_to=rfq_id,
    )
    return [*inbox, ("Sent", reply["Date"].datetime, reply.as_bytes())]  # type: ignore[union-attr]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=3143)
    parser.add_argument("--user", default="sales@dcengineering.in", help="mailbox to fill (any name works)")
    parser.add_argument("--password", default="test", help="GreenMail accepts anything")
    args = parser.parse_args()

    conn = imaplib.IMAP4(args.host, args.port, timeout=15)
    conn.login(args.user, args.password)
    conn.create("Sent")  # "already exists" is fine
    for folder, when, raw in sample_mail(args.user):
        typ, _ = conn.append(folder, None, imaplib.Time2Internaldate(when.timestamp()), raw)
        if typ != "OK":
            raise SystemExit(f"could not add mail to {folder}")
    conn.logout()
    print(f"Added sample mail to {args.user} on {args.host}:{args.port} (7 in INBOX, 1 in Sent).")
    print("Connect it in the app with: Other (IMAP) → server", args.host, "port 3993, SSL, any password.")


if __name__ == "__main__":
    main()
