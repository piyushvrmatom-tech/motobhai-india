import urllib.request
import re

asins = {"1": "B07T29B12P", "5": "B0CQSXTJ3Y"}
for name, asin in asins.items():
    url = f"https://www.amazon.in/dp/{asin}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
    try:
        html = urllib.request.urlopen(req).read().decode('utf-8')
        match = re.search(r'"hiRes":"(https://m.media-amazon.com/images/I/[^"]+)"', html)
        if match:
            urllib.request.urlretrieve(match.group(1), f"public/img/store/{name}.jpg")
            print(f"Success {name}:", match.group(1))
        else:
            match = re.search(r'"large":"(https://m.media-amazon.com/images/I/[^"]+)"', html)
            if match:
                urllib.request.urlretrieve(match.group(1), f"public/img/store/{name}.jpg")
                print(f"Success (large) {name}:", match.group(1))
            else:
                print(f"No image found {name}")
    except Exception as e:
        print("Error:", e)
