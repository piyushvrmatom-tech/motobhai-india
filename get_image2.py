import urllib.request
import re

url = "https://duckduckgo.com/html/?q=TVS+Disc+Lock+images"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    html = urllib.request.urlopen(req).read().decode('utf-8')
    match = re.search(r'img src="([^"]+)"', html)
    if match:
        img_url = match.group(1)
        if img_url.startswith('//'):
            img_url = 'https:' + img_url
        urllib.request.urlretrieve(img_url, "public/img/store/1.jpg")
        print("Success 1: " + img_url)
    else:
        print("No image found 1")
except Exception as e:
    print("Error:", e)
