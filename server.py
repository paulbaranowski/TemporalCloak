import socket
import time
from common import *
from bitstring import BitArray, BitStream, Bits

# Define the server address and port
SERVER_ADDRESS = ('localhost', 1234)


def receive_byte_with_time(sock, last_recv_time):
    try:
        # Receive the byte from the socket
        data = sock.recv(1)
        if not data:
            print("no data received")
            return None, None

        # Get the current time
        current_time = time.monotonic()
        # Calculate the time difference between the current and last received byte
        time_diff = current_time - last_recv_time
        # Return the byte and time difference
        return time_diff, current_time
    except (OSError, ConnectionResetError, ConnectionAbortedError) as e:
        # Handle case where socket is no longer connected
        print("Socket error:", e)
        return None, None


def get_bit_value(delay):
    if delay <= MIDPOINT_TIME:
        return 1
    else:
        return 0


def get_boundary_index(chunks):
    for i in range(len(chunks)):
        if (i + 1) < (len(chunks) - 1):
            if int(chunks[i], 2) == 0:
                if int(chunks[i + 1], 2) == 255:
                    return i + 2
    return None


def bits_to_string2(bits, has_boundary=False):
    completed = False
    boundary = Bits(BOUNDARY_BITS)
    # find the message boundary special chars
    pos = bits.find(boundary)
    if len(pos) == 0:
        return ''
    begin_pos = pos[0]+len(boundary)
    # print("Found boundary at {}".format(begin_pos))
    # Check for ending boundary
    pos = bits.find(boundary, begin_pos)
    end_pos = None
    if len(pos) == 1:
        end_pos = pos[0]
        # print('found end pos {}'.format(end_pos))
        completed = True
        message = bits[begin_pos:end_pos]
    else:
        message = bits[begin_pos:]
    message_bytes = message.tobytes()
    secret_message = message_bytes.decode('ascii')
    return secret_message, completed, end_pos

def main():
    # Create a TCP/IP socket
    listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Bind the socket to a specific address and port
    listen_sock.bind(SERVER_ADDRESS)

    # Listen for incoming connections
    listen_sock.listen(1)

    # Wait for a connection
    print('waiting for a connection...')
    client_sock, client_addr = listen_sock.accept()
    print('client connected:', client_addr)

    # Receive the data and extract the secret message from the time delays
    time_array = []
    bits = BitStream()
    start_time = last_recv_time = time.monotonic()
    # throw away the first time diff
    time_diff, last_recv_time = receive_byte_with_time(client_sock, last_recv_time)
    while True:
        time_diff, last_recv_time = receive_byte_with_time(client_sock, last_recv_time)
        # dont append obvious errors
        if time_diff > 0.250:
            continue
        # time_array.append(time_diff)
        bit = get_bit_value(time_diff)
        bits.append("0b{bit}".format(bit=bit))
        # print(bits.bin)
        try:
            decode_attempt, completed, end_pos = bits_to_string2(bits)
            # print(decode_attempt)
            # restart trying to decode
            if completed:
                print("Decoded message:" + decode_attempt)
                total_time = time.monotonic() - start_time
                print("Total time: {}".format(total_time))
                print("bits/second: {}".format(len(decode_attempt)*8/total_time))
                start_time = time.monotonic()
                # truncate the bits array and start again
                bits = bits[end_pos:]
        except ValueError:
            continue

    # When you're done, close the socket objects
    client_sock.close()
    listen_sock.close()


if __name__ == '__main__':
    main()
