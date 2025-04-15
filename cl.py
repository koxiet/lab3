import socket
from _thread import *
import sys


def receive(client_socket):
    while True:
        try:
            message = client_socket.recv(1024).decode("utf-8")
            if not message:
                print("\nСоединение с сервером разорвано")
                sys.exit(0)
            print(f"\n{message}\nВведите сообщение: ", end="")
        except (ConnectionResetError, ConnectionAbortedError):
            print("\nСоединение с сервером разорвано")
            sys.exit(0)
        except Exception as e:
            print(f"\nОшибка получения сообщения: {e}")
            sys.exit(1)


def client_start(ip, server_port, tcp_port, client_ip):
    username = input("Введите ваше имя: ").strip()
    while not username:
        username = input("Введите ваше имя: ").strip()

    client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        client_sock.bind((client_ip, tcp_port))
    except OSError as e:
        print(f"Ошибка привязки к порту: {e}")
        new_port = int(input("Введите другой порт: "))
        client_sock.bind((client_ip, new_port))

    try:
        client_sock.connect((ip, server_port))
        client_sock.send(username.encode('utf-8'))

        print(f"\nВы подключились как {username}")

        start_new_thread(receive, (client_sock,))

        while True:
            message = input("Введите сообщение: ").strip()
            if not message:
                continue
            if message.lower() == "/exit":
                break
            try:
                client_sock.send(message.encode('utf-8'))
            except Exception as e:
                print(f"Ошибка отправки сообщения: {e}")
                break

    except Exception as e:
        print({e})
    finally:
        client_sock.close()
        print("Соединение закрыто")


if __name__ == '__main__':
    try:
        ip = input("Введите IP сервера: ") or '127.0.0.1'
        tcp_port = int(input("Введите TCP порт клиента: ") or 0)
        server_port = int(input("Введите порт сервера: ") or 8080)
        client_ip = input("Введите IP клиента: ") or '127.0.0.1'
        client_start(ip, server_port, tcp_port, client_ip)
    except ValueError:
        print("Ошибка: порт должен быть числом")
    except Exception as e:
        print({e})