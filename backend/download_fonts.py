import os
import requests
import zipfile
import io

fonts = [
    "Inter", "Manrope", "Rubik", "Oswald", "JetBrains Mono", "IBM Plex Sans"
]

out_dir = os.path.join(os.getcwd(), "fonts")
os.makedirs(out_dir, exist_ok=True)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Accept": "application/zip, text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
}

for font in fonts:
    family = font.replace(" ", "%20")
    url = f"https://fonts.google.com/download?family={family}"
    print(f"Downloading {font}...")
    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            try:
                with zipfile.ZipFile(io.BytesIO(res.content)) as z:
                    extracted = False
                    for font_weight in ["Bold", "Black", "ExtraBold", "Regular"]:
                        if extracted: break
                        found = [f for f in z.namelist() if f.endswith(".ttf") and font_weight in f and "static" in f]
                        if not found:
                            found = [f for f in z.namelist() if f.endswith(".ttf") and font_weight in f]
                        
                        if found:
                            file_to_extract = found[0]
                            filename = os.path.basename(file_to_extract)
                            with open(os.path.join(out_dir, filename), "wb") as f:
                                f.write(z.read(file_to_extract))
                            print(f" -> Extracted {filename}")
                            extracted = True
            except zipfile.BadZipFile:
                print(f" -> Failed: Response is not a valid ZIP file. Length: {len(res.content)}")
                with open(f"error_{font}.html", "wb") as f:
                    f.write(res.content)
        else:
            print(f"Failed to download {font}: HTTP {res.status_code}")
    except Exception as e:
        print(f"Error downloading {font}: {e}")
