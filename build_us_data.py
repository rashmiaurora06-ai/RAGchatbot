"""Rebuild data/tickets.db and data/telecom_guide.pdf for a US mobile carrier ("MyTelecom").

The carrier, its policies and prices are fictional and only modelled on common US carrier
practice. data/faq.csv is edited by hand. After running this, re-index with ingest_all.py.

Run:  .venv/bin/python build_us_data.py
"""
import sqlite3
import textwrap

import config

TICKETS = [
    # (category, issue_type, description, resolution, status)
    ("connectivity", "No data after switching phones",
     "Customer moved their SIM to a new unlocked phone. Calls work but there is no mobile data.",
     "APN was blank on the unlocked phone. Set APN to internet.telecom.example and installed the carrier "
     "settings update. Data restored.", "resolved"),
    ("connectivity", "SOS only at home",
     "Phone shows SOS in the customer's apartment but full bars outside.",
     "Coverage map showed weak in-building signal. Turned on Wi-Fi Calling with the E911 address and "
     "offered a free signal booster under the in-home coverage program.", "resolved"),
    ("connectivity", "5G+ icon never appears",
     "Customer in a 5G+ city never sees 5G+ on a new phone.",
     "Phone's 5G mode was set to 'LTE only'. Switched to 5G Auto and confirmed the plan includes 5G+. "
     "5G+ showed once in a covered area.", "resolved"),
    ("connectivity", "Neighborhood outage",
     "Several customers on the same street lost service after a storm.",
     "Fiber cut to the local tower. Network team restored service within 9 hours. Affected customers "
     "received a one-day service credit on their next bill.", "resolved"),
    ("data", "Very slow data on Unlimited Starter",
     "Customer reports speeds under 1 Mbps every evening.",
     "Unlimited Starter can be slowed during congestion. Explained the plan terms and moved the customer "
     "to Unlimited Plus, which includes 50 GB of premium data. Speeds improved.", "resolved"),
    ("data", "Hotspot stopped working mid-month",
     "Customer's laptop connects to the phone hotspot but pages won't load.",
     "Customer had used all 5 GB of hotspot data and was slowed to 128 kbps. Added a one-time hotspot "
     "add-on and explained hotspot allowances per plan.", "resolved"),
    ("data", "Data usage higher than expected",
     "Customer used 20 GB in a week without streaming.",
     "Cloud photo backup and app auto-updates were running on mobile data. Set them to Wi-Fi only and "
     "turned on Data Saver.", "resolved"),
    ("billing", "First bill higher than quoted",
     "New customer's first bill was almost double the plan price.",
     "Bill included prorated charges for the partial first month, the next month in advance and a "
     "one-time activation fee. Walked through the bill; no error found.", "resolved"),
    ("billing", "Autopay discount missing",
     "Customer set up autopay but still pays the full price.",
     "Autopay was set up with a credit card, which doesn't qualify. Switched to a debit card and turned on "
     "paperless billing. Discount applied from the next bill and a one-time credit was given.", "resolved"),
    ("billing", "Charged twice for the same month",
     "Customer's bank shows two payments for the same bill.",
     "A manual payment and an autopay payment both went through. Second payment was refunded to the "
     "original payment method within 5 business days.", "resolved"),
    ("billing", "Unexpected international charges",
     "Customer was charged $96 after a trip to Italy.",
     "International Day Pass was charged for 8 days at $12. Customer had left data on while connected to "
     "hotel Wi-Fi. Explained that Day Pass charges on any day the phone uses the network abroad. "
     "Courtesy credit of 2 days applied.", "resolved"),
    ("roaming", "No service in Mexico",
     "Customer on an unlimited plan had no service after landing in Mexico.",
     "Data roaming was off on the phone. Turned it on and manually selected a partner network. Service "
     "worked at no extra cost since the plan includes Mexico.", "resolved"),
    ("roaming", "Huge bill from a cruise",
     "Customer was billed for calls and data while on a cruise ship.",
     "Cruise ship networks aren't covered by Day Pass. Explained the policy and issued a one-time 50% "
     "courtesy credit. Recommended Airplane Mode with ship Wi-Fi next time.", "resolved"),
    ("sim", "eSIM QR code won't scan",
     "Customer's eSIM activation QR code shows 'no longer valid'.",
     "QR code had expired after 30 days. Sent a new eSIM profile to the MyTelecom app and activated it "
     "over Wi-Fi.", "resolved"),
    ("sim", "SIM locked asking for PUK",
     "Customer entered the SIM PIN wrong three times.",
     "Verified the account owner and gave the PUK code from the account. Customer unlocked the SIM and "
     "set a new PIN.", "resolved"),
    ("voice", "Calls go straight to voicemail",
     "Incoming calls ring once or not at all and go to voicemail.",
     "Call forwarding to voicemail on 'no reply' was set to 5 seconds. Reset it to 30 seconds and "
     "refreshed the line's network provisioning.", "resolved"),
    ("voice", "Can't make calls after the 3G shutdown",
     "Customer's older phone can text but calls fail with 'not compatible'.",
     "Phone doesn't support HD Voice (VoLTE). Offered a free compatible replacement phone under the "
     "network upgrade program.", "resolved"),
    ("voice", "Too many spam calls",
     "Customer receives 10+ spam calls a day.",
     "Turned on Call Shield with automatic fraud blocking and spam labeling, and registered the number "
     "on the National Do Not Call Registry.", "resolved"),
    ("account", "Port-in stuck",
     "Number transfer from another carrier still pending after a day.",
     "Number Transfer PIN entered was expired. Customer generated a new PIN with the old carrier; port "
     "completed within 2 hours.", "resolved"),
    ("account", "Locked out of the MyTelecom app",
     "Customer can't sign in and the password reset text never arrives.",
     "Customer was signing in with the phone number instead of the MyTelecom ID email. Reset the password "
     "by email and signed in.", "resolved"),
    ("device", "Unlock request denied",
     "Customer's unlock request for a paid-off phone was denied.",
     "Line had been active only 40 days; unlock needs 60 days. Customer resubmitted after day 60 and was "
     "approved.", "resolved"),
    ("account", "Suspected SIM swap",
     "Customer lost service suddenly and got an email that their SIM was changed.",
     "Escalated to the fraud team. Account Lock turned on and SIM restored to the customer's phone.",
     "escalated"),
]

