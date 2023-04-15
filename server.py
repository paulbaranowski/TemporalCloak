import socket
import time
import BitCloakDecoding

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
    start_time = last_recv_time = time.monotonic()
    # throw away the first time diff
    time_diff, last_recv_time = receive_byte_with_time(client_sock, last_recv_time)
    while True:
        time_diff, last_recv_time = receive_byte_with_time(client_sock, last_recv_time)
        # dont append obvious errors
        if time_diff > 0.250:
            continue
        cloak.add_bit_by_delay(time_diff)
        # print(bits.bin)
        try:
            decode_attempt, completed, end_pos = cloak.bits_to_message()
            # print(decode_attempt)
            # restart trying to decode
            if completed:
                print("Decoded message: {}".format(decode_attempt))
                total_time = time.monotonic() - start_time
                print("Total time: {}".format(total_time))
                print("bits/second: {}".format(len(decode_attempt)*8/total_time))
                start_time = time.monotonic()
                # truncate the bits array and start again
                cloak.jump_to_next_message()
        except ValueError:
            continue

    # When you're done, close the socket objects
    client_sock.close()
    listen_sock.close()


if __name__ == '__main__':
    main()
