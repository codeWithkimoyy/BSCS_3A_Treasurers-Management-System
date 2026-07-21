import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import urllib.request, http.cookiejar, urllib.parse

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

# Login
data = urllib.parse.urlencode({'username': 'admin', 'password': 'admin123'}).encode()
opener.open('http://localhost:5000/login', data=data)

# Get dashboard
r = opener.open('http://localhost:5000/')
html = r.read().decode()

# Find the important section
if 'Recent Payments' in html:
    print("GOT IT - Recent Payments section present!")
    # Count payment rows
    count = html.count('<tr>')
    print(f"Table rows: {count}")
    # Check for student names
    for name in ['ILAGA', 'RIZA JANE', 'CUTAMORA', 'KIM C']:
        if name in html:
            print(f"  Found: {name}")
else:
    print("NOT FOUND - Recent Payments section MISSING")
    # What's near the end of the file?
    print(html[-500:])