# Guide pages: (title, paragraphs). Plain ASCII so the simple PDF writer below can encode it.
GUIDE = [
    ("Network overview", [
        "MyTelecom runs a nationwide 4G LTE network and a 5G network. 5G on low-band spectrum covers most of "
        "the population with speeds similar to or somewhat faster than LTE. 5G+ uses mid-band (C-band) and "
        "high-band (mmWave) spectrum in select cities, stadiums and airports and can deliver much higher "
        "speeds and lower latency. mmWave signals are short range and are easily blocked by walls and glass.",
        "The 3G network was shut down in 2022. All voice calls now use HD Voice (VoLTE) over the LTE or 5G "
        "network. Phones that do not support VoLTE cannot make calls, even if they show signal.",
        "Network management: on plans with a premium data allowance, data may be slowed during network "
        "congestion after the allowance is used. Unlimited Starter can be slowed during congestion at any time. "
        "Video is streamed at standard definition unless the plan includes HD streaming.",
    ]),
    ("Data settings and APN", [
        "Most phones bought from MyTelecom set data up automatically. Unlocked phones may need the APN set "
        "manually. APN name: MyTelecom. APN: internet.telecom.example. MMSC: http://mms.telecom.example. "
        "Leave username and password blank.",
        "Carrier settings updates deliver network configuration changes. On iPhone they appear in Settings > "
        "General > About. On Android they install with system updates. Always install them before "
        "troubleshooting data or calling problems.",
        "A network settings reset clears saved Wi-Fi networks, Bluetooth pairings and APN changes and often "
        "fixes persistent data problems. It does not erase personal data.",
    ]),
    ("Wi-Fi Calling and E911", [
        "Wi-Fi Calling routes calls and texts over any Wi-Fi network when cellular signal is weak. Calls to US "
        "numbers are free. Calls to international numbers while on Wi-Fi Calling are billed at international "
        "rates unless the plan includes them.",
        "Federal rules require an E911 address for Wi-Fi Calling. The address is sent to 911 if a call is "
        "placed over Wi-Fi and location cannot be determined. Customers must update it when they move. 911 "
        "calls always try the cellular network first.",
        "In-home coverage program: customers with poor indoor signal and no outage may qualify for a free "
        "signal booster after Wi-Fi Calling has been tried.",
    ]),
    ("SIM, eSIM and SIM security", [
        "A physical SIM (nano-SIM) stores the subscriber identity (IMSI) and the secret key used to "
        "authenticate to the network. An eSIM is the same identity downloaded to a chip built into the phone. "
        "One phone can store several eSIM profiles, which allows dual-line use while traveling.",
        "eSIM QR codes expire 30 days after they are issued and can only be used once. A new eSIM profile can "
        "be sent to the MyTelecom app or generated by support.",
        "SIM PIN protects the SIM if the phone is lost. Three wrong PIN entries lock the SIM and require the "
        "8-digit PUK. Ten wrong PUK entries permanently disable the SIM and a replacement is needed.",
        "SIM swap fraud happens when a criminal moves a victim's number to a new SIM to receive one-time "
        "codes. Account Lock blocks SIM changes, number transfers and ownership changes until the owner turns "
        "it off. Support must verify identity with the account passcode before any SIM change.",
    ]),
    ("Number transfers (porting)", [
        "Port-in: to bring a number from another carrier, the customer needs the account number and a Number "
        "Transfer PIN from the old carrier, and the billing ZIP code. The old account must stay active until "
        "the transfer completes. Wireless-to-wireless transfers usually finish within a few hours; landline "
        "numbers can take up to 10 business days.",
        "Port-out: the account owner creates a Number Transfer PIN in the MyTelecom app. The PIN is valid for "
        "7 days. When the number leaves, that line is cancelled and any remaining device balance becomes due.",
        "A port fails if the name, account number, PIN or ZIP code does not match exactly, or if Account Lock "
        "is on at the losing carrier.",
    ]),
    ("Device unlocking and compatibility", [
        "Postpaid devices can be unlocked when they are fully paid off, have been active on MyTelecom for at "
        "least 60 days, are not reported lost or stolen, and the account has no past-due balance. Prepaid "
        "devices need 6 months of paid service. Military personnel on deployment can request early unlock.",
        "Unlock requests are made at mytelecom.example/unlock and are usually decided within 2 business days. "
        "The customer receives unlock instructions by email.",
        "Bring-your-own-phone customers should check compatibility in the MyTelecom app. The phone must "
        "support VoLTE and the bands used by MyTelecom (LTE bands 2, 4, 5, 12, 14, 30, 66 and 5G n5, n77, "
        "n260).",
    ]),
    ("International travel", [
        "Unlimited plans include talk, text and data in Canada and Mexico at no extra cost. High-speed data in "
        "those countries may be limited.",
        "International Day Pass costs $12 per day per line and lets customers use their plan in 210+ "
        "countries. A day is a 24-hour period that starts the first time the phone uses the network abroad. "
        "There is a monthly cap of $120 per line; days after that are free in the same bill cycle.",
        "Without Day Pass, pay-per-use rates apply: up to $3 per minute for calls, $0.50 per text sent and "
        "$2.05 per MB of data. Cruise ships and airplanes use separate networks billed at higher rates and are "
        "never covered by Day Pass.",
        "Troubleshooting abroad: turn on data roaming, restart, then select a network manually. Check that "
        "Day Pass was added before departure.",
    ]),
    ("Billing, taxes and fees", [
        "Plans are billed one month in advance. When a plan or feature changes mid-cycle, the next bill shows "
        "prorated credits and charges for the partial month. New lines include a one-time $35 activation fee.",
        "Bills show government taxes and fees (Federal Universal Service charge, state and local 911 fees, "
        "sales tax) and carrier fees (Administrative and Regulatory Cost Recovery fee). Amounts depend on the "
        "service address.",
        "Autopay discount: $10 per line per month on eligible unlimited plans, up to 8 lines, when autopay "
        "uses a checking account or debit card and paperless billing is on. Credit cards do not qualify.",
        "Late payment: a fee of $5 or 1.5% of the past-due amount, whichever is greater. Service may be "
        "suspended 30 days after the due date. Payment arrangements can delay suspension.",
        "Refunds: prepaid refills and one-time payments can be refunded within 7 days if unused. Postpaid "
        "monthly charges are not refundable, but confirmed billing errors are credited.",
    ]),
    ("Calls, messaging and alerts", [
        "Visual Voicemail shows messages in a list and works on most smartphones. Basic voicemail is reached "
        "by pressing and holding 1. Voicemail boxes hold up to 30 messages kept for 30 days.",
        "Call Shield is a free service that blocks likely fraud calls and labels spam. Calls authenticated "
        "under the STIR/SHAKEN framework show as Verified. Customers can also register on the National Do Not "
        "Call Registry.",
        "RCS messaging supports typing indicators, read receipts and high-quality photos over data. When RCS is "
        "not available messages fall back to SMS and MMS.",
        "Wireless Emergency Alerts (WEA) are sent by authorized government agencies. Imminent threat and AMBER "
        "alerts can be turned off on most phones; Presidential alerts cannot.",
    ]),
    ("Troubleshooting checklist", [
        "1. Check for an outage in the MyTelecom app (Help > Network status). 2. Turn Airplane Mode on for 30 "
        "seconds, then off. 3. Restart the phone. 4. Install software and carrier settings updates. 5. Check "
        "the SIM or eSIM is active. 6. Reset network settings. 7. Test the SIM in another phone.",
        "If the issue continues after these steps, collect the address, the time it started, the device model "
        "and any error message, and contact support at 611 or through chat in the MyTelecom app.",
    ]),
]


