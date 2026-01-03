import os
import textwrap
import base64
import requests
from io import BytesIO
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont

# =========================================================
# CONFIG
# =========================================================
OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
FB_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")

if not OPENAI_KEY:
    raise Exception("OPENAI_API_KEY missing")
if not FB_TOKEN or not FB_PAGE_ID:
    raise Exception("Facebook secrets missing")

client = OpenAI(api_key=OPENAI_KEY)

WATERMARK_TEXT = "© Yesterday's Letters"

STATIC_STYLE = (
    "High-fidelity modern Japanese anime digital painting, cinematic lighting, "
    "soft bloom, volumetric rays, nostalgic atmosphere, vertical composition "
    "with clear space for typography."
)

# =========================================================
# 1. CONCEPT
# =========================================================
def generate_concept():
    print("1. Generating Concept (GPT-5.2)...")

    r = client.chat.completions.create(
        model="gpt-5.2-chat-latest",
        messages=[
            {
                "role": "system",
                "content": (
                    "Output EXACTLY:\n"
                    "TEXT: <sentence>\n"
                    "POSITION: TOP or BOTTOM\n"
                    "SCENE: <visual description>"
                ),
            },
            {
                "role": "user",
                "content": "Write a poetic sentence (max 15 words) about memory or time."
            }
        ],
    )

    content = r.choices[0].message.content.strip().splitlines()

    text = content[0].replace("TEXT:", "").strip()
    position = content[1].replace("POSITION:", "").strip().upper()
    scene = content[2].replace("SCENE:", "").strip()

    prompt = f"{scene}. {STATIC_STYLE}"

    print("TEXT:", text)
    print("POSITION:", position)
    return text, position, prompt

# =========================================================
# 2. IMAGE (BASE64 – RELIABLE)
# =========================================================
def generate_image(prompt):
    print("2. Generating HD Image (Base64 Mode)...")

    r = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1024x1536",
        n=1,
    )

    image_b64 = r.data[0].b64_json
    if not image_b64:
        raise Exception("No image data returned")

    print("Image generation OK (base64)")
    return BytesIO(base64.b64decode(image_b64))

# =========================================================
# 3. DESIGN (NO UPSCALE – SAFE)
# =========================================================
def add_text_and_watermark(image_buffer, text, position):
    print("3. Designing typography...")

    img = Image.open(image_buffer).convert("RGBA")
    canvas = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    try:
        font_main = ImageFont.truetype("font.ttf", 90)
        font_mark = ImageFont.truetype("font.ttf", 38)
    except:
        font_main = ImageFont.load_default()
        font_mark = ImageFont.load_default()

    lines = textwrap.wrap(text, 22)
    y = int(img.height * (0.18 if position == "TOP" else 0.72))

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font_main)
        x = (img.width - (bbox[2] - bbox[0])) / 2

        for i in range(1, 4):
            draw.text((x+i, y+i), line, font=font_main, fill=(0, 0, 0, 120))
        draw.text((x, y), line, font=font_main, fill=(255, 255, 255, 255))

        y += 120

    wm_bbox = draw.textbbox((0, 0), WATERMARK_TEXT, font=font_mark)
    draw.text(
        ((img.width - (wm_bbox[2] - wm_bbox[0])) / 2, img.height - 80),
        WATERMARK_TEXT,
        font=font_mark,
        fill=(255, 255, 255, 140),
    )

    final_img = Image.alpha_composite(img, canvas)

    out = BytesIO()
    final_img.convert("RGB").save(out, "JPEG", quality=95)
    out.seek(0)

    print("Typography completed successfully")
    return out

# =========================================================
# 4. FACEBOOK POST (PAGE FEED)
# =========================================================
def post_to_facebook(image_buffer):
    print("Proceeding to Facebook post...")
    print("4. Posting to Facebook...")

    url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos"
    data = {
        "access_token": FB_TOKEN,
        "published": "true"
    }
    files = {
        "source": ("image.jpg", image_buffer, "image/jpeg")
    }

    r = requests.post(url, data=data, files=files)

    print("FB STATUS:", r.status_code)
    print("FB RESPONSE:", r.text)

    if r.status_code != 200:
        raise Exception("Facebook post failed")

    print("SUCCESS: Facebook post is live")

# =========================================================
# MAIN
# =========================================================
if __name__ == "__main__":
    text, position, prompt = generate_concept()
    image_buffer = generate_image(prompt)
    final_image = add_text_and_watermark(image_buffer, text, position)
    post_to_facebook(final_image)
