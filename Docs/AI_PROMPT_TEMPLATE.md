# AI-Assisted Theme Creation Prompt Template

Use this template to generate custom themes for Pi-Health Dashboard using AI assistants (ChatGPT, Claude, etc.).

---

## How to Use This Template

1. Copy the prompt below
2. Replace `[THEME_DESCRIPTION]` with your theme idea
3. Paste into your AI assistant
4. Review and save the generated `theme.json`
5. Follow the instructions to complete your theme

---

## Prompt Template

```
I need help creating a custom theme for Pi-Health Dashboard. Please generate a complete theme.json file based on my description.

THEME DESCRIPTION: [THEME_DESCRIPTION]

Please create a theme.json file that includes:
1. A creative theme name (lowercase with hyphens)
2. A display name for the theme
3. An appropriate dashboard title
4. A cohesive color palette with hex codes
5. Tailwind CSS gradient classes that match the theme
6. Appropriate shadow effects
7. Status colors for container states

THEME STRUCTURE (use this exact JSON structure):

{
  "name": "theme-name-here",
  "display_name": "Theme Display Name",
  "title": "Dashboard Title Here",
  "description": "Brief description of the theme",
  "banner": {
    "filename": "banner.jpg",
    "alt_text": "Banner description"
  },
  "colors": {
    "primary": "#000000",
    "primary_light": "#000000",
    "primary_dark": "#000000",
    "accent": "#000000",
    "accent_light": "#000000",
    "background": "#000000",
    "background_secondary": "#000000",
    "text_primary": "#000000",
    "text_secondary": "#000000",
    "success": "#10b981",
    "warning": "#f59e0b",
    "error": "#ef4444",
    "info": "#3b82f6"
  },
  "gradients": {
    "header": "from-color-900 to-color-900",
    "button": "from-color-600 to-color-600 hover:from-color-700 hover:to-color-700",
    "card_options": [
      "from-color-800 to-color-900",
      "from-color-800 to-color-900",
      "from-color-800 to-color-900",
      "from-color-900 to-color-800",
      "from-color-900 to-color-900",
      "from-color-900 to-color-900"
    ]
  },
  "effects": {
    "card_glow": "0 0 20px rgba(R, G, B, 0.3)",
    "card_hover_glow": "0 0 30px rgba(R, G, B, 0.5)",
    "text_shadow": "2px 2px 4px rgba(0, 0, 0, 0.5)"
  },
  "status_colors": {
    "running": "#10b981",
    "exited": "#ef4444",
    "paused": "#f59e0b",
    "restarting": "#3b82f6",
    "created": "#6366f1",
    "removing": "#f97316",
    "dead": "#991b1b"
  }
}

REQUIREMENTS:
- Use very dark backgrounds (#0f1827 or similar) for better readability
- Ensure text colors have good contrast with backgrounds
- Gradients should use Tailwind CSS color classes (e.g., from-blue-900 to-purple-900)
- Keep the theme cohesive - all colors should work well together
- Status colors should remain distinct and visible

Also provide:
1. Suggestions for banner images (specific search terms, movie scenes, or image sources)
2. The complete file creation commands
3. Any additional styling recommendations

Please provide the complete theme.json content that I can copy and save directly.
```

---

## Example Prompts

### Example 1: Movie/Character Theme

```
THEME DESCRIPTION:
Create a theme based on the movie "The Matrix" with dark green code aesthetics,
black backgrounds, and neon green accents. Title should be "Neo's Dashboard".
```

### Example 2: Color-Based Theme

```
THEME DESCRIPTION:
Create a vibrant sunset theme with oranges, pinks, and purples. It should feel
warm and energetic. Title should be "Sunset Server Dashboard".
```

### Example 3: Minimalist Theme

```
THEME DESCRIPTION:
Create a minimal monochrome theme using only black, white, and shades of gray.
Professional and clean. Title should be "Minimal System Monitor".
```

### Example 4: Gaming Theme

```
THEME DESCRIPTION:
Create a cyberpunk theme inspired by games like Cyberpunk 2077, with neon pink/
cyan colors, dark backgrounds, and futuristic feel. Title should be "Cyber Ops
Dashboard".
```

### Example 5: Nature Theme

```
THEME DESCRIPTION:
Create an ocean theme with deep blues and teals, inspired by underwater scenes.
Calming and peaceful. Title should be "Deep Blue Dashboard".
```

---

## After Generation

Once the AI generates your theme, follow these steps:

### Step 1: Create Theme Folder

