import os
import requests
import textwrap
import base64
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from io import BytesIO

# --- CONFIGURATION ---
OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
FB_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")

client = OpenAI(api_key=OPENAI_KEY)
WATERMARK_TEXT = "© Yesterday's Letters"

# --- STYLE LOCK (2026 Optimized & Safety-Compliant) ---
STATIC_STYLE = (
    "Art style: High-fidelity modern Japanese anime digital painting. "
    "Features cinematic lighting with heavy bloom and volumetric sun rays. "
    "Vibrant yet nostalgic colors, clean lines, and detailed scenery. "
    "Composition: Vertical frame with significant clean space in the sky or ground for text."
)

def generate_concept():
    """ 1. The Author: Writes the letter and decides layout using GPT-5.2 """
    print("1. Generating Concept (GPT-5.2)...")
    try:
        response = client.chat.completions.create(
            model="gpt-5.2-chat-latest",
            messages=[
                {"role": "system", "content": "You are the writer for 'Yesterday's Letters'. Output format: TEXT: [poetic sentence] | POSITION: [TOP or BOTTOM] | SCENE: [visual description]"},
                {"role": "user", "content": "Write a poetic sentence (max 15 words) about memory or time. Decide if text goes at TOP or BOTTOM based on the scene."}
            ]
        )
        content = response.choices[0].message.content
        parts = content.split("|")
        text = parts[0].replace("TEXT:", "").strip()
        pos = parts[1].replace("POSITION:", "").strip().upper()
        scene = parts[2].replace("SCENE:", "").strip()
        return text, pos, f"{scene}. {STATIC_STYLE}"
    except Exception as e:
        print(f"Concept Error: {e}")
        return None, None, None

def generate_image(prompt):
    """ 2. The Artist: Using GPT Image 1.5 with Base64 output """
    print("2. Generating HD Image (GPT Image 1.5)...")
    try:
        response = client.images.generate(
            model="gpt-image-1.5", 
            prompt=prompt,
            size="1024x1536", # Best supported vertical ratio
            quality="high",
            response_format="b64_json",
            n=1,
        )
        return response.data[0].b64_json
    except Exception as e:
        print(f"Image Error: {e}")
        return None

def add_text_and_watermark(image_data, text, position):
    """ 3. The Graphic Designer: Super-Sampling for Crisp Typography """
    print(f"3. Designing HD Typography (Position: {position})...")
    
    # Decode Base64 data
    img_bytes = base64.b64decode(image_data)
    img = Image.open(BytesIO(img_bytes)).convert("RGBA")
    
    # Create a 2x larger canvas for 'Super-Sampling' (makes text crisp)
    canvas_size = (img.size[0] * 2, img.size[1] * 2)
    text_layer = Image.new('RGBA', canvas_size, (0,0,0,0))
    draw = ImageDraw.Draw(text_layer)
    
    try:
        # Doubled font size for the super-sampling process
        font_main = ImageFont.truetype("font.ttf", 100) 
        font_mark = ImageFont.truetype("font.ttf", 45)
    except:
        font_main = ImageFont.load_default()
        font_mark = ImageFont.load_default()
        print("Warning: Custom font not found, using default.")

    lines = textwrap.wrap(text, width=22)
    line_height = 130 
    
    # Position logic
    if position == "TOP":
        current_y = canvas_size[1] * 0.18
    else:
        current_y = canvas_size[1] * 0.72

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font_main)
        x_pos = (canvas_size[0] - (bbox[2] - bbox[0])) / 2
        
        # Soft Multi-layer Shadow
        for off in range(1, 6): 
            draw.text((x_pos+off, current_y+off), line, font=font_main, fill=(0,0,0,100))
        
        # Main White Text
        draw.text((x_pos, current_y), line, font=font_main, fill=(255, 255, 255, 255))
        current_y += line_height

    # Watermark center bottom
    mark_bbox = draw.textbbox((0, 0), WATERMARK_TEXT, font=font_mark)
    draw.text(((canvas_size[0]-(mark_bbox[2]-mark_bbox[0]))/2, canvas_size[1]-140), 
              WATERMARK_TEXT, font=font_mark, fill=(255,255,255,140))

    # Downscale for anti-aliasing (The "Clean" secret)
    text_layer = text_layer.resize(img.size, resample=Image.LANCZOS)
    
    # Combine and export
    final_img = Image.alpha_composite(img, text_layer)
    buffer = BytesIO()
    final_img.convert("RGB").save(buffer, format="JPEG", quality=98)
    buffer.seek(0)
    return buffer

def post_to_facebook(image_buffer):
    """ 4. The Publisher: Image-only post """
    print("4. Posting to Facebook...")
    url = f"https://graph.facebook.com/{FB_PAGE_ID}/photos"
    payload = { 'access_token': FB_TOKEN }
    files = { 'source': ('image.jpg', image_buffer, 'image/jpeg') }
    
    r = requests.post(url, data=payload, files=files)
    if r.status_code == 200:
        print("SUCCESS! Post is live.")
    else:
        print(f"FAILED: {r.text}")

# --- EXECUTE ---
if __name__ == "__main__":
    if not OPENAI_KEY or not FB_TOKEN or not FB_PAGE_ID:
        print("Error: Missing API Keys in GitHub Secrets.")
    else:
        text, pos, prompt = generate_concept()
        if text:
            img_data = generate_image(prompt)
            if img_data:
                final_img = add_text_and_watermark(img_data, text, pos)
                post_to_facebook(final_img)
