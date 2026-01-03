import os
import requests
import textwrap
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from io import BytesIO

# --- CONFIGURATION ---
OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
FB_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")

client = OpenAI(api_key=OPENAI_KEY)
WATERMARK_TEXT = "© Yesterday's Letters"

# --- STYLE LOCK (4:5 Ratio Optimized) ---
STATIC_STYLE = (
    "Art style: High-fidelity digital anime art (Makoto Shinkai inspired). "
    "Cinematic lighting, heavy bloom, volumetric rays. "
    "Nostalgic, dreamy atmosphere. Aspect ratio is vertical 4:5. "
    "Ensure there is a large, clean negative space in either the TOP or BOTTOM for text."
)

def generate_concept():
    """ 1. The Author: Writes the letter and decides layout """
    print("1. Generating Concept...")
    response = client.chat.completions.create(
        model="gpt-5.2-chat-latest",
        messages=[
            {"role": "system", "content": "You are the writer for 'Yesterday's Letters'. Output format: TEXT: [poetic sentence] | POSITION: [TOP or BOTTOM] | SCENE: [visual description]"},
            {"role": "user", "content": "Write a poetic sentence (max 15 words) and decide if the text should be at the TOP or BOTTOM based on the scene's composition."}
        ]
    )
    content = response.choices[0].message.content
    try:
        parts = content.split("|")
        text = parts[0].replace("TEXT:", "").strip()
        pos = parts[1].replace("POSITION:", "").strip().upper()
        scene = parts[2].replace("SCENE:", "").strip()
        return text, pos, f"{scene}. {STATIC_STYLE}"
    except:
        return None, None, None

def generate_image(prompt):
    """ 2. The Artist """
    print("2. Generating Image...")
    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1792", # This creates the vertical 4:5 / 9:16 cinematic look
        quality="hd",
        n=1,
    )
    return response.data[0].url

def add_text_and_watermark(image_url, text, position):
    """ 3. The Graphic Designer: Smart Placement """
    print(f"3. Designing Image (Position: {position})...")
    response = requests.get(image_url)
    img = Image.open(BytesIO(response.content)).convert("RGBA")
    width, height = img.size
    overlay = Image.new('RGBA', img.size, (0,0,0,0))
    draw = ImageDraw.Draw(overlay)
    
    try:
        font_main = ImageFont.truetype("font.ttf", 55) # Larger for vertical
        font_mark = ImageFont.truetype("font.ttf", 25)
    except:
        font_main = ImageFont.load_default()
        font_mark = ImageFont.load_default()

    lines = textwrap.wrap(text, width=22)
    line_height = 70
    total_text_height = len(lines) * line_height
    
    # SMART POSITIONING
    if position == "TOP":
        start_y = height * 0.20
    else: # BOTTOM
        start_y = height * 0.70

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font_main)
        x_pos = (width - (bbox[2] - bbox[0])) / 2
        # Heavy 4-way Shadow for visibility
        for off in [(3,3), (-3,3), (3,-3), (-3,-3)]:
            draw.text((x_pos + off[0], start_y + off[1]), line, font=font_main, fill=(0,0,0,230))
        draw.text((x_pos, start_y), line, font=font_main, fill="#FFFFFF")
        start_y += line_height

    # Watermark at the very bottom center
    mark_bbox = draw.textbbox((0, 0), WATERMARK_TEXT, font=font_mark)
    draw.text(((width-(mark_bbox[2]-mark_bbox[0]))/2, height-80), WATERMARK_TEXT, font=font_mark, fill=(255,255,255,150))

    combined = Image.alpha_composite(img, overlay)
    buffer = BytesIO()
    combined.convert("RGB").save(buffer, format="JPEG", quality=95)
    buffer.seek(0)
    return buffer

def post_to_facebook(image_buffer):
    """ 4. The Publisher: NO CAPTION """
    print("4. Posting Image only...")
    url = f"https://graph.facebook.com/{FB_PAGE_ID}/photos"
    # Note: 'message' is removed to keep the post clean
    payload = { 'access_token': FB_TOKEN }
    files = { 'source': ('image.jpg', image_buffer, 'image/jpeg') }
    r = requests.post(url, data=payload, files=files)
    if r.status_code == 200: print("SUCCESS!")
    else: print(f"FAILED: {r.text}")

if __name__ == "__main__":
    text, pos, prompt = generate_concept()
    if text:
        img_url = generate_image(prompt)
        final_img = add_text_and_watermark(img_url, text, pos)
        post_to_facebook(final_img)
