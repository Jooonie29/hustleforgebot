import os
import random
import base64
import json
import requests
import csv
from io import BytesIO
from datetime import datetime, date
import pytz

from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont, ImageStat, ImageFilter

# =========================================================
# ENV / CONFIG
# =========================================================
OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
FB_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")
FB_PAGE_ID = os.environ.get("FB_PAGE_ID")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Manila")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
FORCE_POST = os.getenv("FORCE_POST", "false").lower() == "true"  # Bypass time/daily gates for testing

if not OPENAI_KEY and not DRY_RUN:
    raise Exception("OPENAI_API_KEY missing")
if (not FB_TOKEN or not FB_PAGE_ID) and not DRY_RUN:
    raise Exception("Facebook secrets missing")

if not DRY_RUN:
    client = OpenAI(api_key=OPENAI_KEY)
else:
    client = None

# =========================================================
# COST CONTROL
# =========================================================
POST_WINDOWS = [(13, 15)]  # 1-3 PM Manila time (for testing)
LAST_POST_FILE = "last_post.txt"
HOLIDAY_HISTORY_FILE = "holiday_history.json"

# STATE FILES
MONTHLY_USAGE_FILE = "monthly_usage.json"
THOUGHT_HISTORY_FILE = "thought_history.json"
ENGAGEMENT_LOG_FILE = "engagement_log.csv"
ERROR_LOG_FILE = "error_log.txt"
KILL_SWITCH_FILE = "posting_disabled.flag"

MAX_MONTHLY_IMAGES = 30
THOUGHT_COOLDOWN_DAYS = 35  # Full month + buffer to prevent recycling
SCENE_COOLDOWN_DAYS = 5     # Avoid same scene within 5 days
SCENE_HISTORY_FILE = "scene_history.json"

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
# FEATURE LOGIC
# =========================================================
def check_kill_switch():
    if os.path.exists(KILL_SWITCH_FILE):
        return True
    return False

def validate_fonts():
    """Check that all required fonts exist before making API calls."""
    required_fonts = [
        "fonts/LibreBaskerville-Regular.ttf",
    ]
    missing = [f for f in required_fonts if not os.path.exists(f)]
    if missing:
        raise Exception(f"Missing font files: {missing}")

def enable_kill_switch():
    with open(KILL_SWITCH_FILE, "w") as f:
        f.write("DISABLED DUE TO FB API ERROR")

def load_json_file(filepath):
    if not os.path.exists(filepath):
        return {}
    with open(filepath, "r") as f:
        return json.load(f)

def save_json_file(filepath, data):
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

def check_monthly_cap():
    data = load_json_file(MONTHLY_USAGE_FILE)
    month = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m")
    count = data.get(month, 0)
    return count >= MAX_MONTHLY_IMAGES

def increment_monthly_cap():
    data = load_json_file(MONTHLY_USAGE_FILE)
    month = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m")
    data[month] = data.get(month, 0) + 1
    save_json_file(MONTHLY_USAGE_FILE, data)

def get_thought_cooldown_history():
    return load_json_file(THOUGHT_HISTORY_FILE)

def update_thought_history(thought_text):
    history = get_thought_cooldown_history()
    today = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d")
    history[thought_text] = today
    save_json_file(THOUGHT_HISTORY_FILE, history)

