from temporal_cloak.client import TemporalCloakClient


def main():
    message = input("Enter secret message to be transmitted: ")
    with TemporalCloakClient() as client:
        client.set_message(message)
        client.send_sync_byte()
        while True:
            client.send()


if __name__ == '__main__':
    main()
