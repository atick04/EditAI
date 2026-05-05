import os
import requests

out_dir = os.path.join(os.getcwd(), "fonts")
os.makedirs(out_dir, exist_ok=True)

# Direct CDN URLs from jsDelivr (fontsource) - no API key needed
FONTS = {
    "Inter_24pt-Bold.ttf":       "https://cdn.jsdelivr.net/npm/@fontsource/inter@5.0.8/files/inter-latin-700-normal.woff2",
    "Manrope-Bold.ttf":          "https://cdn.jsdelivr.net/npm/@fontsource/manrope@5.0.8/files/manrope-latin-700-normal.woff2",
    "Rubik-Bold.ttf":            "https://cdn.jsdelivr.net/npm/@fontsource/rubik@5.0.8/files/rubik-latin-700-normal.woff2",
    "Oswald-Bold.ttf":           "https://cdn.jsdelivr.net/npm/@fontsource/oswald@5.0.8/files/oswald-latin-700-normal.woff2",
    "Montserrat-ExtraBold.ttf":  "https://cdn.jsdelivr.net/npm/@fontsource/montserrat@5.0.8/files/montserrat-latin-800-normal.woff2",
    "Comfortaa-Bold.ttf":        "https://cdn.jsdelivr.net/npm/@fontsource/comfortaa@5.0.8/files/comfortaa-latin-700-normal.woff2",
    "Lobster-Regular.ttf":       "https://cdn.jsdelivr.net/npm/@fontsource/lobster@5.0.8/files/lobster-latin-400-normal.woff2",
    "JetBrainsMono-Bold.ttf":    "https://cdn.jsdelivr.net/npm/@fontsource/jetbrains-mono@5.0.8/files/jetbrains-mono-latin-700-normal.woff2",
    "IBMPlexSans-Bold.ttf":      "https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-sans@5.0.8/files/ibm-plex-sans-latin-700-normal.woff2",
    "BebasNeue-Regular.ttf":     "https://cdn.jsdelivr.net/npm/@fontsource/bebas-neue@5.0.8/files/bebas-neue-latin-400-normal.woff2",
}

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

print(f"Saving fonts to: {out_dir}\n")
for filename, url in FONTS.items():
    dest = os.path.join(out_dir, filename)
    if os.path.exists(dest):
        print(f"  OK {filename} already exists")
        continue
    print(f"  Downloading {filename} ...")
    try:
        res = requests.get(url, headers=headers, timeout=30)
        if res.status_code == 200 and len(res.content) > 1000:
            with open(dest, "wb") as f:
                f.write(res.content)
            print(f"    -> OK ({len(res.content)//1024}KB)")
        else:
            print(f"    -> FAILED HTTP {res.status_code}, size={len(res.content)}")
    except Exception as e:
        print(f"    -> ERROR: {e}")

print("\nDone!")
