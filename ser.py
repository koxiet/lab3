import socket
from _thread import *
from datetime import datetime
import json
import sys

chat_history = []
connected_users = {}


def is_port_in_use(ip, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((ip, port))
            return False
        except OSError:
            return True


def save_history():
    try:
        with open('chat_history.json', 'w', encoding='utf-8') as f:
            json.dump(chat_history, f, ensure_ascii=False)
    except Exception as e:
        print({e})


def load_history():
    try:
        with open('chat_history.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    except Exception as e:
        print({e})
        return []


def broadcast(message, exclude_socket=None):
    for client in list(connected_users.keys()):
        if client != exclude_socket:
            try:
                client.send(message.encode('utf-8'))
            except:
                continue


def tcp(client_sock, client_ip, username):
    global chat_history

    welcome_msg = f"Добро пожаловать, {username}"
    try:
        client_sock.send(welcome_msg.encode('utf-8'))
    except:
        return
    while True:
        try:
            message = client_sock.recv(1024).decode("utf-8").strip()
            if not message:
                break

            if message == "/users":
                user_list = "\n".join([f"- {user}" for ip, user in connected_users.values()])
                response = f"=== Список пользователей ===\n{user_list}\n==="
                client_sock.send(response.encode('utf-8'))
                continue

            if message == "/hist":
                history = "\n".join(chat_history[-20:])
                response = f"=== История чата ===\n{history}\n==="
                client_sock.send(response.encode('utf-8'))
                continue

            timestamp = datetime.now().strftime("%H:%M")
            simple_msg = f"{username}: {message}"
            full_msg = f"[{timestamp}] {simple_msg}"

            print(full_msg)
            chat_history.append(full_msg)
            save_history()

            broadcast(simple_msg, exclude_socket=client_sock)

        except (ConnectionResetError, ConnectionAbortedError):
            break

    leave_message = f"{username} покинул чат"
    print(f"[{datetime.now().strftime('%H:%M')}] {leave_message}")
    chat_history.append(f"[{datetime.now().strftime('%H:%M')}] {leave_message}")
    save_history()

    try:
        if client_sock in connected_users:
            del connected_users[client_sock]
        broadcast(leave_message)
    except Exception as e:
        print(f"Ошибка при отправке сообщения: {e}")
    finally:
        try:
            client_sock.close()
        except:
            pass


def start_server(server_ip, server_tcp_port):
    global chat_history
    chat_history = load_history()
    if is_port_in_use(server_ip, server_tcp_port):
        print(f"Порт {server_tcp_port} на IP {server_ip} уже занят")
        sys.exit(1)

    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((server_ip, server_tcp_port))
        server_socket.listen(5)
    except OSError as e:
        print({e})
        sys.exit(1)

    print(f"Сервер запущен на {server_ip}:{server_tcp_port}")

    try:
        while True:
            try:
                client_socket, (client_ip, _) = server_socket.accept()
                username = client_socket.recv(1024).decode("utf-8").strip()

                connected_users[client_socket] = (client_ip, username)
                start_message = f"[{datetime.now().strftime('%H:%M')}] {username} присоединился к чату"
                print(start_message)
                chat_history.append(start_message)
                save_history()

                broadcast(start_message, exclude_socket=client_socket)
                start_new_thread(tcp, (client_socket, client_ip, username))

            except Exception as e:
                print({e})
                continue

    except KeyboardInterrupt:
        print("\nСервер завершает работу")
    finally:
        server_socket.close()
        print("Сервер остановлен")


if __name__ == "__main__":
    try:
        server_ip = input("Введите IP сервера: ")
        server_tcp_port = int(input("Введите TCP порт сервера: "))
        start_server(server_ip, server_tcp_port)
    except ValueError:
        print("Ошибка: порт должен быть числом")
    except Exception as e:
        print(f"Неожиданная ошибка: {e}")