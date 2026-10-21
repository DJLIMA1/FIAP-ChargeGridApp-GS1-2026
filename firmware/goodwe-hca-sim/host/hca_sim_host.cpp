// Servidor Modbus TCP de HOST (macOS/Linux) com a MESMA lógica do carregador simulado
// (lib/hca_sim_core) e o MESMO Modbus TCP mínimo do firmware (firmware/shared/hca_g2).
// Serve para testar a tela/ferramentas sem o ESP32: tools/tests/test_hca_sim_e2e.py.
//
//   hca_sim_host --port 1502 --address 1 [--speed 100]
//
// --speed multiplica o relógio (100 = o watchdog de 15 s dispara em 150 ms). O relé é
// impresso em stdout ("RELAY CLOSED"/"RELAY OPEN"). Nunca abre porta serial nem GPIO.
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <signal.h>
#include <sys/socket.h>
#include <unistd.h>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "hca_sim_core.h"
#include "modbus_tcp.h"

namespace {
struct Connection {
  int fd;
  std::vector<uint8_t> buffer;
};
double speed = 1;
uint32_t nowMs() {
  using namespace std::chrono;
  static const auto start = steady_clock::now();
  return static_cast<uint32_t>(duration_cast<milliseconds>(steady_clock::now() - start).count() * speed);
}
}  // namespace

int main(int argc, char** argv) {
  int port = 1502, address = 1;
  for (int i = 1; i + 1 < argc; i += 2) {
    if (!strcmp(argv[i], "--port")) port = atoi(argv[i + 1]);
    else if (!strcmp(argv[i], "--address")) address = atoi(argv[i + 1]);
    else if (!strcmp(argv[i], "--speed")) speed = atof(argv[i + 1]);
  }
  signal(SIGPIPE, SIG_IGN);
  hcasim::Charger charger(hca::kGw7k, static_cast<uint8_t>(address));
  charger.boot(nowMs(), hca::kGw7k.maxTenths, hca::kFastMode);
  const int listener = socket(AF_INET, SOCK_STREAM, 0);
  int yes = 1;
  setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
  sockaddr_in bind_address{};
  bind_address.sin_family = AF_INET;
  bind_address.sin_port = htons(static_cast<uint16_t>(port));
  bind_address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  if (bind(listener, reinterpret_cast<sockaddr*>(&bind_address), sizeof(bind_address)) || listen(listener, 4)) {
    perror("bind/listen");
    return 1;
  }
  printf("LISTENING %d unit %d (SIMULADO)\n", port, charger.address());
  fflush(stdout);
  std::vector<Connection> connections;
  bool relay = false;
  for (;;) {
    std::vector<pollfd> fds{{listener, POLLIN, 0}};
    for (auto& connection : connections) fds.push_back({connection.fd, POLLIN, 0});
    poll(fds.data(), fds.size(), 5);
    charger.tick(nowMs());
    if (fds[0].revents & POLLIN) {
      const int fd = accept(listener, nullptr, nullptr);
      if (fd >= 0) {
        setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &yes, sizeof(yes));
        connections.push_back({fd, {}});
      }
    }
    for (size_t i = 1; i < fds.size(); ++i) {
      if (!(fds[i].revents & (POLLIN | POLLHUP | POLLERR))) continue;
      Connection& connection = connections[i - 1];
      uint8_t chunk[512];
      const ssize_t got = recv(connection.fd, chunk, sizeof(chunk), 0);
      if (got <= 0) { close(connection.fd); connection.fd = -1; continue; }
      connection.buffer.insert(connection.buffer.end(), chunk, chunk + got);
      while (!connection.buffer.empty()) {
        const long frame = mbtcp::frameLength(connection.buffer.data(), connection.buffer.size());
        if (frame < 0) { close(connection.fd); connection.fd = -1; break; }
        if (frame == 0) break;
        uint8_t response[mbtcp::kMaxAdu];
        charger.tick(nowMs());
        const size_t size = mbtcp::serve(connection.buffer.data(), frame, charger.address(), charger, response);
        if (size) send(connection.fd, response, size, 0);
        connection.buffer.erase(connection.buffer.begin(), connection.buffer.begin() + frame);
      }
    }
    std::vector<Connection> open;
    for (auto& connection : connections) if (connection.fd >= 0) open.push_back(connection);
    connections.swap(open);
    if (charger.relayClosed() != relay) {
      relay = charger.relayClosed();
      printf("RELAY %s 10029=%u 10060=%u status=%u fault=%u\n", relay ? "CLOSED" : "OPEN",
             charger.reg(hca::kMaxChargingPower), charger.reg(hca::kStartStop), charger.reg(hca::kStatus), charger.fault());
      fflush(stdout);
    }
  }
}