def log_engagement(scene, thought, status="POSTED"):
    exists = os.path.exists(ENGAGEMENT_LOG_FILE)
    with open(ENGAGEMENT_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(["Date", "Time", "Scene", "Thought", "Status"])
        
        now = datetime.now(pytz.timezone(TIMEZONE))
        writer.writerow([
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
            scene,
            thought,
            status
        ])

def log_error(e):
    now = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")
    with open(ERROR_LOG_FILE, "a") as f:
        f.write(f"[{now}] ERROR: {e}\n")
        import traceback
        traceback.print_exc(file=f)

def check_token_health():
    if DRY_RUN:
        return True
    
    url = f"https://graph.facebook.com/me?access_token={FB_TOKEN}"
    try:
        r = requests.get(url)
        if r.status_code != 200:
            msg = f"Token Health Check Failed: {r.text}"
            print(msg)  # Print to console for GitHub Logs
            log_error(msg)
            enable_kill_switch()
            return False
        return True
    except Exception as e:
        msg = f"Token Health Check Exception: {e}"
        print(msg)  # Print to console
        log_error(msg)
        enable_kill_switch()
        return False


# =========================================================
# CURATED HUSTLE THOUGHT BANK - 42 UNIQUE THOUGHTS
# =========================================================
THOUGHT_BANK = {
    # GRIND & HUSTLE (7)
    "grind": [
        "While they sleep, I build.",
        "The grind doesn't care about your excuses.",
        "Late nights now. Private jets later.",
        "Work in silence. Let success make the noise.",
        "Your only competition is the person you were yesterday.",
        "Outwork everyone. Outlearn everyone. Outlast everyone.",
        "The hustle is lonely. So is the top. Get used to it.",
    ],
    # VENGEANCE & PROVE THEM WRONG (7)
    "vengeance": [
        "Let your success be the revenge they never saw coming.",
        "They laughed at my dreams. Now they watch me live them.",
        "Every rejection is just fuel for the fire.",
        "Doubt me. It only makes my victory sweeter.",
        "I remember every single person who counted me out.",
        "Use their disrespect as your motivation.",
        "The best revenge is massive success.",
    ],
    # DISCIPLINE & CONSISTENCY (7)
    "discipline": [
        "Motivation fades. Discipline stays.",
        "Champions are made when no one is watching.",
        "Show up even when you don't want to. Especially then.",
        "Consistency is more powerful than talent.",
        "Discipline is choosing between what you want now and what you want most.",
        "Suffer the pain of discipline or suffer the pain of regret.",
        "I don't count days. I make days count.",
    ],
    # MINDSET & MENTAL TOUGHNESS (7)
    "mindset": [
        "A lion doesn't lose sleep over the opinions of sheep.",
        "Your mind quits a thousand times before your body does.",
        "Weak thoughts create weak results.",
        "Think like a winner. Train like a winner. Become a winner.",
        "The only limits that exist are the ones you accept.",
        "Pressure either bursts pipes or creates diamonds.",
        "I didn't come this far to only come this far.",
    ],
    # SUCCESS & ACHIEVEMENT (7)
    "success": [
        "Success isn't given. It's earned.",
        "They don't want you to win. Win anyway.",
        "I'm not lucky. I'm relentless.",
        "The top is lonely, but the view is worth it.",
        "Build in silence. Arrive in violence.",
        "Results speak louder than intentions.",
        "Winners find ways. Losers find excuses.",
    ],
    # STRUGGLE & GROWTH THROUGH PAIN (7)
    "struggle": [
        "The pain you feel today is the strength you'll have tomorrow.",
        "Embrace the struggle. It's forging you into something unstoppable.",
        "Rock bottom became the solid foundation I built my empire on.",
        "Every setback is a setup for a comeback.",
        "I didn't come from money. I came from hunger.",
        "Hard times create strong people.",
        "The wound is where the light enters. Then the fire begins.",
    ],
}

# =========================================================
# RANDOMIZED PROMPT COMPONENTS (HIGH-QUALITY TEMPLATE)
# =========================================================

# SCENES (what we're looking at)
SCENES = [
    {
        "name": "city_skyline_night",
        "scene": "City skyline at night with lit office building windows",
        "details": "Single illuminated corner office, distant city lights, urban ambition"
    },
    {
        "name": "empty_gym_4am",
        "scene": "Empty industrial gym at 4 AM with harsh overhead lights",
        "details": "Heavy weights, worn floor, motivational posters, solitary dedication"
    },
    {
        "name": "late_night_desk",
        "scene": "Late-night desk setup with laptop glow and coffee cups",
        "details": "Multiple monitors, scattered notes, dim room, focused energy"
    },
    {
        "name": "rain_streets_dawn",
        "scene": "Rain-soaked city streets at dawn with neon reflections",
        "details": "Empty sidewalks, puddle reflections, early morning hustle"
    },
    {
        "name": "midnight_coffee_shop",
        "scene": "24-hour coffee shop at midnight with a lone figure working",
        "details": "Warm interior light, laptop open, coffee steam, urban solitude"
    },
    {
        "name": "construction_sunrise",
        "scene": "Construction site at sunrise with workers arriving",
        "details": "Steel beams, hard hats, orange sky, building something great"
    },
    {
        "name": "empty_boardroom",
        "scene": "Empty corporate boardroom at night with city view",
        "details": "Glass walls, leather chairs, city lights backdrop, ambition"
    },
    {
        "name": "mountain_peak_climb",
        "scene": "Person standing at mountain peak after grueling climb",
        "details": "Dramatic clouds below, harsh wind, victorious moment, earned view"
    },
]

# SEASONS + SKY
SEASONS = {
    "night_grind": [
        "Dark city sky with scattered artificial lights",
        "Deep midnight blue with distant skyscraper silhouettes",
    ],
    "storm_rising": [
        "Dramatic storm clouds gathering with lightning flashes",
        "Heavy gray clouds breaking with golden light piercing through",
    ],
    "pre_dawn": [
        "Cold pre-dawn sky transitioning from black to deep blue",
        "First light of day breaking over urban horizon",
    ],
    "harsh_winter": [
        "Cold stark winter sky with sharp contrast",
        "Steel gray overcast with biting cold atmosphere",
    ],
}

# LIGHTING OPTIONS
LIGHTING_OPTIONS = [
    "Harsh neon city lights casting stark shadows",
    "Single desk lamp cutting through darkness",
    "Dramatic storm-break light piercing through clouds",
    "Cold blue pre-dawn light with high contrast",
    "Industrial overhead fluorescent lighting",
]

# ATMOSPHERE + MOTION
ATMOSPHERE_OPTIONS = [
    "Rain streaking down city windows with neon reflections",
    "Steam rising from breath in cold morning air",
    "Industrial haze with electric tension in the atmosphere",
    "Urban dust catching harsh light beams",
    "Coffee steam rising in dark room with focused energy",
]

# MOOD OPTIONS
MOOD_OPTIONS = [
    "Intense, driven, relentless mood",
    "Hungry, determined, focused mood",
    "Vengeful, motivated, unstoppable mood",
    "Gritty, ambitious, powerful mood",
]

def generate_image_prompt(scene_data):
    """Generate a prompt using the specific Wojak/Doomer template."""
    # Build the master prompt - WOJAK DOOMER STYLE
    prompt = (
        f"A melancholic Wojak meme illustration, hand-drawn internet meme style. "
        f"A pale white Wojak character wearing a black beanie and dark hoodie, thin face with minimal expression, slightly tired eyes, cigarette in mouth with subtle smoke. "
        f"Side-facing portrait, shoulders visible. "
        f"Background shows {scene_data['scene']} with {scene_data['details']}, moody and cold atmosphere. "
        f"Flat colors, rough outlines, low-detail shading, classic Wojak / doomer aesthetic. "
        f"High contrast, centered composition, emotional loneliness vibe, meme-style digital illustration."
    )
    
    # Season/Time key - defaulting to 'night' as it fits the doomer vibe best
    return prompt, "doomer_night"

# Keep SCENE_PROMPTS for backwards compatibility (holiday posts use this format)
SCENE_PROMPTS = {scene["name"]: scene["scene"] for scene in SCENES}

# Seasonal Map: Month -> List of preferred thought categories
SEASONAL_MAP = {
    "01": ["mindset", "discipline"],   # New Year - fresh discipline
    "09": ["grind", "discipline"],     # Back to work season
    "12": ["success", "struggle"],     # Year-end reflection on wins
}

def choose_scene_and_text():
    # 1. Load history
    history = get_thought_cooldown_history()
    today_dt = datetime.now(pytz.timezone(TIMEZONE))
    
    # 2. Filter eligible thoughts (not on cooldown)
    all_eligible = []
    
    for category, thoughts in THOUGHT_BANK.items():
        for t in thoughts:
            last_used_str = history.get(t)
            if last_used_str:
                last_used_dt = datetime.strptime(last_used_str, "%Y-%m-%d").replace(tzinfo=pytz.timezone(TIMEZONE))
                days_diff = (today_dt - last_used_dt).days
                if days_diff < THOUGHT_COOLDOWN_DAYS:
                    continue  # Skip if used recently
            all_eligible.append((category, t))
    
    if not all_eligible:
        # Fallback if literally everything is on cooldown
        category = random.choice(list(THOUGHT_BANK.keys()))
        text = random.choice(THOUGHT_BANK[category])
        scene_data = random.choice(SCENES)
        return scene_data, text
    
    # 3. Compute available scenes (with cooldown check)
    scene_history = load_json_file(SCENE_HISTORY_FILE)
    recent_scenes = []
    for s, date_str in scene_history.items():
        try:
            used_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=pytz.timezone(TIMEZONE))
            if (today_dt - used_dt).days < SCENE_COOLDOWN_DAYS:
                recent_scenes.append(s)
        except:
            pass
    
    available_scenes = [s for s in SCENES if s["name"] not in recent_scenes]
    if not available_scenes:
        available_scenes = SCENES  # Fallback if all on cooldown
    
    # 4. Apply seasonal preference if applicable
    current_month = today_dt.strftime("%m")
    preferred_categories = SEASONAL_MAP.get(current_month, [])
    
    if preferred_categories:
        seasonal_eligible = [x for x in all_eligible if x[0] in preferred_categories]
        if seasonal_eligible:
            if DRY_RUN:
                print(f"Applying seasonal filter for month {current_month}: {preferred_categories}")
            category, text = random.choice(seasonal_eligible)
            scene_data = random.choice(available_scenes)
            return scene_data, text
    
    # 5. Pick random from full valid list
    category, text = random.choice(all_eligible)
    scene_data = random.choice(available_scenes)
    return scene_data, text