def build_tickets() -> None:
    config.TICKETS_DB.unlink(missing_ok=True)
    con = sqlite3.connect(config.TICKETS_DB)
    con.execute("""CREATE TABLE tickets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id   TEXT UNIQUE NOT NULL,
            category    TEXT NOT NULL,
            issue_type  TEXT NOT NULL,
            description TEXT NOT NULL,
            resolution  TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'resolved'
        )""")
    con.executemany(
        "INSERT INTO tickets (ticket_id, category, issue_type, description, resolution, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(f"TK-{i:03d}", *t) for i, t in enumerate(TICKETS, start=1)])
    con.commit()
    con.close()


def _pdf_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_guide_pdf() -> None:
    """A text-only PDF (Helvetica, US Letter). Each page keeps the running header and 'Page N' footer
    that ingest_guides.py strips out."""
    pages = []
    for n, (title, paras) in enumerate(GUIDE, start=1):
        lines = [("F2", 9, "Telecom Technical Reference Guide - Internal Use Only"), ("F2", 9, ""),
                 ("F1", 14, f"{n}. {title}"), ("F2", 11, "")]
        for p in paras:
            lines += [("F2", 11, line) for line in textwrap.wrap(p, 92)] + [("F2", 11, "")]
        y, ops = 750, ["BT"]
        for font, size, text in lines:
            ops.append(f"/{font} {size} Tf 1 0 0 1 60 {y} Tm ({_pdf_text(text)}) Tj")
            y -= size + 5
        ops.append(f"/F2 9 Tf 1 0 0 1 290 40 Tm (Page {n}) Tj")
        ops.append("ET")
        pages.append("\n".join(ops).encode("latin-1"))

    objs: list[bytes] = []
    n_pages = len(pages)
    page_ids = [5 + 2 * i for i in range(n_pages)]
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {n_pages} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    for i, content in enumerate(pages):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {page_ids[i] + 1} 0 R "
                    f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>".encode())
        objs.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")

    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    config.GUIDE_PDF.write_bytes(bytes(out))


if __name__ == "__main__":
    build_tickets()
    build_guide_pdf()
    print(f"tickets: {len(TICKETS)} written to {config.TICKETS_DB.name}")
    print(f"guide: {len(GUIDE)} pages written to {config.GUIDE_PDF.name}")
