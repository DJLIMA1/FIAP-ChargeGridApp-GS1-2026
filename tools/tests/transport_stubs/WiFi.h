#pragma once
#include "Arduino.h"
#include <vector>
#include "hca_sim_core.h"
#include "modbus_tcp.h"
constexpr int WL_CONNECTED = 3;
class IPAddress {
 public:
  uint32_t value = 0;
  IPAddress() = default;
  IPAddress(unsigned a,unsigned b,unsigned c,unsigned d) : value((a<<24)|(b<<16)|(c<<8)|d) {}
  bool fromString(const String& text) {
    unsigned a,b,c,d; char tail;
    if (sscanf(text.c_str(),"%u.%u.%u.%u%c",&a,&b,&c,&d,&tail)!=4 || a>255 || b>255 || c>255 || d>255) return false;
    value=(a<<24)|(b<<16)|(c<<8)|d;return true;
  }
  String toString() const { return String(std::to_string(value>>24)+"."+std::to_string((value>>16)&255)+"."+std::to_string((value>>8)&255)+"."+std::to_string(value&255)); }
  bool operator==(const IPAddress& other) const { return value==other.value; }
  bool operator!=(const IPAddress& other) const { return !(*this==other); }
};
namespace fakenet {
struct Peer {
  IPAddress ip;
  bool tcpAccept=true, reply=true, writeFail=false;
  hcasim::Charger charger{hca::kGw7k,1};
  std::vector<uint16_t> runWrites;
  explicit Peer(IPAddress address) : ip(address) { charger.boot(testMillis,70,0); }
};
inline std::vector<Peer> peers;
inline std::vector<IPAddress> connections;
inline IPAddress dns;
}
struct WiFiStub {
  int connection=WL_CONNECTED;
  IPAddress local{192,168,0,10};
  int status() const { return connection; }
  IPAddress localIP() const { return local; }
  int hostByName(const char*,IPAddress& out) { out=fakenet::dns;return out!=IPAddress(0,0,0,0); }
};
inline WiFiStub WiFi;
class WiFiClient {
 public:
  bool connected() { return connected_; }
  void stop() { connected_=false;buffer_.clear();offset_=0; }
  int connect(IPAddress ip,uint16_t,int32_t timeout) {
    fakenet::connections.push_back(ip);
    for (auto& peer:fakenet::peers) if (peer.ip==ip) {
      peer_=&peer;connected_=peer.tcpAccept;
      if (!connected_) delay(timeout);
      return connected_;
    }
    delay(timeout);return 0;
  }
  void setNoDelay(bool) {}
  int available() { return buffer_.size()-offset_; }
  int read() { return available() ? buffer_[offset_++] : -1; }
  int read(uint8_t* out,size_t size) {
    const size_t count=min(size,size_t(available()));
    memcpy(out,buffer_.data()+offset_,count);offset_+=count;return count;
  }
  size_t write(const uint8_t* data,size_t size) {
    if (!connected_ || !peer_ || peer_->writeFail) return 0;
    buffer_.clear();offset_=0;
    if (!peer_->reply) return size;
    if (size>=12 && data[7]==6 && ((data[8]<<8)|data[9])==hca::kStartStop)
      peer_->runWrites.push_back((data[10]<<8)|data[11]);
    peer_->charger.tick(testMillis);
    uint8_t response[mbtcp::kMaxAdu];
    const size_t length=mbtcp::serve(data,size,peer_->charger.address(),peer_->charger,response);
    buffer_.assign(response,response+length);return size;
  }
 private:
  bool connected_=false;
  fakenet::Peer* peer_=nullptr;
  std::vector<uint8_t> buffer_;
  size_t offset_=0;
};