# =========================================================
# HOLIDAY POSTS — EXACT DATE ONLY
# =========================================================
HOLIDAY_POSTS = {
    (1, 1):  {"name": "new_year", "text": "New year. Same hunger. No days off.", "scene": "city skyline at dawn with lone figure watching from rooftop, new year sunrise"},
    (2, 14): {"name": "valentines", "text": "Fall in love with the grind. It will never let you down.", "scene": "late night desk with laptop and coffee, focused dedication, warm lamp light"},
    (3, 8):  {"name": "womens_day", "text": "Strong women don't wait for opportunities. They create them.", "scene": "woman in power suit walking through city at sunrise, confident stride"},
    (4, 1):  {"name": "april_fools", "text": "The biggest joke? Thinking you can outwork me.", "scene": "empty gym at 4am with heavy weights, single figure training"},
    (5, 1):  {"name": "labor_may", "text": "They call it work. I call it war.", "scene": "construction worker at dawn, steel and sweat, building something great"},
    (6, 1):  {"name": "pride", "text": "Be proud of how far you've come. Be hungry for how far you'll go.", "scene": "mountain peak view at sunset, victorious stance, clouds below"},
    (7, 4):  {"name": "independence", "text": "Financial freedom is the only independence worth fighting for.", "scene": "corner office at night, city lights below, empire builder"},
    (8, 4):  {"name": "friendship", "text": "Your circle should motivate you, not comfort your mediocrity.", "scene": "two figures training together at dawn, mutual respect and drive"},
    (9, 1):  {"name": "labor_sep", "text": "While they vacation, I execute.", "scene": "late night office, everyone gone home, one light still on"},
    (10, 31):{"name": "halloween", "text": "My demons? I put them to work.", "scene": "dark city street at night with lone figure walking purposefully, neon reflections"},
    (11, 28):{"name": "thanksgiving", "text": "Grateful for the struggle that made me dangerous.", "scene": "man looking out window at city dawn, reflection on the journey"},
    (12, 25):{"name": "christmas", "text": "The best gift you can give yourself is results.", "scene": "person working at desk on christmas eve, dedication, city lights outside"},
}

