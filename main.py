import os
import random
import base64
import textwrap
import requests
from io import BytesIO

from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont, ImageStat

# =========================================================
# ENV / KEYS
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
FONT_MAIN = "fonts/LibreBaskerville-Regular.ttf"
FONT_WATERMARK = "fonts/LibreBaskerville-Regular.ttf"

WATERMARK_TEXT = "© Yesterday's Letters"

# =========================================================
# CURATED HUMAN THOUGHT BANK (NO LLM)
# =========================================================
THOUGHT_BANK = {
    "rain": [
        "Please God, let me win this time.",
        "I whispered prayers louder than the rain.",
        "Some nights, faith is the only shelter."
    ],
    "road": [
        "I don’t know where this leads, but I keep walking.",
        "Uncertainty taught me how to trust.",
        "I stayed even when I didn’t see the way forward."
    ],
    "forest": [
        "Growth is quiet when no one is watching.",
        "I healed slowly, like trees do.",
        "Not every season asks you to bloom."
    ],
    "water": [
        "I let go of what I couldn’t carry anymore.",
        "Time softened the memories I thought would drown me.",
        "Some answers arrive gently."
    ],
    "window": [
        "I watched life change before I was ready.",
        "I waited longer than I planned.",
        "Hope looked different from the other side."
    ],
    "night": [
        "Even here, God didn’t forget me.",
        "I learned to breathe in the dark.",
        "The quiet stayed with me."
    ]
}

# =========================================================
# SCENE → EMOTION PAIRING
# =========================================================
SCENES = {
    "rain": "night rain, single figure holding umbrella, reflective ground",
    "road": "empty road at dusk, long perspective, solitary figure",
    "forest": "dense forest clearing, moonlight through trees",
    "water": "riverbank at night, calm flowing water, soft reflections",
    "window": "warm interior light, person looking out window at night",
    "night": "open landscape under starry sky, quiet isolation"
}

STATIC_STYLE = (
    "Studio Ghibli–inspired illustration with realistic cinematic lighting. "
    "Physically believable shadows, soft bloom highlights, gentle lens diffusion. "
    "Painterly textures, restrained line work, natural color grading. "
    "Subtle film grain, nostalgic atmosphere, emotional stillness."
)

# =========================================================
# 1. PICK SCENE + HUMAN TEXT
# =========================================================
def pick_concept():
    scene_key = random.choice(list(SCENES.keys()))
    text = random.choice(THOUGHT_BANK[scene_key])
    scene_prompt = f"{SCENES[scene_key]}. {STATIC_STYLE}"

    print("SCENE:", scene_key)
    print("TEXT:", text)

    return text, scene_prompt

# =========================================================
# 2. IMAGE GENERATION (SUPPORTED SIZE ONLY)
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
# 3. SAFE CROP TO 4:5
# =========================================================
def crop_to_4_5(img):
    target_h = int(img.width * 5 / 4)
    top = (img.height - target_h) // 2
    return img.crop((0, top, img.width, top + target_h))

# =========================================================
# 4. AUTO CONTRAST DETECTION
# =========================================================
def is_background_dark(img, box):
    crop = img.crop(box)
    stat = ImageStat.Stat(crop)
    return sum(stat.mean) / 3 < 120

# =========================================================
# 5. LOCKED TEXT BOX + AUTO FONT SCALE
# =========================================================
def draw_text(img, text):
    draw = ImageDraw.Draw(img)

    box_width = int(img.width * 0.8)
    box_height = 300
    box_x = (img.width - box_width) // 2
    box_y = int(img.height * 0.18)

    box = (box_x, box_y, box_x + box_width, box_y + box_height)
    dark_bg = is_background_dark(img, box)

    fill = (245, 245, 240, 255) if dark_bg else (30, 30, 30, 255)
    shadow = (0, 0, 0, 80) if dark_bg else (255, 255, 255, 80)

    font_size = 56
    while font_size > 34:
        font = ImageFont.truetype(FONT_MAIN, font_size)
        wrapped = textwrap.wrap(text, width=28)

        total_height = len(wrapped) * (font_size + 10)
        if total_height <= box_height:
            break
        font_size -= 2

    y = box_y + (box_height - total_height) // 2

    for line in wrapped:
        w = draw.textbbox((0, 0), line, font=font)[2]
        x = (img.width - w) // 2

        draw.text((x + 1, y + 1), line, font=font, fill=shadow)
        draw.text((x, y), line, font=font, fill=fill)
        y += font_size + 10

# =========================================================
# 6. WATERMARK
# =========================================================
def draw_watermark(img):
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_WATERMARK, 28)

    w = draw.textbbox((0, 0), WATERMARK_TEXT, font=font)[2]
    draw.text(
        ((img.width - w) // 2, img.height - 60),
        WATERMARK_TEXT,
        font=font,
        fill=(255, 255, 255, 140),
    )

# =========================================================
# 7. COMPOSE FINAL IMAGE
# =========================================================
def compose(image_buffer, text):
    img = Image.open(image_buffer).convert("RGB")
    img = crop_to_4_5(img)

    draw_text(img, text)
    draw_watermark(img)

    out = BytesIO()
    img.save(out, "JPEG", quality=95)
    out.seek(0)
    return out

# =========================================================
# 8. FACEBOOK POST
# =========================================================
def post_to_facebook(image_buffer):
    url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos"
    data = {"access_token": FB_TOKEN, "published": "true"}
    files = {"source": ("image.jpg", image_buffer, "image/jpeg")}

    r = requests.post(url, data=data, files=files)
    if r.status_code != 200:
        raise Exception(r.text)

# =========================================================
# MAIN
# =========================================================
if __name__ == "__main__":
    text, prompt = pick_concept()
    img_buf = generate_image(prompt)
    final = compose(img_buf, text)
    post_to_facebook(final)
