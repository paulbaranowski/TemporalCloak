import requests
from BitCloakDecoding import BitCloakDecoding
url = 'http://localhost:8888'

# Stream the response in chunks of 1024 bytes
print("Getting {}...".format(url))
response = requests.get(url, stream=True)
print("Got response")
print(response.headers)
cloak = BitCloakDecoding(debug=True)
cloak.start_timer()
total_bytes = 0
CHUNK_SIZE=100
for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
    total_bytes += CHUNK_SIZE
    if chunk:
        # Process the chunk of data
        if not cloak.completed:
            cloak.mark_time()
        # print(len(chunk))
print("Total bytes received: {}".format(str(total_bytes)))