def load_holiday_history():
    if not os.path.exists(HOLIDAY_HISTORY_FILE):
        return {}
    with open(HOLIDAY_HISTORY_FILE) as f:
        return json.load(f)

def save_holiday_history(history):
    with open(HOLIDAY_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def get_today_holiday():
    today = date.today()
    key = (today.month, today.day)
    if key not in HOLIDAY_POSTS:
        return None

    history = load_holiday_history()
    year = str(today.year)
    used = history.get(year, [])

    holiday = HOLIDAY_POSTS[key]
    if holiday["name"] in used:
        return None

    return holiday

def mark_holiday_used(name):
    today = date.today()
    year = str(today.year)
    history = load_holiday_history()
    history.setdefault(year, []).append(name)
    save_holiday_history(history)

# =========================================================
# IMAGE GENERATION (CALLED ONLY IF POSTING)
# =========================================================
def generate_image_from_scene(prompt):
    """Generate image from a complete prompt string."""
    if DRY_RUN:
        print(f"[DRY RUN] Generating image for prompt ({len(prompt)} chars):")
        print(f"  {prompt[:150]}...")
        # Return a blank dummy image for testing flow
        img = Image.new("RGB", (1024, 1792), color=(50, 50, 50))
        out = BytesIO()
        img.save(out, "JPEG")
        out.seek(0)
        return out

    r = client.images.generate(
        model="gpt-image-1.5",
        prompt=prompt,
        size="1024x1536",
        n=1,
    )

    return BytesIO(base64.b64decode(r.data[0].b64_json))

# =========================================================
# IMAGE PROCESSING
# =========================================================
FONT_MAIN = "fonts/LibreBaskerville-Regular.ttf"
FONT_MARK = "fonts/LibreBaskerville-Regular.ttf"
WATERMARK_TEXT = "© HustleForge"

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

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # ---- TYPOGRAPHY SCALE (smaller, calmer) ----
    FONT_SIZE = 38 if len(text) <= 90 else 34
    LINE_HEIGHT = int(FONT_SIZE * 1.35)

    font = ImageFont.truetype(FONT_MAIN, FONT_SIZE)

    # ---- FIXED TEXT BOX (prevents drift) ----
    BOX_WIDTH = int(img.width * 0.70)
    BOX_HEIGHT = LINE_HEIGHT * 4
    BOX_X = (img.width - BOX_WIDTH) // 2

    # ---- SMART VERTICAL ZONES (Top Sky / Bottom Hoodie) ----
    # Avoid the middle (Face) entirely
    candidate_ys = [
        int(img.height * 0.10),  # High Sky
        int(img.height * 0.75),  # Low Body/Subtitle
    ]

    def zone_score(y):
        crop = img.crop((BOX_X, y, BOX_X + BOX_WIDTH, y + BOX_HEIGHT)).convert("L")
        stat = ImageStat.Stat(crop)
        return stat.stddev[0]  # Lowest variance = flattest area

    BOX_Y = min(candidate_ys, key=zone_score)


    # ---- STYLE SETTINGS (Highlight Mode) ----
    TEXT_COLOR = (255, 255, 255, 255)
    BG_COLOR = (0, 0, 0, 230)  # Much darker, almost opaque
    PAD_X = 20
    PAD_Y = 10

    # ---- LINE WRAPPING ----
    words = text.split()
    lines, current = [], ""

    for w in words:
        test = f"{current} {w}".strip()
        if draw.textlength(test, font=font) <= BOX_WIDTH:
            current = test
        else:
            lines.append(current)
            current = w
    lines.append(current)

    # ---- VERTICAL CENTERING INSIDE BOX ----
    y = BOX_Y + (BOX_HEIGHT - len(lines) * LINE_HEIGHT) // 2

    for line in lines:
        w = draw.textlength(line, font=font)
        x = (img.width - w) // 2
        
        # Calculate exact bounding box for the text
        bbox = draw.textbbox((x, y), line, font=font)
        # bbox is (left, top, right, bottom)
        
        # Draw background highlights
        draw.rectangle(
            (bbox[0] - PAD_X, bbox[1] - PAD_Y, bbox[2] + PAD_X, bbox[3] + PAD_Y),
            fill=BG_COLOR
        )

        # Draw Text
        draw.text((x, y), line, font=font, fill=TEXT_COLOR)

        y += LINE_HEIGHT

    # ---- WATERMARK (unchanged, quieter) ----
    mark_font = ImageFont.truetype(FONT_MAIN, 26)
    mw = draw.textlength(WATERMARK_TEXT, font=mark_font)
    draw.text(
        ((img.width - mw) // 2, img.height - 58),
        WATERMARK_TEXT,
        font=mark_font,
        fill=(255, 255, 255, 130),
    )

    final = Image.alpha_composite(img, overlay)
    out = BytesIO()
    final.convert("RGB").save(out, "JPEG", quality=95)
    out.seek(0)
    return out

# =========================================================
# FACEBOOK POST
# =========================================================
def post_to_facebook(image_buffer):
    if DRY_RUN:
        print("[DRY RUN] Skipping Facebook upload.")
        return

    url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos"
    data = {"access_token": FB_TOKEN, "published": "true"}
    files = {"source": ("image.jpg", image_buffer, "image/jpeg")}
    
    try:
        r = requests.post(url, data=data, files=files)
        if r.status_code != 200:
            raise Exception(f"FB Error {r.status_code}: {r.text}")
    except Exception as e:
        print(f"CRITICAL: Facebook Post Failed. Enabling Kill Switch. Error: {e}")
        enable_kill_switch()
        raise e

# =========================================================
# MAIN (STRICT ORDER — DO NOT CHANGE)
# =========================================================
if __name__ == "__main__":
    print(f"Starting Bot. Dry Run: {DRY_RUN}")

    # 1. Safety Checks
    # 1. Safety Checks
    if check_kill_switch() and not FORCE_POST:
        print("KILL SWITCH ACTIVE. Posting disabled. Exiting.")
        exit(0)
    
    # Validate fonts exist before making any API calls
    validate_fonts()
    
    # Token Health Check
    if not check_token_health():
        print("Token Health Check Failed.")
        if not FORCE_POST:
            print("Kill switch enabled. Exiting.")
            exit(1)
        else:
            print("FORCE_POST enabled. Ignoring health check failure.")

    if check_monthly_cap() and not DRY_RUN:
        print("MONTHLY CAP REACHED. Exiting.")
        exit(0)

    # 2. Time gate (skipped if FORCE_POST=true)
    if not is_good_posting_time() and not DRY_RUN and not FORCE_POST:
        print("Outside posting window. Skipping.")
        exit(0)

    # 3. Daily gate (skipped if FORCE_POST=true)
    if already_posted_today() and not DRY_RUN and not FORCE_POST:
        print("Already posted today. Skipping.")
        exit(0)

    # 4. Decide content (FREE)
    holiday = get_today_holiday()
    if holiday:
        text = holiday["text"]
        # For holidays, use the old-style direct prompt
        scene_prompt = (
            f"Dramatic photorealistic digital art, ultra high detail, 8K quality, cinematic photography style. "
            f"{holiday['scene']}, with a wide sense of depth and scale. "
            f"High contrast, deep shadows, bold colors, urban grit aesthetic. "
            f"Intense, driven, relentless mood, hustle culture atmosphere. "
            f"Magazine quality, sharp focus, dramatic composition, no text, no watermark."
        )
        is_holiday = True
        scene_name = "holiday_" + holiday["name"]
        print("HOLIDAY POST:", holiday["name"])
    else:
        scene_data, text = choose_scene_and_text()
        # Generate randomized prompt from scene data
        scene_prompt, season = generate_image_prompt(scene_data)
        scene_name = scene_data["name"]
        is_holiday = False
        print(f"REGULAR POST: {scene_name} ({season})")

    # 5. GENERATE & POST (COSTS MONEY)
    try:
        image_buffer = generate_image_from_scene(scene_prompt)
        final_image = add_text(image_buffer, text)
        post_to_facebook(final_image)

        # 6. Record state (Only on success)
        if not DRY_RUN:
            mark_posted_today()
            increment_monthly_cap()
            update_thought_history(text)
            # Track used scene to ensure variety
            scene_history = load_json_file(SCENE_HISTORY_FILE)
            scene_history[scene_name] = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d")
            save_json_file(SCENE_HISTORY_FILE, scene_history)
            if is_holiday:
                mark_holiday_used(holiday["name"])
            
            log_engagement(scene_name, text, "SUCCESS")
        else:
            log_engagement(scene_name, text, "DRY_RUN_SUCCESS")

        print("Post successful.")

    except Exception as e:
        print(f"Process failed: {e}")
        log_engagement(scene_name, text, f"FAILED: {e}")
        log_error(e)
        exit(1)




