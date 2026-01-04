import os
import random
import base64
import requests
from io import BytesIO
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont, ImageStat

# =========================================================
# ENV / SECRETS
# =========================================================
OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
FB_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")

if not OPENAI_KEY:
    raise Exception("OPENAI_API_KEY missing")
if not FB_TOKEN or not FB_PAGE_ID:
    raise Exception("Facebook secrets missing")

client = OpenAI(api_key=OPENAI_KEY)

# =========================================================
# PATHS
# =========================================================
FONT_PATH = "fonts/LibreBaskerville-Regular.ttf"
WATERMARK_TEXT = "© Yesterday's Letters"

# =========================================================
# HUMAN THOUGHT BANK (NO LLM)
# =========================================================
THOUGHT_BANK = {
    "prayer": [
        "Some nights, faith is the only shelter.",
        "Please God, let me win this time.",
        "I don’t have answers, only prayers."
    ],
    "uncertainty": [
        "I don’t know where this road leads, but I keep walking.",
        "Nothing feels certain, except that I must continue."
    ],
    "reflection": [
        "Growth is quiet when no one is watching.",
        "I didn’t realize I was healing until it stopped hurting."
    ],
    "hope": [
        "May you receive what you’ve been praying for in 2026.",
        "God has a plan. Trust, wait, and believe."
    ]
}

# =========================================================
# SCENE → EMOTION → PROMPT
# =========================================================
SCENES = {
    "night_rain": {
        "emotion": "prayer",
        "prompt": (
            "A solitary figure standing under an umbrella in heavy night rain, "
            "wet pavement reflecting warm street lights, quiet street, deep shadows"
        )
    },
    "forest": {
        "emotion": "reflection",
        "prompt": (
            "A lone figure standing in a dense forest clearing at dusk, "
            "soft moonlight filtering through trees, stillness, depth"
        )
    },
    "road": {
        "emotion": "uncertainty",
        "prompt": (
            "A person standing on an empty road at twilight, road disappearing into distance, "
            "vast sky, quiet uncertainty"
        )
    },
    "water": {
        "emotion": "hope",
        "prompt": (
            "A figure sitting near calm water at night, gentle reflections, stars above, "
            "peaceful atmosphere"
        )
    }
}

STATIC_STYLE = (
    "Studio Ghibli–inspired cinematic illustration with realistic lighting. "
    "Physically accurate soft shadows, subtle bloom, nostalgic mood, "
    "painterly textures, restrained line work, film grain, emotional stillness."
)

# =========================================================
# 1. SELECT SCENE + TEXT
# =========================================================
def select_concept():
    scene_key = random.choice(list(SCENES.keys()))
    scene = SCENES[scene_key]

    emotion = scene["emotion"]
    text = random.choice(THOUGHT_BANK[emotion])

    prompt = f"{scene['prompt']}. {STATIC_STYLE}"

    print("SCENE:", scene_key)
    print("TEXT:", text)

    return text, prompt

# =========================================================
# 2. IMAGE GENERATION (SUPPORTED SIZE)
# =========================================================
def generate_image(prompt):
    r = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1024x1536",
        n=1,
    )

    image_b64 = r.data[0].b64_json
    return BytesIO(base64.b64decode(image_b64))

# =========================================================
# 3. SAFE CROP TO 4:5 (1024x1280)
# =========================================================
def crop_to_4_5(img):
    target_height = int(img.width * 5 / 4)
    top = (img.height - target_height) // 2
    return img.crop((0, top, img.width, top + target_height))

# =========================================================
# 4. SMART TEXT PLACEMENT + TYPOGRAPHY
# =========================================================
def add_text(image_buffer, text):
    img = Image.open(image_buffer).convert("RGBA")
    img = crop_to_4_5(img)

    draw = ImageDraw.Draw(img)

    FONT_SIZE = 42
    LINE_HEIGHT = int(FONT_SIZE * 1.3)
    TEXT_BOX_HEIGHT = 220
    MAX_TEXT_WIDTH = int(img.width * 0.58)

    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    watermark_font = ImageFont.truetype(FONT_PATH, 26)

    # ---- Candidate regions (y start positions)
    regions = [
        int(img.height * 0.18),
        int(img.height * 0.30),
        int(img.height * 0.42),
        int(img.height * 0.55),
        int(img.height * 0.68),
    ]

    def region_score(y):
        box = img.crop((0, y, img.width, y + TEXT_BOX_HEIGHT)).convert("L")
        stat = ImageStat.Stat(box)
        return stat.var[0]  # lower variance = quieter background

    best_y = min(regions, key=region_score)

    # ---- Wrap text by pixel width
    words = text.split()
    lines = []
    current = ""

    for w in words:
        test = current + (" " if current else "") + w
        if draw.textbbox((0, 0), test, font=font)[2] <= MAX_TEXT_WIDTH:
            current = test
        else:
            lines.append(current)
            current = w
    if current:
        lines.append(current)

    # ---- Ensure fixed height (shrink font if needed)
    while len(lines) * LINE_HEIGHT > TEXT_BOX_HEIGHT:
        FONT_SIZE -= 2
        LINE_HEIGHT = int(FONT_SIZE * 1.3)
        font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

    text_height = len(lines) * LINE_HEIGHT
    y = best_y + (TEXT_BOX_HEIGHT - text_height) // 2

    # ---- Auto contrast detection
    sample = img.crop((img.width//4, best_y, img.width*3//4, best_y+TEXT_BOX_HEIGHT)).convert("L")
    brightness = ImageStat.Stat(sample).mean[0]

    if brightness < 120:
        text_color = (245, 245, 240, 255)
        shadow = (0, 0, 0, 90)
    else:
        text_color = (30, 30, 30, 255)
        shadow = (255, 255, 255, 80)

    # ---- Draw text
    for line in lines:
        w = draw.textbbox((0, 0), line, font=font)[2]
        x = (img.width - w) // 2
        draw.text((x+1, y+1), line, font=font, fill=shadow)
        draw.text((x, y), line, font=font, fill=text_color)
        y += LINE_HEIGHT

    # ---- Watermark
    wm_w = draw.textbbox((0, 0), WATERMARK_TEXT, font=watermark_font)[2]
    draw.text(
        ((img.width - wm_w) // 2, img.height - 48),
        WATERMARK_TEXT,
        font=watermark_font,
        fill=(255, 255, 255, 120)
    )

    out = BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=95)
    out.seek(0)
    return out

# =========================================================
# 5. FACEBOOK POST
# =========================================================
def post_to_facebook(image_buffer):
    url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos"
    data = {"access_token": FB_TOKEN}
    files = {"source": ("image.jpg", image_buffer, "image/jpeg")}

    r = requests.post(url, data=data, files=files)
    if r.status_code != 200:
        raise Exception(r.text)

    print("Posted successfully")

# =========================================================
# MAIN
# =========================================================
if __name__ == "__main__":
    text, prompt = select_concept()
    image = generate_image(prompt)
    final = add_text(image, text)
    post_to_facebook(final)
