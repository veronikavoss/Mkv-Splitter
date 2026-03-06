import os

assets_dir = os.path.join(os.path.dirname(__file__), "assets")
os.makedirs(assets_dir, exist_ok=True)

up_svg = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
<rect width="24" height="24" rx="4" fill="#1E1E1E" stroke="#333" stroke-width="1"/>
<path d="M12 7L6 14H18L12 7Z" fill="#D4AF37"/>
</svg>"""

up_hover_svg = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
<rect width="24" height="24" rx="4" fill="#2C2C2C" stroke="#444" stroke-width="1"/>
<path d="M12 7L6 14H18L12 7Z" fill="#F3D360"/>
</svg>"""

up_disabled_svg = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
<rect width="24" height="24" rx="4" fill="#1A1A1A" stroke="#222" stroke-width="1"/>
<path d="M12 7L6 14H18L12 7Z" fill="#555555"/>
</svg>"""

down_svg = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
<rect width="24" height="24" rx="4" fill="#1E1E1E" stroke="#333" stroke-width="1"/>
<path d="M12 17L18 10H6L12 17Z" fill="#D4AF37"/>
</svg>"""

down_hover_svg = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
<rect width="24" height="24" rx="4" fill="#2C2C2C" stroke="#444" stroke-width="1"/>
<path d="M12 17L18 10H6L12 17Z" fill="#F3D360"/>
</svg>"""

down_disabled_svg = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
<rect width="24" height="24" rx="4" fill="#1A1A1A" stroke="#222" stroke-width="1"/>
<path d="M12 17L18 10H6L12 17Z" fill="#555555"/>
</svg>"""

delete_svg = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
<rect width="24" height="24" rx="4" fill="#2C1616" stroke="#4A2020" stroke-width="1"/>
<path d="M16 8L8 16M8 8L16 16" stroke="#FF4C4C" stroke-width="2" stroke-linecap="round"/>
</svg>"""

delete_hover_svg = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
<rect width="24" height="24" rx="4" fill="#3D1A1A" stroke="#5C2525" stroke-width="1"/>
<path d="M16 8L8 16M8 8L16 16" stroke="#FF7B7B" stroke-width="2" stroke-linecap="round"/>
</svg>"""

files = {
    "list_up.svg": up_svg,
    "list_up_hover.svg": up_hover_svg,
    "list_up_disabled.svg": up_disabled_svg,
    "list_down.svg": down_svg,
    "list_down_hover.svg": down_hover_svg,
    "list_down_disabled.svg": down_disabled_svg,
    "list_delete.svg": delete_svg,
    "list_delete_hover.svg": delete_hover_svg,
}

for filename, content in files.items():
    path = os.path.join(assets_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
print("Assets created in", assets_dir)
