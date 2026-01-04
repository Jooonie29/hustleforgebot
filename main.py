import os
import random
import base64
import requests
from io import BytesIO
from datetime import datetime
import pytz

from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont, ImageStat

# =========================================================
# ENV / CONFIG
# =========================================================
OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
FB_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Manila")

if not OPENAI_KEY:
    raise Exception("OPENAI_API_KEY missing")
if not FB_TOKEN or not FB_PAGE_ID:
    raise Exception("Facebook secrets missing")

client = OpenAI(api_key=OPENAI_KEY)

# =========================================================
# COST CONTROL
# =========================================================
# RULE #2: ONE POST PER DAY ONLY
POST_WINDOWS = [
    (19, 21),  # 7–9 PM ONLY
]

LAST_POST_FILE = "last_post.txt"

def is_good_posting_time():
    tz = pytz.timezone(TIMEZONE)
    hour = datetime.now(tz).hour
    return any(start <= hour < end for start, end in POST_WINDOWS)

def already_posted_today():
    today = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d")
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE) as f:
            return f.read().strip() == today
    return False

def mark_posted_today():
    today = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d")
    with open(LAST_POST_FILE, "w") as f:
        f.write(today)

# =========================================================
# CURATED HUMAN THOUGHT BANK (NO LLM)
# =========================================================
THOUGHT_BANK = {
    "rain": [
        "Some nights, faith is the only shelter.",
        "I whispered prayers I didn’t know how to say out loud.",
        "God hears you, even in the rain."
    ],
    "forest": [
        "Growth is quiet when no one is watching.",
        "Not everything that’s slow is lost.",
        "I stayed long enough to hear myself think."
    ],
    "road": [
        "I didn’t know where I was going, only that I had to keep walking.",
        "The road teaches patience.",
        "Faith sometimes looks like the next step."
    ],
    "water": [
        "Still waters teach louder lessons.",
        "Some answers arrive gently.",
        "I let go of what I could no longer carry."
    ],
    "night": [
        "God has a plan. Trust, wait, and believe.",
        "Even here, I was not forgotten.",
        "The stars stayed with me."
    ]
}

# =========================================================
# SCENE → PROMPT
# =========================================================
SCENE_PROMPTS = {
    "rain": "night rain, umbrella, wet pavement, soft streetlights",
    "forest": "quiet forest clearing, moonlight through trees",
    "road": "empty road at dusk, long shadows, distant horizon",
    "water": "calm lake at night, stars reflected on water",
    "night": "open night sky, gentle starlight, peaceful stillness"
}

STATIC_STYLE = (
    "Studio Ghibli inspired illustration with realistic cinematic lighting. "
    "Soft bloom, natural shadows, gentle atmospheric depth. "
    "Painterly textures, restrained line work, nostalgic mood."
)

# =========================================================
# MONTHLY VISUAL THEMES (NO EXTRA COST)
# =========================================================
MONTHLY_THEMES = {
    "01": "Cool blue tones, quiet beginnings, minimal contrast.",
    "02": "Warm highlights, soft shadows, longing and memory.",
    "03": "Balanced neutral light, sense of becoming.",
    "04": "Bright diffused light, hopeful softness.",
    "05": "Clear light, grounded stillness.",
    "06": "Golden hour warmth, nostalgic glow.",
    "07": "Cool night tones, silence and depth.",
    "08": "Muted warmth, waiting and pause.",
    "09": "Soft desaturation, letting go.",
    "10": "Higher contrast, cinematic depth.",
    "11": "Warm interior glow, gratitude.",
    "12": "Cold nights with small warm lights, quiet hope."
}

def get_monthly_theme():
    month = datetime.now(pytz.timezone(TIMEZONE)).strftime("%m")
    return MONTHLY_THEMES.get(month, "")

def choose_scene_and_text():
    scene = random.choice(list(THOUGHT_BANK.keys()))
    text = random.choice(THOUGHT_BANK[scene])
    return scene, text

# =========================================================
# IMAGE GENERATION (CALLED ONLY IF POSTING)
# =========================================================
def generate_image(scene):
    theme = get_monthly_theme()
    prompt = (
        f"{SCENE_PROMPTS[scene]}. "
        f"{STATIC_STYLE} "
        f"{theme}"
    )

    r = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1024x1536",
        n=1,
    )

    image_b64 = r.data[0].b64_json
    return BytesIO(base64.b64decode(image_b64))

# =========================================================
# IMAGE PROCESSING
# =========================================================
FONT_MAIN = "fonts/LibreBaskerville-Regular.ttf"
WATERMARK_TEXT = "© Yesterday's Letters"

def crop_to_4_5(img):
    target_h = int(img.width * 5 / 4)
    top = (img.height - target_h) // 2
    return img.crop((0, top, img.width, top + target_h))

def is_dark(img, box):
    crop = img.crop(box).convert("L")
    return ImageStat.Stat(crop).mean[0] < 130

def add_text(image_buffer, text):
    img = Image.open(image_buffer).convert("RGBA")
    img = crop_to_4_5(img)

    draw_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(draw_layer)

    font = ImageFont.truetype(FONT_MAIN, 42)
    box_w = int(img.width * 0.72)
    box_h = 220
    box_x = (img.width - box_w) // 2
    box_y = int(img.height * 0.45)

    dark = is_dark(img, (box_x, box_y, box_x + box_w, box_y + box_h))
    color = (245, 245, 240, 255) if dark else (30, 30, 30, 255)

    words = text.split()
    lines, line = [], ""
    for w in words:
        test = f"{line} {w}".strip()
        if draw.textlength(test, font=font) <= box_w:
            line = test
        else:
            lines.append(line)
            line = w
    lines.append(line)

    y = box_y + (box_h - len(lines) * 54) // 2
    for l in lines:
        w = draw.textlength(l, font=font)
        draw.text(((img.width - w) // 2, y), l, font=font, fill=color)
        y += 54

    final = Image.alpha_composite(img, draw_layer)
    out = BytesIO()
    final.convert("RGB").save(out, "JPEG", quality=95)
    out.seek(0)
    return out

# =========================================================
# FACEBOOK POST
# =========================================================
def post_to_facebook(image_buffer):
    url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos"
    data = {"access_token": FB_TOKEN, "published": "true"}
    files = {"source": ("image.jpg", image_buffer, "image/jpeg")}

    r = requests.post(url, data=data, files=files)
    if r.status_code != 200:
        raise Exception(r.text)

# =========================================================
# MAIN (STRICT ORDER — DO NOT CHANGE)
# =========================================================
if __name__ == "__main__":

    # RULE #1 — NEVER GENERATE UNLESS WE WILL POST
    if not is_good_posting_time():
        print("Outside posting window. Skipping.")
        exit(0)

    if already_posted_today():
        print("Already posted today. Skipping.")
        exit(0)

    # ONLY NOW DO WE SPEND MONEY
    scene, text = choose_scene_and_text()
    print("SCENE:", scene)
    print("TEXT:", text)

    image_buffer = generate_image(scene)
    final_image = add_text(image_buffer, text)
    post_to_facebook(final_image)

    mark_posted_today()
    print("Post successful.")
