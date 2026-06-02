import urllib.request
import re

url = "https://duckduckgo.com/html/?q=Wurth+helmet+visor+cleaner+150ml+images"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    html = urllib.request.urlopen(req).read().decode('utf-8')
    match = re.search(r'img src="([^"]+)"', html)
    if match:
        img_url = match.group(1)
        if img_url.startswith('//'):
            img_url = 'https:' + img_url
        urllib.request.urlretrieve(img_url, "public/img/store/5.jpg")
        print("Success: " + img_url)
    else:
        print("No image found")
except Exception as e:
    print("Error:", e)
