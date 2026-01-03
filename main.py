import os
import requests
import textwrap
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from io import BytesIO

# --- CONFIGURATION ---
# The bot gets these keys from your GitHub Secrets
OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
FB_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")

client = OpenAI(api_key=OPENAI_KEY)

# --- BRANDING SETTINGS ---
PAGE_NAME = "Yesterday's Letters"
WATERMARK_TEXT = "© Yesterday's Letters"

# --- STYLE LOCK (The "Glowing Nostalgia" Engine) ---
# This ensures every image looks like a high-budget anime movie (Makoto Shinkai style)
STATIC_STYLE = (
    "Art style: High-fidelity digital anime art (Makoto Shinkai inspired). "
    "Features hyper-realistic cinematic lighting, heavy bloom effect, and volumetric god rays. "
    "Deep, rich shadows contrasting with glowing highlights. "
    "Nostalgic, dreamy atmosphere with a vast landscape and a large dark negative space in the sky (for text). "
    "Golden hour or twilight lighting."
)

def generate_concept():
    """ 1. The Author: Writes a 'Letter Fragment' """
    print("1. Generating Concept...")
    
    response = client.chat.completions.create(
        model="gpt-5.2-chat-latest",
        messages=[
            {"role": "system", "content": "You are the writer for a nostalgic page called 'Yesterday's Letters'. Output format: CAPTION: [text] | SCENE: [visual description]"},
            {"role": "user", "content": "Write a short, poetic sentence about memory, distance, faith, or time (max 18 words). Then describe a matching visual scene of a lone figure in a vast setting. Do NOT describe the art style."}
        ]
    )
    content = response.choices[0].message.content
    
    try:
        parts = content.split("|")
        caption = parts[0].replace("CAPTION:", "").strip()
        scene_description = parts[1].replace("SCENE:", "").strip()
        
        # Combine Scene + Fixed Style
        final_prompt = f"{scene_description}. {STATIC_STYLE}"
        return caption, final_prompt
    except:
        print("Error parsing GPT response.")
        return None, None

def generate_image(prompt):
    """ 2. The Artist: Draws the image """
    print(f"2. Generating Image...")
    
    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1024",
        quality="standard",
        n=1,
    )
    return response.data[0].url

def add_text_and_watermark(image_url, text):
    """ 3. The Graphic Designer: Overlays Caption + Watermark """
    print("3. Designing Image...")
    
    response = requests.get(image_url)
    img = Image.open(BytesIO(response.content)).convert("RGBA")
    
    # ENHANCEMENT: Boost contrast slightly to make shadows pop (Cinematic look)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.1) 
    
    width, height = img.size
    draw = ImageDraw.Draw(img)
    
    # --- LOAD FONTS ---
    # Attempts to load your 'font.ttf' file. Falls back to default if missing.
    try:
        font_main = ImageFont.truetype("font.ttf", 42) 
        font_mark = ImageFont.truetype("font.ttf", 20)
    except:
        font_main = ImageFont.load_default()
        font_mark = ImageFont.load_default()
        print("Warning: Custom font not found. Using default.")

    # --- PART A: MAIN CAPTION ---
    lines = textwrap.wrap(text, width=28) 
    line_height = 55 
    total_height = len(lines) * line_height
    
    # Position: Top 30% (The Sky)
    start_y = (height * 0.30) - (total_height / 2)
    
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font_main)
        text_width = bbox[2] - bbox[0]
        x_pos = (width - text_width) / 2
        
        # Heavy Dark Shadow (offset 3px) for readability against bright bloom
        draw.text((x_pos + 3, start_y + 3), line, font=font_main, fill=(0, 0, 0, 200))
        # Main Text (Soft White)
        draw.text((x_pos, start_y), line, font=font_main, fill="#F8F8F8")
        start_y += line_height

    # --- PART B: BRAND WATERMARK ---
    bbox_mark = draw.textbbox((0, 0), WATERMARK_TEXT, font=font_mark)
    mark_width = bbox_mark[2] - bbox_mark[0]
    mark_x = (width - mark_width) / 2
    mark_y = height - 50 
    
    # Watermark (White with 50% opacity)
    draw.text((mark_x, mark_y), WATERMARK_TEXT, font=font_mark, fill=(255, 255, 255, 140))

    # Save
    final_buffer = BytesIO()
    img.convert("RGB").save(final_buffer, format="JPEG", quality=95)
    final_buffer.seek(0)
    return final_buffer

def post_to_facebook(image_buffer, caption):
    """ 4. The Publisher """
    print("4. Posting to Facebook...")
    url = f"https://graph.facebook.com/{FB_PAGE_ID}/photos"
    payload = { 'access_token': FB_TOKEN, 'message': caption }
    files = { 'source': ('image.jpg', image_buffer, 'image/jpeg') }
    
    r = requests.post(url, data=payload, files=files)
    if r.status_code == 200:
        print("SUCCESS! Post is live.")
    else:
        print(f"FAILED: {r.text}")

# --- EXECUTE ---
if __name__ == "__main__":
    if not OPENAI_KEY or not FB_TOKEN:
        print("Error: Missing API Keys. Check GitHub Secrets.")
    else:
        caption_text, img_prompt = generate_concept()
        if caption_text:
            raw_img_url = generate_image(img_prompt)
            final_img = add_text_and_watermark(raw_img_url, caption_text)

            post_to_facebook(final_img, caption_text)
