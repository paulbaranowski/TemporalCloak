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
cloak.start_timer()
total_bytes = 0
for chunk in response.iter_content(chunk_size=TemporalCloakConst.CHUNK_SIZE_TORNADO):
    total_bytes += TemporalCloakConst.CHUNK_SIZE_TORNADO
    if chunk:
        # Process the chunk of data
        if not cloak.completed:
            cloak.mark_time()
        # print(len(chunk))
print("Total bytes received: {}".format(str(total_bytes)))
print("Total bytes received: {}".format(humanize.naturalsize(total_bytes, True, False, "%.2f")))
