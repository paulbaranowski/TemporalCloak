import sys
import requests
from temporal_cloak.decoding import TemporalCloakDecoding
from temporal_cloak.const import TemporalCloakConst
import humanize


def main():
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = 'http://localhost:8888/api/image'

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


if __name__ == '__main__':
    main()
