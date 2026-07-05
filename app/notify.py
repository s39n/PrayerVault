"""Morning prayer prompt: compose the message and push it (via ntfy)."""
import datetime

import httpx

from . import config, notes, settings

# Small server-side verse list for the push (mirrors the frontend Today verses).
VERSES = [
    ("The Lord is my shepherd; I shall not want.", "Psalm 23:1"),
    ("Cast all your anxieties on him, because he cares for you.", "1 Peter 5:7"),
    ("Be still, and know that I am God.", "Psalm 46:10"),
    ("The steadfast love of the Lord never ceases; his mercies are new every morning.", "Lamentations 3:22-23"),
    ("Trust in the Lord with all your heart, and do not lean on your own understanding.", "Proverbs 3:5"),
    ("I can do all things through him who strengthens me.", "Philippians 4:13"),
    ("Come to me, all who labor and are heavy laden, and I will give you rest.", "Matthew 11:28"),
    ("The Lord is near to all who call on him, to all who call on him in truth.", "Psalm 145:18"),
    ("Do not be anxious about anything, but in everything by prayer let your requests be made known to God.", "Philippians 4:6"),
    ("Wait for the Lord; be strong, and let your heart take courage.", "Psalm 27:14"),
    ("And we know that for those who love God all things work together for good.", "Romans 8:28"),
    ("He heals the brokenhearted and binds up their wounds.", "Psalm 147:3"),
    ("The Lord will fight for you, and you have only to be silent.", "Exodus 14:14"),
    ("My grace is sufficient for you, for my power is made perfect in weakness.", "2 Corinthians 12:9"),
    ("Fear not, for I am with you; be not dismayed, for I am your God.", "Isaiah 41:10"),
    ("This is the day that the Lord has made; let us rejoice and be glad in it.", "Psalm 118:24"),
    ("The Lord is my light and my salvation; whom shall I fear?", "Psalm 27:1"),
    ("Delight yourself in the Lord, and he will give you the desires of your heart.", "Psalm 37:4"),
    ("The name of the Lord is a strong tower; the righteous man runs into it and is safe.", "Proverbs 18:10"),
    ("Weeping may tarry for the night, but joy comes with the morning.", "Psalm 30:5"),
]


def verse_of_day() -> tuple[str, str]:
    doy = datetime.date.today().timetuple().tm_yday
    return VERSES[doy % len(VERSES)]


def compose_morning() -> tuple[str, str]:
    """Return (title, body) for the morning prompt."""
    text, ref = verse_of_day()
    title = "PrayerVault - a word for today"
    body = f"“{text}” - {ref}"
    try:
        ongoing = [i for i in notes.list_notes() if i.get("status") == "ongoing"]
        if ongoing:
            ongoing.sort(key=lambda i: str(i.get("date", "")))
            body += f"\n\nStill on your heart: {ongoing[0].get('title', '')}"
    except Exception:
        pass
    body += "\n\nCome and pray."
    return title, body


async def send_ntfy(topic: str, title: str, body: str) -> None:
    url = f"{config.NTFY_SERVER.rstrip('/')}/{topic}"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            url,
            content=body.encode("utf-8"),
            headers={"Title": title, "Tags": "pray,sunrise", "Priority": "default"},
        )
        r.raise_for_status()


async def send_morning(cfg: dict | None = None) -> bool:
    """Send the morning prompt per settings. Returns True if a push was sent."""
    m = (cfg or settings.load())["morning"]
    if m.get("delivery") == "ntfy" and m.get("ntfy_topic"):
        title, body = compose_morning()
        await send_ntfy(m["ntfy_topic"], title, body)
        return True
    return False
