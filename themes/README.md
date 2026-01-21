# Pi-Health Dashboard Themes

This folder contains all available themes for the Pi-Health Dashboard.

## Available Themes

### 1. Coraline (Default)
- **Style**: Dark purple with button-eyed icons
- **Colors**: Purple (#5f4b8b), Light Purple, Blues
- **Icons**: Circular button-eyed style inspired by the Coraline movie
- **Status**: ✅ Complete (banner included)

### 2. Professional
- **Style**: Clean corporate blue theme
- **Colors**: Blue (#2563eb), Cyan accents, Dark slate backgrounds
- **Icons**: Minimal rectangular design with clean lines
- **Status**: ⚠️ Needs banner image

### 3. Arthur Christmas
- **Style**: Festive holiday theme
- **Colors**: Red (#dc2626), Green (#16a34a), Gold accents
- **Icons**: Christmas-themed with ornaments, stars, and festive elements
- **Status**: ⚠️ Needs banner image

## Theme Structure

Each theme folder contains:
```
theme-name/
├── theme.json      # Theme configuration (colors, gradients, effects)
├── icons.js        # Custom SVG icons for the theme
├── banner.jpg      # Banner image (1920x400px recommended)
└── README.md       # Theme documentation
```

## Icon Styles

Each theme has its own unique icon style:

### Coraline Icons
- **Design**: Circular backgrounds with button-like appearance
- **Colors**: Purple fills, light purple strokes
- **Style**: Whimsical, inspired by the movie's button-eyed aesthetic

### Professional Icons
- **Design**: Rounded rectangles with semi-transparent fills
- **Colors**: Blue borders, light blue content
- **Style**: Clean, minimal, corporate-friendly

### Arthur Christmas Icons
- **Design**: Circular with ornament-like appearance
- **Colors**: Red/green fills, gold accents, stars and festive details
- **Style**: Holiday-themed, warm and cheerful

## Adding a New Theme

1. Create a new folder: `themes/your-theme-name/`
2. Create `theme.json` (see Docs/THEME_CREATION_GUIDE.md)
3. Create `icons.js` with your custom icon set
4. Add `banner.jpg` (1920x400px recommended)
5. Update `docker-compose.yml`: `THEME=your-theme-name`
6. Restart the container

## Icon System

### How Icons Work

Icons are loaded dynamically based on the active theme:
1. Theme loads from `theme.json`
2. If `icons.file` is specified, load that JavaScript file
3. Icons are exported as `window.ThemeIcons`
4. Index page uses theme icons, falling back to defaults if unavailable

### Creating Custom Icons

Your `icons.js` file should export icons like this:

```javascript
const iconSVGs = {
    transfer: '<svg>...</svg>',
    search: '<svg>...</svg>',
    tv: '<svg>...</svg>',
    film: '<svg>...</svg>',
    download: '<svg>...</svg>',
    collection: '<svg>...</svg>',
    play: '<svg>...</svg>',
    'cloud-download': '<svg>...</svg>',
    music: '<svg>...</svg>',
    book: '<svg>...</svg>',
    default: '<svg>...</svg>'
};

window.ThemeIcons = iconSVGs;
```

### Icon Types

The following icon types are used:
- **transfer**: Up/down arrows (e.g., Transmission)
- **search**: Magnifying glass (e.g., Jackett)
- **tv**: Television (e.g., Sonarr)
- **film**: Film reel (e.g., Radarr)
- **download**: Download arrow (e.g., NZBGet)
- **collection**: Stacked boxes (e.g., Jellyfin)
- **play**: Play button (e.g., Get iPlayer)
- **cloud-download**: Cloud with arrow (e.g., RDT Client)
- **music**: Musical notes (e.g., Lidarr, Airsonic)
- **book**: Open book (e.g., Audiobookshelf)
- **default**: Generic server icon

## Switching Themes

Edit `docker-compose.yml`:
```yaml
environment:
  - THEME=coraline           # or 'professional', 'arthur-christmas'
```

Then restart:
```bash
docker compose down && docker compose up -d
```

## Tips for Creating Icons

1. **Consistent size**: Use `viewBox="0 0 24 24"` for all icons
2. **Unique style**: Make your icons visually distinct for your theme
3. **Good contrast**: Ensure icons are visible on gradient backgrounds
4. **Theme colors**: Use colors from your theme.json
5. **Test visibility**: Check icons against all gradient options

## Need Help?

- See `Docs/THEME_CREATION_GUIDE.md` for detailed theme creation instructions
- See `Docs/AI_PROMPT_TEMPLATE.md` for AI-assisted theme generation
- Check existing themes for reference examples
