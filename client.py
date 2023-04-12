import socket
import time
import random
import sys
from common import *
from bitstring import BitArray


def string_to_bits2(secret_message):
    # convert string to ascii bytes
    secret_encoded = secret_message.encode('ascii')
    bits = BitArray(secret_encoded)
    return bits


def string_to_bits(secret_message):
    # Convert each character in the secret message to its binary representation
    binary_string = ''.join([format(ord(char), '08b') for char in secret_message])

    # Pad the binary string with zeroes so that its length is a multiple of 8
    padding = 8 - len(binary_string) % 8
    if padding != 8:
        binary_string += '0' * padding

    # Convert the binary string to a list of individual bits
    bits = [int(bit) for bit in binary_string]
    return bits


def pad_with_break2(bits):
    bits.prepend(BOUNDARY_BITS)
    return bits


def pad_with_break(bits):
    padding = [0] * 8 + [1] * 8
    return padding + bits


def get_secret_message() -> str:
    # return "foo bar"
    """Prompts the user to enter a secret message and returns it."""
    return input("Enter secret message to be transmitted: ")


def generate_delays2(bits):
    delays = []
    for bit in bits:
        if bit == 1:
            delay = random.uniform(BIT_1_LOWER_BOUND, BIT_1_UPPER_BOUND)
        else:
            delay = random.uniform(BIT_0_LOWER_BOUND, BIT_0_UPPER_BOUND)
        delays.append(delay)
    return delays


def generate_delays(bits):
    delays = []
    for bit in bits:
        if bit:
            delay = BIT_1_LOWER_BOUND
        else:
            delay = BIT_0_LOWER_BOUND
        delays.append(delay)
    return delays


def send_byte_with_delay(sock, delay):
    # Generate a random byte
    byte = bytes([random.randint(0, 255)])

    # Send the byte and wait for the appropriate delay
    try:
        sock.sendall(byte)
        time.sleep(delay)
    except BrokenPipeError:
        print("Server closed the connection.")
        sock.close()
        sys.exit(1)


def send_message(sock: socket.socket, delays):
    # Send each bit with a time delay between each byte
    for delay in delays:
        send_byte_with_delay(sock, delay)


def connect_to_server(host: str, port: int) -> socket.socket:
    """Creates a new socket and connects to the specified host and port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    return sock


def main():
    host = '127.0.0.1'
    port = 1234

    message = get_secret_message()
    bits = string_to_bits2(message)
    padded_bits = pad_with_break2(bits)
    delays = generate_delays(padded_bits)
    print(delays)
    with connect_to_server(host, port) as sock:
        while True:
            send_message(sock, delays)
    response = sock.recv(1024)
    print(response.decode())


if __name__ == '__main__':
    main()