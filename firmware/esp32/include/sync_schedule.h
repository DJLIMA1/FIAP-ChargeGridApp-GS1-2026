#pragma once
#include <stdint.h>

// Agenda monotônica da central, sem Arduino/rede; os testes usam um relógio falso.
namespace syncschedule {
inline bool due(uint32_t now, uint32_t deadline) { return static_cast<int32_t>(now - deadline) >= 0; }
inline uint32_t afterBatch(uint32_t now, uint32_t interval, bool immediate) {
  return immediate ? now : now + interval;
}
class Requests {
 public:
  void request() { ++revision_; }
  uint32_t revision() const { return revision_; }
  bool mayAdvance(uint32_t now) const { return !retryBlocked_ || due(now, retryDeadline_); }
  void retryAfter(uint32_t deadline) { retryBlocked_ = true; retryDeadline_ = deadline; }
  void contacted() { retryBlocked_ = false; }
 private:
  uint32_t revision_ = 0;
  bool retryBlocked_ = false;
  uint32_t retryDeadline_ = 0;
};

// Sync vencido nunca elimina o giro físico. A decisão de enviar é tomada depois
// do polling, que pode bloquear ou pedir um envio por mudança online/offline.
template<class Tick, class Poll, class Sync>
void networkTurn(Tick tick, Poll poll, Sync sync) {
  tick();
  poll();
  tick();
  sync();
  tick();
}
}  // namespace syncschedule
