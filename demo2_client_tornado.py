import requests
from TemporalCloakDecoding import TemporalCloakDecoding
from TemporalCloakConst import TemporalCloakConst
import humanize

url = 'http://localhost:8888'

# Stream the response in chunks of 1024 bytes
print("Getting {}...".format(url))
response = requests.get(url, stream=True)
print("Got response")
print(response.headers)
cloak = TemporalCloakDecoding(debug=True)
total_bytes = 0
first_chunk = True
for chunk in response.iter_content(chunk_size=TemporalCloakConst.CHUNK_SIZE_TORNADO):
    if chunk:
        total_bytes += len(chunk)
        if first_chunk:
            # Discard the sync chunk and start timing baseline
            cloak.start_timer()
            first_chunk = False
        elif not cloak.completed:
            cloak.mark_time()
print("Total bytes received: {}".format(str(total_bytes)))
print("Total bytes received: {}".format(humanize.naturalsize(total_bytes, True, False, "%.2f")))
