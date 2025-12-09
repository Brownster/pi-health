# Arthur Christmas Theme

Festive theme inspired by Arthur Christmas with warm reds, greens, and gold accents.

## Required Assets

### banner.jpg
Place your banner image in this directory as `banner.jpg`.

**Recommended specifications:**
- **Dimensions**: 1920x400px (or similar wide aspect ratio)
- **Format**: JPG or PNG
- **Style**: Arthur Christmas movie imagery, festive winter scenes, Christmas elements
- **Color palette**: Reds, greens, golds, warm tones to match the theme

**Finding Banner Images:**

1. **Arthur Christmas Movie Stills**
   - Search Google Images: "Arthur Christmas wallpaper 1920x1080"
   - Look for wide scenes from the movie
   - Character promotional art

2. **Holiday Stock Photos** (if movie images aren't available)
   - [Unsplash](https://unsplash.com/s/photos/christmas): "christmas decorations", "santa workshop"
   - [Pexels](https://www.pexels.com/search/christmas/): "holiday lights", "winter festive"
   - Search terms: "christmas banner", "holiday scene", "festive decorations"

3. **AI Image Generation**
   - DALL-E, Midjourney, or Stable Diffusion
   - Prompt: "Wide panoramic Christmas scene with Santa's workshop, festive decorations, warm lights, Arthur Christmas movie style, 16:4 aspect ratio"

**Quick resize command:**
```bash
convert your-image.jpg -resize 1920x400^ -gravity center -extent 1920x400 banner.jpg
```

## Theme Features

### Colors
- Primary: Red (#dc2626)
- Accent: Green (#16a34a)
- Background: Dark charcoal (#0f1419)
- Text: Warm gold/yellow (#fef3c7)

### Icons
Festive holiday-themed icons featuring:
- Ornament-style circular backgrounds
- Christmas stars and decorative elements
- Red, green, and gold color scheme
- Warm, cheerful aesthetic

## Customization

Edit `theme.json` to modify colors, gradients, and other theme properties.

Edit `icons.js` to customize the icon designs (change star placements, ornament colors, etc.).
