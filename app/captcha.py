import io
import secrets
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .db import execute, insert, one
from .security import random_token

ALPHABET = "ACDEFHJKMNPRTUVWXY34679"
LENGTH = 5
TTL_MINUTES = 10
WIDTH = 220
HEIGHT = 70
FONT = Path(__file__).resolve().parent / "fonts" / "DejaVuSansCondensed-Bold.ttf"
INKS = [(24, 24, 27), (30, 58, 95), (88, 28, 60), (20, 83, 45)]


def create():
    execute("delete from captchas where expires_at < now()")
    answer = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
    row = insert(
        """insert into captchas (handle, answer, expires_at)
           values (%s, %s, now() + make_interval(mins => %s)) returning handle""",
        (random_token(18), answer, TTL_MINUTES),
    )
    return row["handle"]


def solve(handle, typed):
    if not handle:
        return False
    row = insert("delete from captchas where handle = %s and expires_at > now() returning answer", (handle,))
    if not row:
        return False
    cleaned = "".join((typed or "").split()).upper()
    return secrets.compare_digest(cleaned, row["answer"])


def image(handle):
    row = one("select answer from captchas where handle = %s and expires_at > now()", (handle,))
    if not row:
        return None
    return render(row["answer"])


def render(text):
    rng = secrets.SystemRandom()
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (244, 244, 245))
    draw = ImageDraw.Draw(canvas)
    for _ in range(6):
        draw.line(
            [(rng.randint(0, WIDTH), rng.randint(0, HEIGHT)), (rng.randint(0, WIDTH), rng.randint(0, HEIGHT))],
            fill=(rng.randint(150, 200),) * 3, width=rng.randint(1, 2),
        )
    slot = (WIDTH - 20) // len(text)
    for index, char in enumerate(text):
        font = ImageFont.truetype(str(FONT), rng.randint(36, 44))
        tile = Image.new("RGBA", (60, 64), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((30, 32), char, font=font, fill=rng.choice(INKS) + (255,), anchor="mm")
        tile = tile.rotate(rng.uniform(-28, 28), resample=Image.BICUBIC)
        canvas.paste(tile, (10 + index * slot + rng.randint(-5, 3), rng.randint(0, 8)), tile)
    for _ in range(3):
        start = rng.randint(10, HEIGHT - 10)
        points = [(x, start + rng.randint(-12, 12)) for x in range(0, WIDTH + 1, 22)]
        draw.line(points, fill=rng.choice(INKS), width=2, joint="curve")
    for _ in range(260):
        draw.point((rng.randint(0, WIDTH - 1), rng.randint(0, HEIGHT - 1)), fill=(rng.randint(60, 170),) * 3)
    canvas = canvas.filter(ImageFilter.SMOOTH)
    out = io.BytesIO()
    canvas.save(out, "PNG", optimize=True)
    return out.getvalue()
