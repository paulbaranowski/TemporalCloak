from temporal_cloak.server import TemporalCloakServer


def main():
    with TemporalCloakServer() as server:
        server.accept_connection()
        server.receive()


if __name__ == '__main__':
    main()
