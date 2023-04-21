import socket
import time
import BitCloakDecoding

# Define the server address and port
SERVER_ADDRESS = ('localhost', 1234)


def receive_byte(sock):
    try:
        # Receive the byte from the socket
        data = sock.recv(1)
        if not data:
            print("no data received")
            return False
        return True
    except (OSError, ConnectionResetError, ConnectionAbortedError) as e:
        # Handle case where socket is no longer connected
        print("Socket error:", e)
        return False


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
    cloak = BitCloakDecoding.BitCloakDecoding()
    cloak.start_timer()
    # throw away the first time diff
    receive_byte(client_sock)
    cloak.mark_time()
    while True:
        if receive_byte(client_sock):
            cloak.mark_time()
        else:
            break

    # When you're done, close the socket objects
    client_sock.close()
    listen_sock.close()


if __name__ == '__main__':
    main()
