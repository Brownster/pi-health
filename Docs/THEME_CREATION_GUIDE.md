# Pi-Health Dashboard - Theme Creation Guide

This guide explains how to create custom themes for your Pi-Health Dashboard.

## Table of Contents

1. [What Are Themes?](#what-are-themes)
2. [Theme Structure](#theme-structure)
3. [Creating a New Theme](#creating-a-new-theme)
4. [Theme Configuration (theme.json)](#theme-configuration-themejson)
5. [Banner Image Requirements](#banner-image-requirements)
6. [Installing and Activating Your Theme](#installing-and-activating-your-theme)
7. [Examples](#examples)
8. [Tips and Best Practices](#tips-and-best-practices)

---

## What Are Themes?

Themes allow you to personalize the look and feel of your Pi-Health Dashboard by customizing:
- Color schemes (primary colors, accents, backgrounds, text colors)
- Banner images
- Dashboard title
- Gradients and visual effects
- Container status colors

Each theme is self-contained in its own folder, making it easy to create, share, and switch between different themes.

---

## Theme Structure

Each theme consists of a folder inside the `themes/` directory with the following structure:

```
themes/
└── your-theme-name/
    ├── theme.json       # Theme configuration (required)
    ├── banner.jpg       # Banner image (required)
    └── README.md        # Optional documentation
```

### Example: Existing Themes

```
themes/
├── coraline/
│   ├── theme.json
│   ├── banner.jpg
│   └── README.md
├── professional/
│   ├── theme.json
│   └── README.md
└── arthur-christmas/
    ├── theme.json
    └── README.md
```

---

## Creating a New Theme

### Step 1: Create Theme Folder

Create a new folder inside the `themes/` directory with your theme name (use lowercase, hyphens for spaces):

```bash
mkdir themes/my-custom-theme
```

### Step 2: Create theme.json

Create a `theme.json` file in your theme folder. Use the template below as a starting point.

### Step 3: Add Banner Image

Add your banner image to the theme folder. Name it `banner.jpg` (or update the filename in `theme.json`).

### Step 4: Test Your Theme

Update the `THEME` environment variable in `docker-compose.yml` and restart the container:

```yaml
environment:
  - THEME=my-custom-theme
```

---

## Theme Configuration (theme.json)

The `theme.json` file defines all visual aspects of your theme. Here's the complete structure:

```json
{
  "name": "my-theme",
  "display_name": "My Custom Theme",
  "title": "My Pi-Health Dashboard",
  "description": "A custom theme for my Pi server",
  "banner": {
    "filename": "banner.jpg",
    "alt_text": "My Banner"
  },
  "colors": {
    "primary": "#5f4b8b",
    "primary_light": "#6f58a3",
    "primary_dark": "#372b53",
    "accent": "#8a6cbd",
    "accent_light": "#c9b6e6",
    "background": "#111827",
    "background_secondary": "#1f2937",
    "text_primary": "#dbeafe",
    "text_secondary": "#93c5fd",
    "success": "#10b981",
    "warning": "#f59e0b",
    "error": "#ef4444",
    "info": "#3b82f6"
  },
  "gradients": {
    "header": "from-purple-900 to-blue-900",
    "button": "from-purple-600 to-indigo-600 hover:from-purple-700 hover:to-indigo-700",
    "card_options": [
      "from-purple-800 to-indigo-900",
      "from-indigo-800 to-purple-900",
      "from-blue-800 to-purple-900",
      "from-purple-900 to-blue-800",
      "from-indigo-900 to-blue-900",
      "from-blue-900 to-indigo-900"
    ]
  },
  "effects": {
    "card_glow": "0 0 20px rgba(139, 92, 246, 0.3)",
    "card_hover_glow": "0 0 30px rgba(139, 92, 246, 0.5)",
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
```

### Field Descriptions

#### Basic Information
- **name**: Internal theme identifier (must match folder name)
- **display_name**: Human-readable theme name
- **title**: Dashboard title shown on all pages
- **description**: Brief description of the theme

#### Banner
- **filename**: Banner image filename (e.g., "banner.jpg")
- **alt_text**: Alternative text for the banner image

#### Colors
All colors use hex format (#RRGGBB):
- **primary**: Main theme color (used for buttons, borders, icons)
- **primary_light**: Lighter variant for hover states
- **primary_dark**: Darker variant for gradients
- **accent**: Secondary color for highlights
- **accent_light**: Light accent for icon details
- **background**: Main page background
- **background_secondary**: Secondary background (cards, panels)
- **text_primary**: Main text color
- **text_secondary**: Secondary text color
- **success/warning/error/info**: Status indicator colors

#### Gradients
Uses Tailwind CSS gradient classes:
- **header**: Header background gradient
- **button**: Button gradient and hover state
- **card_options**: Array of gradients for service cards (rotates based on service name)

#### Effects
CSS shadow and text effects:
- **card_glow**: Box shadow for cards
- **card_hover_glow**: Enhanced shadow on hover
- **text_shadow**: Text shadow for titles

#### Status Colors
Container status indicator colors (hex format).

---

## Banner Image Requirements

### Specifications

- **Format**: JPG or PNG (JPG recommended for smaller file size)
- **Dimensions**: 1920x400px (recommended) or similar wide aspect ratio (16:4)
- **File Size**: Keep under 500KB for faster loading
- **Filename**: `banner.jpg` by default (can customize in theme.json)

### Design Tips

1. **Avoid busy images**: The banner is displayed with blur and low opacity
2. **Horizontal composition**: Wide images work best
3. **High contrast**: Ensure the image works well when blurred
4. **Theme-appropriate**: Choose imagery that matches your theme's purpose

### Example Sources

- Movie stills or promotional art (for character themes like Coraline, Arthur Christmas)
- Abstract patterns, circuits, or tech imagery (for professional themes)
- Personal photos or artwork
- Free stock photo sites (Unsplash, Pexels, Pixabay)

---

## Installing and Activating Your Theme

### Method 1: Manual Installation

1. Create your theme folder in `themes/`
2. Add `theme.json` and banner image
3. Edit `docker-compose.yml`:
   ```yaml
   environment:
     - THEME=your-theme-name
   ```
4. Restart the container:
   ```bash
   docker compose down
   docker compose up -d
   ```

### Method 2: Environment Variable

Set the `THEME` environment variable when running the container:

```bash
docker run -e THEME=your-theme-name pi-health-dashboard
```

### Default Theme

If no `THEME` environment variable is set, the dashboard defaults to the `coraline` theme.

---

## Examples

### Example 1: Dark Blue Professional Theme

```json
{
  "name": "corporate-blue",
  "display_name": "Corporate Blue",
  "title": "System Dashboard",
  "colors": {
    "primary": "#1e40af",
    "primary_light": "#3b82f6",
    "primary_dark": "#1e3a8a",
    "accent": "#0ea5e9",
    "accent_light": "#38bdf8",
    "background": "#0f172a",
    "background_secondary": "#1e293b",
    "text_primary": "#f1f5f9",
    "text_secondary": "#cbd5e1"
  },
  "gradients": {
    "header": "from-slate-900 to-blue-900",
    "button": "from-blue-600 to-blue-700 hover:from-blue-700 hover:to-blue-800",
    "card_options": [
      "from-slate-800 to-blue-900",
      "from-blue-800 to-slate-900"
    ]
  }
}
```

### Example 2: Green Nature Theme

```json
{
  "name": "forest",
  "display_name": "Forest Theme",
  "title": "Nature's Dashboard",
  "colors": {
    "primary": "#16a34a",
    "primary_light": "#22c55e",
    "primary_dark": "#166534",
    "accent": "#84cc16",
    "accent_light": "#a3e635",
    "background": "#0f1810",
    "background_secondary": "#1c2e1f",
    "text_primary": "#dcfce7",
    "text_secondary": "#86efac"
  }
}
```

---

## Tips and Best Practices

### Color Selection

1. **Use a color palette generator**: Tools like [Coolors.co](https://coolors.co/) or [Adobe Color](https://color.adobe.com/)
2. **Check contrast**: Ensure text is readable on backgrounds
3. **Consistent scheme**: Choose 2-3 main colors and stick to them
4. **Dark backgrounds**: Use very dark colors (#0f1827) for better readability

### Gradients

- Use Tailwind CSS gradient classes (e.g., `from-blue-900 to-purple-900`)
- Keep gradients subtle for professional look
- Test gradients on both light and dark content

### Banner Images

- **Licensing**: Ensure you have rights to use the image
- **Optimization**: Compress images before adding them (use TinyPNG, ImageOptim)
- **Backup**: Keep original high-res versions of your banners

### Testing

1. Test theme on different screen sizes (mobile, tablet, desktop)
2. Check all pages (Home, System Health, Containers, Edit Config, Login)
3. Verify container cards have good contrast with gradients
4. Ensure status colors are distinct and readable

### Sharing Themes

If you create a great theme and want to share it:
1. Create a README.md in your theme folder
2. Include screenshots
3. Credit any resources used (images, inspiration)
4. Share the theme folder as a zip or on GitHub

---

## Need Help?

- Check existing themes in `themes/` for reference
- Review `static/theme.js` to see how themes are applied
- Use the AI Prompt Template (see `AI_PROMPT_TEMPLATE.md`) to generate themes with AI assistance

---

## Theme Versioning

**Current Theme Schema Version**: 1.0

If the theme system is updated in the future, we'll maintain backward compatibility or provide migration guides.