```bash
cd /path/to/pi-health
mkdir themes/your-theme-name
```

### Step 2: Save theme.json

Save the AI-generated JSON to `themes/your-theme-name/theme.json`

### Step 3: Add Banner Image

1. Find or create a banner image based on AI suggestions
2. Resize to 1920x400px (recommended)
3. Save as `themes/your-theme-name/banner.jpg`

**Quick resize with ImageMagick:**
```bash
convert your-image.jpg -resize 1920x400^ -gravity center -extent 1920x400 themes/your-theme-name/banner.jpg
```

### Step 4: Create README (Optional)

```bash
cat > themes/your-theme-name/README.md << 'EOF'
# Your Theme Name

Description of your theme.

## Colors
- Primary: #hexcode
- Accent: #hexcode

## Banner
Description of banner image and source.

## Credits
Any resources or inspiration used.
EOF
```

### Step 5: Activate Theme

Edit `docker-compose.yml`:
```yaml
environment:
  - THEME=your-theme-name
```

Restart:
```bash
docker compose down && docker compose up -d
```

---

## Advanced: Iterating on Themes

If you want to refine your theme, use this follow-up prompt:

```
The theme looks good, but I'd like to adjust it. Please modify the theme.json with these changes:
[Describe specific changes - e.g., "make the primary color slightly lighter",
"change the accent to a warmer tone", "adjust gradients to be more subtle"]

Keep all other aspects the same.
```

---

## Banner Image Resources

### Free Stock Photo Sites
- [Unsplash](https://unsplash.com/) - High-quality free photos
- [Pexels](https://www.pexels.com/) - Free stock photos and videos
- [Pixabay](https://pixabay.com/) - Free images and videos

### Search Terms by Theme Type

**Movie/Character Themes:**
- "[Movie Name] wallpaper 1920x1080"
- "[Character Name] banner"
- "[Movie Name] promotional art"

**Abstract/Professional:**
- "dark technology background"
- "circuit board texture"
- "abstract data visualization"
- "minimal geometric pattern"

**Nature Themes:**
- "ocean underwater scene"
- "forest path aerial view"
- "mountain landscape sunset"
- "northern lights panorama"

**Gaming/Cyberpunk:**
- "cyberpunk cityscape"
- "neon lights urban"
- "futuristic technology"
- "synthwave background"

### AI Image Generation

You can also use AI image generators:
- [DALL-E](https://openai.com/dall-e-2)
- [Midjourney](https://www.midjourney.com/)
- [Stable Diffusion](https://stability.ai/)

**Example prompt for banner generation:**
```
A wide panoramic banner image (16:4 aspect ratio) for a dashboard interface,
featuring [your theme description]. Dark atmospheric lighting, high contrast,
suitable for background use with text overlay.
```

---

## Troubleshooting

**Theme not loading?**
- Check theme folder name matches THEME environment variable
- Verify theme.json is valid JSON (use JSONLint.com)
- Check Docker container logs: `docker logs pi-health-dashboard`

**Colors look wrong?**
- Ensure hex codes include # prefix
- Use 6-digit hex codes (#RRGGBB format)
- Check that gradients use valid Tailwind CSS classes

**Banner not showing?**
- Verify banner file exists and is named correctly
- Check banner.filename in theme.json matches actual filename
- Ensure banner file size is reasonable (<1MB recommended)

---

## Sharing Your Theme

Created an awesome theme? Consider sharing it:

1. Create a GitHub Gist or repository with:
   - `theme.json`
   - `README.md` with screenshots
   - Banner image (if redistributable)

2. Share in the Pi-Health community (if one exists)

3. Include:
   - Theme description
   - Screenshots of the theme in action
   - Banner image source/credits
   - Installation instructions

---

## Theme Gallery Ideas

Some theme ideas to inspire you:

- **Seasonal**: Spring Bloom, Summer Sunset, Autumn Leaves, Winter Frost
- **Movies**: Star Wars, Tron, Blade Runner, Avatar
- **Games**: Zelda, Halo, Portal, Minecraft
- **Nature**: Ocean Depths, Forest Canopy, Desert Dunes, Arctic Frost
- **Colors**: Ruby Red, Emerald Green, Sapphire Blue, Amethyst Purple
- **Retro**: Synthwave, Vaporwave, 80s Arcade, Terminal Green
- **Professional**: Corporate Blue, Executive Gray, Finance Green, Medical Clean
- **Holidays**: Halloween, Christmas, Easter, Fourth of July

Have fun creating! 🎨
