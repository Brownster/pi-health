#!/usr/bin/env python3
"""
Quick theme tester - runs Flask app on port 8081 for testing
Usage: THEME=arthur-christmas python3 test_theme.py
"""
import os
from app import app

if __name__ == '__main__':
    theme = os.getenv('THEME', 'coraline')
    port = 8081
    print(f"\n{'='*60}")
    print(f"  Testing Pi-Health with theme: {theme}")
    print(f"  Server running at: http://localhost:{port}")
    print(f"  Press Ctrl+C to stop")
    print(f"{'='*60}\n")

    app.run(host="0.0.0.0", port=port, debug=True)
