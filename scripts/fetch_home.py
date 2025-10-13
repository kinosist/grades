import urllib.request
r = urllib.request.urlopen('http://127.0.0.1:8000/')
print('status', r.getcode())
print(r.read(2000).decode('utf-8', errors='replace'))
