#include "sensors.h"
#include <algorithm>
void SimulatedSensors::start() { energyWh = 0; }
Reading SimulatedSensors::read(bool charging, unsigned long elapsedMs) {
  const float power = charging ? 7200.0f : 0.0f;
  energyWh += power * elapsedMs / 3600000.0f;
  return {std::min(100.0f, 20.0f + energyWh / 600.0f), energyWh, power, charging};
}
