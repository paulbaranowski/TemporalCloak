import socket
import time
import random
import sys
from TemporalCloakEncoding import TemporalCloakEncoding


def get_secret_message() -> str:
    # return "foo bar"
    """Prompts the user to enter a secret message and returns it."""
    return input("Enter secret message to be transmitted: ")


def send_byte_with_delay(sock, delay: float) -> None:
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


def send_message(sock: socket.socket, delays: list) -> None:
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
    cloak = TemporalCloakEncoding()
    cloak.message = message
    with connect_to_server(host, port) as sock:
        while True:
            send_message(sock, cloak.delays)
    response = sock.recv(1024)
    print(response.decode())


if __name__ == '__main__':
    main()
