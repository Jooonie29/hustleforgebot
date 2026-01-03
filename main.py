import os
import requests
import textwrap
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

# --- CONFIGURATION ---
OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
FB_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")

client = OpenAI(api_key=OPENAI_KEY)

WATERMARK_TEXT = "© Yesterday's Letters"

# --- STYLE LOCK ---
STATIC_STYLE = (
    "Art style: High-fidelity modern Japanese anime digital painting. "
    "Features cinematic lighting with heavy bloom and volumetric sun rays. "
    "Vibrant yet nostalgic colors, clean lines, and detailed scenery. "
    "Composition: Vertical frame with significant clean space in the sky or ground for text."
)

# -------------------------------------------------
# 1. GENERATE CONCEPT
# -------------------------------------------------
def generate_concept():
    print("1. Generating Concept (GPT-5.2)...")
    try:
        response = client.chat.completions.create(
            model="gpt-5.2-chat-latest",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the writer for 'Yesterday's Letters'. "
                        "Output format ONLY: "
                        "TEXT: [sentence] | POSITION: [TOP or BOTTOM] | SCENE: [visual description]"
                    ),
                },
                {
                    "role": "user",
                    "content": "Write a poetic sentence (max 15 words) about memory or time."
                }
            ],
        )

        content = response.choices[0].message.content
        parts = content.split("|")

        text = parts[0].replace("TEXT:", "").strip()
        position = parts[1].replace("POSITION:", "").strip().upper()
        scene = parts[2].replace("SCENE:", "").strip()

        return text, position, f"{scene}. {STATIC_STYLE}"

    except Exception as e:
        print("Concept Error:", e)
        return None, None, None


# -------------------------------------------------
# 2. GENERATE IMAGE (URL MODE)
# -------------------------------------------------
def generate_image(prompt):
    print("2. Generating HD Image (URL Mode)...")
    try:
        response = client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size="1024x1536",
            n=1,
        )
        print("Image generation OK")
        return response.data[0].url

    except Exception as e:
        print("Image Error RAW:", str(e))
        return None


# -------------------------------------------------
# 3. ADD TEXT + WATERMARK
# -------------------------------------------------
def add_text_and_watermark(image_url, text, position):
    print("3. Designing HD Typography...")

    r = requests.get(image_url, timeout=60)
    r.raise_for_status()

    img = Image.open(BytesIO(r.content)).convert("RGBA")

    canvas_size = (img.size[0] * 2, img.size[1] * 2)
    text_layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_layer)

    try:
        font_main = ImageFont.truetype("font.ttf", 100)
        font_mark = ImageFont.truetype("font.ttf", 45)
    except:
        font_main = ImageFont.load_default()
        font_mark = ImageFont.load_default()

    lines = textwrap.wrap(text, width=22)
    line_height = 130

    if position == "TOP":
        current_y = int(canvas_size[1] * 0.18)
    else:
        current_y = int(canvas_size[1] * 0.72)

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font_main)
        text_width = bbox[2] - bbox[0]
        x = (canvas_size[0] - text_width) / 2

        for off in range(1, 6):
            draw.text((x + off, current_y + off), line, font=font_main, fill=(0, 0, 0, 120))

        draw.text((x, current_y), line, font=font_main, fill=(255, 255, 255, 255))
        current_y += line_height

    mark_bbox = draw.textbbox((0, 0), WATERMARK_TEXT, font=font_mark)
    draw.text(
        ((canvas_size[0] - (mark_bbox[2] - mark_bbox[0])) / 2, canvas_size[1] - 140),
        WATERMARK_TEXT,
        font=font_mark,
        fill=(255, 255, 255, 140),
    )

    text_layer = text_layer.resize(img.size, Image.LANCZOS)
    final_img = Image.alpha_composite(img, text_layer)

    buffer = BytesIO()
    final_img.convert("RGB").save(buffer, format="JPEG", quality=98)
    buffer.seek(0)

    return buffer


# -------------------------------------------------
# 4. POST TO FACEBOOK PAGE (FIXED)
# -------------------------------------------------
def post_to_facebook(image_buffer):
    print("4. Posting to Facebook...")

    url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos"
    payload = {
        "access_token": FB_TOKEN,
        "published": "true"
    }
    files = {
        "source": ("image.jpg", image_buffer, "image/jpeg")
    }

    response = requests.post(url, data=payload, files=files)

    print("Facebook status:", response.status_code)
    print("Facebook response:", response.text)

    if response.status_code != 200:
        raise Exception("Facebook post failed")

    print("SUCCESS: Post is live on the Page.")


# -------------------------------------------------
# MAIN EXECUTION
# -------------------------------------------------
if __name__ == "__main__":
    if not OPENAI_KEY or not FB_TOKEN or not FB_PAGE_ID:
        raise Exception("Missing required environment variables")

    text, position, prompt = generate_concept()
    if not text:
        raise Exception("Concept generation failed")

    image_url = generate_image(prompt)
    if not image_url:
        raise Exception("Image generation failed")

    final_image = add_text_and_watermark(image_url, text, position)
    post_to_facebook(final_image)

